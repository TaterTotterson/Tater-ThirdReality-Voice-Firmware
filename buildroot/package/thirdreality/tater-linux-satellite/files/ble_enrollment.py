"""One-shot BlueZ handoff used to enroll a BLE identity key.

The S420 normally gives its BCM43438 controller exclusively to the bounded raw
HCI observer.  During an explicit enrollment window this helper stops that
observer, runs a minimal BlueZ GATT peripheral, consumes the peer IRK from
BlueZ's root-only bond store, removes the temporary bond, and resumes passive
observation.
"""

from __future__ import annotations

import configparser
import logging
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Optional


_LOGGER = logging.getLogger(__name__)
_IRK_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9 ._-]+")
_BLUEZ_STORE = Path("/var/lib/bluetooth")


def read_identity_key(path: str | Path) -> str:
    """Return a normalized peer IRK without logging or exposing other keys."""

    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
        value = parser.get("IdentityResolvingKey", "Key", fallback="").strip()
    except (OSError, configparser.Error):
        return ""
    return value.lower() if _IRK_RE.fullmatch(value) else ""


class LinuxBleEnrollment:
    def __init__(
        self,
        on_event: Callable[[str, dict[str, Any]], None],
        observer: Any,
        *,
        store_path: str | Path = _BLUEZ_STORE,
    ) -> None:
        self.on_event = on_event
        self.observer = observer
        self.store_path = Path(store_path)
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._active_id = ""
        self._status = "idle"

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": bool(self._active_id),
                "enrollment_id": self._active_id,
                "status": self._status,
            }

    def start(self, payload: dict[str, Any]) -> None:
        enrollment_id = str(payload.get("enrollment_id") or "").strip()
        display_name = _SAFE_NAME_RE.sub("", str(payload.get("display_name") or "").strip())[:28]
        if not _ID_RE.fullmatch(enrollment_id) or not display_name:
            raise ValueError("Invalid BLE enrollment request.")
        try:
            timeout_s = max(30, min(180, int(payload.get("timeout_s") or 90)))
        except (TypeError, ValueError, OverflowError):
            timeout_s = 90
        with self._lock:
            if self._active_id:
                raise RuntimeError("BLE enrollment is already active.")
            self._active_id = enrollment_id
            self._status = "starting"
            self._cancel.clear()
            self._thread = threading.Thread(
                target=self._run,
                args=(enrollment_id, display_name, timeout_s),
                name="tater-ble-enrollment",
                daemon=True,
            )
            self._thread.start()

    def cancel(self, enrollment_id: str = "") -> None:
        with self._lock:
            if not self._active_id:
                return
            if enrollment_id and enrollment_id != self._active_id:
                return
            self._cancel.set()

    def stop(self) -> None:
        self._cancel.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)

    def _emit(self, message_type: str, payload: dict[str, Any]) -> None:
        try:
            self.on_event(message_type, payload)
        except Exception:  # pragma: no cover - transport-specific safety net
            _LOGGER.exception("Unable to send BLE enrollment state")

    def _set_status(self, enrollment_id: str, status: str, error: str = "") -> None:
        with self._lock:
            if self._active_id == enrollment_id:
                self._status = status
        payload = {"enrollment_id": enrollment_id, "status": status}
        if error:
            payload["error"] = error[:160]
        self._emit("ble.enrollment.status", payload)

    @staticmethod
    def _binary(name: str, candidates: tuple[str, ...]) -> str:
        found = shutil.which(name)
        if found:
            return found
        for candidate in candidates:
            if Path(candidate).is_file():
                return candidate
        return ""

    def _find_peer_irk(self, started_at: float) -> tuple[str, str]:
        try:
            paths = list(self.store_path.glob("*/*/info"))
        except OSError:
            return "", ""
        for info_path in paths:
            try:
                if info_path.stat().st_mtime + 1.0 < started_at:
                    continue
            except OSError:
                continue
            irk = read_identity_key(info_path)
            if irk:
                return info_path.parent.name, irk
        return "", ""

    @staticmethod
    def _write_command(process: subprocess.Popen[str], command: str, delay: float = 0.12) -> None:
        if process.stdin is None:
            raise RuntimeError("bluetoothctl input is unavailable")
        process.stdin.write(command + "\n")
        process.stdin.flush()
        time.sleep(delay)

    def _configure_controller(
        self,
        process: subprocess.Popen[str],
        display_name: str,
        timeout_s: int,
    ) -> None:
        commands = (
            "power on",
            "pairable on",
            "discoverable on",
            "agent NoInputNoOutput",
            "default-agent",
            "menu gatt",
            "register-service 180d",
            "yes",
            "register-characteristic 2a38 read",
            "00",
            "register-characteristic 2a37 notify",
            "00 48",
            "register-application",
            "back",
            "menu advertise",
            "uuids 180d",
            f"name {display_name}",
            "discoverable on",
            f"timeout {timeout_s}",
            "back",
            "advertise on",
        )
        for command in commands:
            if self._cancel.is_set():
                return
            self._write_command(process, command)

    def _run(self, enrollment_id: str, display_name: str, timeout_s: int) -> None:
        bluetoothd: Optional[subprocess.Popen[bytes]] = None
        bluetoothctl: Optional[subprocess.Popen[str]] = None
        peer_address = ""
        completed = False
        self._emit(
            "ble.enrollment.status",
            {"enrollment_id": enrollment_id, "status": "starting"},
        )
        try:
            self.observer.stop()
            daemon_path = self._binary(
                "bluetoothd",
                ("/usr/libexec/bluetooth/bluetoothd", "/usr/lib/bluetooth/bluetoothd"),
            )
            ctl_path = self._binary("bluetoothctl", ("/usr/bin/bluetoothctl",))
            if not daemon_path or not ctl_path:
                raise RuntimeError("BlueZ enrollment support is not installed.")
            bluetoothd = subprocess.Popen(  # noqa: S603 - fixed root-owned binary
                [daemon_path, "--nodetach"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.6)
            bluetoothctl = subprocess.Popen(  # noqa: S603 - fixed root-owned binary
                [ctl_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            started_at = time.time()
            self._configure_controller(bluetoothctl, display_name, timeout_s)
            if self._cancel.is_set():
                self._set_status(enrollment_id, "cancelled")
                return
            self._set_status(enrollment_id, "advertising")
            deadline = time.monotonic() + timeout_s
            while not self._cancel.wait(0.25):
                peer_address, irk = self._find_peer_irk(started_at)
                if irk:
                    # Serialization happens before this local reference is dropped.
                    self._emit(
                        "ble.enrollment.result",
                        {"enrollment_id": enrollment_id, "ok": True, "irk": irk},
                    )
                    irk = ""
                    completed = True
                    break
                if time.monotonic() >= deadline:
                    self._set_status(
                        enrollment_id,
                        "timed_out",
                        "No device paired before the enrollment window closed.",
                    )
                    break
            if self._cancel.is_set() and not completed:
                self._set_status(enrollment_id, "cancelled")
        except Exception as exc:
            self._emit(
                "ble.enrollment.result",
                {"enrollment_id": enrollment_id, "ok": False, "error": str(exc)[:160]},
            )
        finally:
            if bluetoothctl is not None:
                try:
                    if peer_address:
                        self._write_command(bluetoothctl, f"remove {peer_address}", delay=0.05)
                    self._write_command(bluetoothctl, "advertise off", delay=0.05)
                    self._write_command(bluetoothctl, "quit", delay=0.05)
                except (OSError, RuntimeError):
                    pass
                if bluetoothctl.poll() is None:
                    bluetoothctl.terminate()
                    try:
                        bluetoothctl.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        bluetoothctl.kill()
            if bluetoothd is not None and bluetoothd.poll() is None:
                bluetoothd.terminate()
                try:
                    bluetoothd.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    bluetoothd.kill()
            with self._lock:
                if self._active_id == enrollment_id:
                    self._active_id = ""
                    self._status = "complete" if completed else "idle"
                self._thread = None
            self.observer.start()
