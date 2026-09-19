"""Bounded Linux HCI observer for Tater BLE presence reports.

The S420 uses a Broadcom AP6212 combo radio.  This module talks directly to
the kernel HCI socket so the firmware does not need bluetoothd, D-Bus object
tracking, pairing support, or the rest of the BlueZ userspace runtime.
"""

from __future__ import annotations

from collections import OrderedDict
import errno
import fcntl
import logging
from pathlib import Path
import socket
import struct
import threading
import time
from typing import Any, Callable, Optional


_LOGGER = logging.getLogger(__name__)

_AF_BLUETOOTH = getattr(socket, "AF_BLUETOOTH", 31)
_BTPROTO_HCI = getattr(socket, "BTPROTO_HCI", 1)
_SOL_HCI = 0
_HCI_FILTER = 2
_HCI_COMMAND_PKT = 0x01
_HCI_EVENT_PKT = 0x04
_EVT_LE_META_EVENT = 0x3E
_EVT_LE_ADVERTISING_REPORT = 0x02
_OGF_LE_CTL = 0x08
_OCF_LE_SET_SCAN_PARAMETERS = 0x000B
_OCF_LE_SET_SCAN_ENABLE = 0x000C
_HCIDEVUP = 0x400448C9

_SCAN_INTERVAL_UNITS = 512  # 320 ms, matching the constrained ESP32 targets.
_SCAN_WINDOW_UNITS = 48  # 30 ms, about a 9.4% receive duty cycle.
_BATCH_MAX = 24
_DEDUPE_MAX = 48
_DATA_MAX = 31
_RSSI_DELTA_DB = 3
_EMIT_MIN_MS = 250
_EMIT_MAX_MS = 1000
_BATCH_FLUSH_MS = 500
_RETRY_SECONDS = 2.0


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


def _opcode(ogf: int, ocf: int) -> int:
    return (int(ogf) << 10) | int(ocf)


def _hci_command(ogf: int, ocf: int, parameters: bytes) -> bytes:
    return struct.pack("<BHB", _HCI_COMMAND_PKT, _opcode(ogf, ocf), len(parameters)) + parameters


def parse_le_advertising_reports(packet: bytes) -> list[dict[str, Any]]:
    """Decode legacy LE advertising reports from a raw HCI event packet."""
    raw = bytes(packet or b"")
    if len(raw) < 5 or raw[0] != _HCI_EVENT_PKT or raw[1] != _EVT_LE_META_EVENT:
        return []
    packet_end = 3 + raw[2]
    if packet_end > len(raw) or raw[3] != _EVT_LE_ADVERTISING_REPORT:
        return []

    report_count = raw[4]
    offset = 5
    reports: list[dict[str, Any]] = []
    for _index in range(report_count):
        if offset + 10 > packet_end:
            return []
        event_type = raw[offset]
        address_type = raw[offset + 1]
        address_bytes = raw[offset + 2 : offset + 8]
        data_length = raw[offset + 8]
        data_start = offset + 9
        data_end = data_start + data_length
        if data_end >= packet_end:
            return []
        data = raw[data_start:data_end]
        rssi = struct.unpack("b", raw[data_end : data_end + 1])[0]
        reports.append(
            {
                "address": ":".join(f"{value:02x}" for value in reversed(address_bytes)),
                "address_type": int(address_type),
                "rssi": int(rssi),
                "event_type": int(event_type),
                "data": bytes(data[:_DATA_MAX]),
            }
        )
        offset = data_end + 1
    return reports


class LinuxBleScanner:
    """Passive BLE scanner with fixed memory and bandwidth bounds."""

    def __init__(
        self,
        on_batch: Callable[[dict[str, Any]], None],
        *,
        device_id: int = 0,
        should_pause: Optional[Callable[[], bool]] = None,
        availability_path: str | Path | None = "/etc/bluetooth/bcm4343a1.hcd",
    ) -> None:
        self.on_batch = on_batch
        self.device_id = max(0, int(device_id))
        self.should_pause = should_pause
        self.available = availability_path is None or Path(availability_path).is_file()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._socket_lock = threading.Lock()
        self._socket: Optional[socket.socket] = None
        self._pending: "OrderedDict[tuple[str, int], dict[str, Any]]" = OrderedDict()
        self._dedupe: "OrderedDict[tuple[str, int, int, bytes], tuple[int, int]]" = OrderedDict()
        self._last_flush_ms = _monotonic_ms()
        self._batch_id = 0
        self._stats: dict[str, Any] = {
            "available": self.available,
            "running": False,
            "scanning": False,
            "paused": False,
            "adverts_seen": 0,
            "adverts_filtered": 0,
            "adverts_dropped": 0,
            "batches_sent": 0,
            "controller_restarts": 0,
            "last_error": "",
        }

    def start(self) -> None:
        if not self.available or (self._thread is not None and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="tater-ble-observer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._socket_lock:
            active_socket = self._socket
        if active_socket is not None:
            try:
                active_socket.close()
            except OSError:
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        self._pending.clear()
        self._stats.update({"running": False, "scanning": False, "paused": False})

    def status(self) -> dict[str, Any]:
        return dict(self._stats)

    def _pause_requested(self) -> bool:
        if self.should_pause is None:
            return False
        try:
            return bool(self.should_pause())
        except Exception:  # pylint: disable=broad-except
            _LOGGER.debug("BLE pause predicate failed", exc_info=True)
            return True

    @staticmethod
    def _set_event_filter(hci_socket: socket.socket) -> None:
        type_mask = 1 << _HCI_EVENT_PKT
        event_mask_low = 0
        event_mask_high = 1 << (_EVT_LE_META_EVENT - 32)
        hci_socket.setsockopt(
            _SOL_HCI,
            _HCI_FILTER,
            struct.pack("=IIIH", type_mask, event_mask_low, event_mask_high, 0),
        )

    @staticmethod
    def _set_scan_enabled(hci_socket: socket.socket, enabled: bool) -> None:
        parameters = struct.pack("<BB", 1 if enabled else 0, 0)
        hci_socket.send(_hci_command(_OGF_LE_CTL, _OCF_LE_SET_SCAN_ENABLE, parameters))

    @staticmethod
    def _set_scan_parameters(hci_socket: socket.socket) -> None:
        # Passive scan, public local address, accept all advertisers.
        parameters = struct.pack(
            "<BHHBB",
            0,
            _SCAN_INTERVAL_UNITS,
            _SCAN_WINDOW_UNITS,
            0,
            0,
        )
        hci_socket.send(_hci_command(_OGF_LE_CTL, _OCF_LE_SET_SCAN_PARAMETERS, parameters))

    def _open_socket(self) -> socket.socket:
        control_socket = socket.socket(_AF_BLUETOOTH, socket.SOCK_RAW, _BTPROTO_HCI)
        try:
            try:
                fcntl.ioctl(control_socket.fileno(), _HCIDEVUP, struct.pack("I", self.device_id))
            except OSError as exc:
                if exc.errno not in {errno.EALREADY, errno.EBUSY}:
                    raise
        finally:
            control_socket.close()

        hci_socket = socket.socket(_AF_BLUETOOTH, socket.SOCK_RAW, _BTPROTO_HCI)
        hci_socket.bind((self.device_id,))
        hci_socket.settimeout(0.25)
        self._set_event_filter(hci_socket)
        try:
            self._set_scan_enabled(hci_socket, False)
        except OSError:
            pass
        self._set_scan_parameters(hci_socket)
        self._set_scan_enabled(hci_socket, True)
        return hci_socket

    def _run(self) -> None:
        self._stats["running"] = True
        while not self._stop.is_set():
            hci_socket: Optional[socket.socket] = None
            try:
                hci_socket = self._open_socket()
                with self._socket_lock:
                    self._socket = hci_socket
                self._stats.update(
                    {
                        "scanning": True,
                        "paused": False,
                        "last_error": "",
                    }
                )
                _LOGGER.info("Tater BLE observer started on hci%d", self.device_id)
                self._receive_loop(hci_socket)
            except Exception as exc:  # pylint: disable=broad-except
                if not self._stop.is_set():
                    self._stats["last_error"] = str(exc)
                    self._stats["controller_restarts"] = int(self._stats["controller_restarts"]) + 1
                    _LOGGER.warning("BLE observer unavailable (%s); retrying", exc)
                    self._stop.wait(_RETRY_SECONDS)
            finally:
                self._stats["scanning"] = False
                with self._socket_lock:
                    if self._socket is hci_socket:
                        self._socket = None
                if hci_socket is not None:
                    try:
                        self._set_scan_enabled(hci_socket, False)
                    except OSError:
                        pass
                    try:
                        hci_socket.close()
                    except OSError:
                        pass
        self._stats.update({"running": False, "scanning": False, "paused": False})

    def _receive_loop(self, hci_socket: socket.socket) -> None:
        paused = False
        while not self._stop.is_set():
            pause_requested = self._pause_requested()
            if pause_requested != paused:
                paused = pause_requested
                self._stats.update({"paused": paused, "scanning": not paused})
                if paused:
                    self._set_scan_enabled(hci_socket, False)
                    self._pending.clear()
                else:
                    self._set_scan_parameters(hci_socket)
                    self._set_scan_enabled(hci_socket, True)
                _LOGGER.debug("BLE observer %s for audio activity", "paused" if paused else "resumed")
            if paused:
                self._stop.wait(0.25)
                continue

            try:
                packet = hci_socket.recv(260)
            except socket.timeout:
                self._flush(_monotonic_ms())
                continue
            for advert in parse_le_advertising_reports(packet):
                self._ingest_advert(advert, _monotonic_ms())
            self._flush(_monotonic_ms())

    def _ingest_advert(self, advert: dict[str, Any], now_ms: int) -> bool:
        self._stats["adverts_seen"] = int(self._stats["adverts_seen"]) + 1
        address = str(advert.get("address") or "").lower()
        address_type = int(advert.get("address_type") or 0)
        event_type = int(advert.get("event_type") or 0)
        rssi = int(advert.get("rssi") or -127)
        data = bytes(advert.get("data") or b"")[:_DATA_MAX]
        dedupe_key = (address, address_type, event_type, data)
        previous = self._dedupe.get(dedupe_key)
        emit = previous is None
        if previous is not None:
            previous_ms, previous_rssi = previous
            elapsed_ms = max(0, now_ms - previous_ms)
            emit = elapsed_ms >= _EMIT_MAX_MS or (
                abs(rssi - previous_rssi) >= _RSSI_DELTA_DB and elapsed_ms >= _EMIT_MIN_MS
            )
        self._dedupe[dedupe_key] = (now_ms if emit else previous[0], rssi if emit else previous[1]) if previous else (now_ms, rssi)
        self._dedupe.move_to_end(dedupe_key)
        while len(self._dedupe) > _DEDUPE_MAX:
            self._dedupe.popitem(last=False)
        if not emit:
            self._stats["adverts_filtered"] = int(self._stats["adverts_filtered"]) + 1
            return False

        pending_key = (address, event_type)
        if pending_key not in self._pending and len(self._pending) >= _BATCH_MAX:
            self._stats["adverts_dropped"] = int(self._stats["adverts_dropped"]) + 1
            return False
        self._pending[pending_key] = {
            "address": address,
            "address_type": address_type,
            "rssi": max(-127, min(20, rssi)),
            "event_type": max(0, min(255, event_type)),
            "data": data.hex(),
            "observed_ms": now_ms,
        }
        self._pending.move_to_end(pending_key)
        return True

    def _flush(self, now_ms: int, *, force: bool = False) -> bool:
        if not self._pending:
            return False
        if not force and len(self._pending) < _BATCH_MAX and now_ms - self._last_flush_ms < _BATCH_FLUSH_MS:
            return False
        rows = []
        for advert in self._pending.values():
            row = dict(advert)
            observed_ms = int(row.pop("observed_ms"))
            row["age_ms"] = max(0, min(60_000, now_ms - observed_ms))
            rows.append(row)
        self._pending.clear()
        self._last_flush_ms = now_ms
        self._batch_id = (self._batch_id + 1) & 0xFFFFFFFF
        if self._batch_id == 0:
            self._batch_id = 1
        payload = {
            "version": 1,
            "batch_id": self._batch_id,
            "device_uptime_ms": now_ms,
            "adverts": rows,
        }
        try:
            self.on_batch(payload)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Could not submit BLE advertisements to Tater")
            return False
        self._stats["batches_sent"] = int(self._stats["batches_sent"]) + 1
        return True
