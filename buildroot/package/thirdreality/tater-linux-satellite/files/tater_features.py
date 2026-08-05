"""Tater-native controls layered onto the reusable Linux audio state machine."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.request import Request, urlopen

from .peripheral_api import LVAEvent

_LOGGER = logging.getLogger(__name__)
_PROTOCOL_VERSION = 1
_MAX_TIMERS = 8
_MAX_TIMER_SECONDS = 7 * 24 * 60 * 60
_SETTINGS_PATH = Path("/data/conf/tater-live-settings.json")
_OTA_PATH = Path("/data/tater/software.swu")
_SWUPDATE_KEY = Path("/etc/swupdate-public.pem")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _integer(value: Any, default: int = 0, *, minimum: int = 0, maximum: int = 2**31 - 1) -> int:
    try:
        result = int(round(float(value)))
    except (TypeError, ValueError):
        result = default
    return max(minimum, min(maximum, result))


def _frame(message_type: str, payload: Optional[dict[str, Any]] = None) -> str:
    return json.dumps(
        {
            "v": _PROTOCOL_VERSION,
            "type": message_type,
            "id": uuid.uuid4().hex,
            "ts": time.time(),
            "payload": payload if isinstance(payload, dict) else {},
        },
        separators=(",", ":"),
    )


@dataclass
class _Timer:
    timer_id: str
    name: str
    original_duration_ms: int
    deadline: float
    task: Optional[asyncio.Task[None]] = None
    ringing: bool = False

    def public(self) -> dict[str, Any]:
        remaining_ms = 0 if self.ringing else max(0, int(round((self.deadline - time.monotonic()) * 1000)))
        return {
            "id": self.timer_id,
            "name": self.name,
            "label": self.name,
            "state": "ringing" if self.ringing else "armed",
            "active": True,
            "ringing": self.ringing,
            "original_duration_ms": self.original_duration_ms,
            "duration_ms": self.original_duration_ms,
            "remaining_ms": remaining_ms,
        }


class TaterFeatureManager:
    """Handle Tater commands that are independent of the voice transport."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.satellite = client.satellite
        self.state = client.state
        self.timers: dict[str, _Timer] = {}
        self.media_session_id = ""
        self.media_group_id = ""
        self.media_started_at = 0.0
        self.ota_task: Optional[asyncio.Task[None]] = None
        self.settings = self._load_settings()
        self.capabilities: dict[str, Any] = {
            "live_settings": True,
            "setup_mode": True,
            "timers": True,
            "ota": True,
            "persistent_media_sessions": True,
            "media_session_volume": True,
            "audio_ducking": True,
            "tts_overlays": True,
            "audio_scenes": False,
            "looping_background_audio": False,
            "synchronized_media_sessions": False,
            "stereo_channel_selection": False,
            "media_playhead_telemetry": False,
            "media_drift_correction": False,
            "synchronized_tts_overlays": False,
            "audio_session_version": 1,
            "audio_scene_version": 0,
            "media_sample_rate_hz": 48000,
        }

    def _send(self, message_type: str, payload: Optional[dict[str, Any]] = None) -> None:
        self.client._submit_frame(_frame(message_type, payload))  # pylint: disable=protected-access

    def _load_settings(self) -> dict[str, Any]:
        try:
            value = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _save_settings(self) -> None:
        try:
            _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary = _SETTINGS_PATH.with_name(f".{_SETTINGS_PATH.name}.{os.getpid()}.tmp")
            temporary.write_text(json.dumps(self.settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, _SETTINGS_PATH)
        except OSError:
            _LOGGER.exception("Unable to persist Tater live settings")

    def connected(self) -> None:
        self._apply_settings(self.settings, persist=False)

    def disconnected(self) -> None:
        # Timers intentionally remain local and keep counting during a server
        # reconnect. Media is stopped because its remote session is gone.
        if self.media_session_id:
            self.state.music_player.stop()
            self.media_session_id = ""
            self.media_group_id = ""

    def status(self) -> dict[str, Any]:
        self._reconcile_ringing_timers()
        disk_free = 0
        try:
            disk_free = shutil.disk_usage("/data").free
        except OSError:
            pass
        return {
            "timer_count": len(self.timers),
            "timer_ringing": any(timer.ringing for timer in self.timers.values()),
            "media_session_id": self.media_session_id,
            "ota_active": self.ota_task is not None and not self.ota_task.done(),
            "data_free_bytes": disk_free,
        }

    def handle_message(self, body: dict[str, Any]) -> bool:
        message_type = str(body.get("type") or "").strip()
        message_id = str(body.get("id") or "").strip()
        raw_payload = body.get("payload")
        payload = raw_payload if isinstance(raw_payload, dict) else {}

        if message_type in {"timer.start", "timer.arm"}:
            self._start_timer(payload, message_id, replace=message_type == "timer.arm")
            return True
        if message_type in {"timer.list", "timer.status"}:
            self._timer_result(message_id, "list", timers=[timer.public() for timer in self.timers.values()], count=len(self.timers))
            return True
        if message_type in {"timer.cancel", "timer.clear"}:
            self._cancel_timers(payload, message_id, clear_all=message_type == "timer.clear")
            return True
        if message_type == "timer.snooze":
            self._snooze_timers(payload, message_id)
            return True
        if message_type == "timer.alarm":
            for timer in self._select_timers(payload):
                self._ring_timer(timer)
            return True
        if message_type == "settings":
            self._apply_settings(payload, persist=True)
            return True
        if message_type == "play.url" and "continue_conversation" not in payload:
            # A per-response value from Tater always wins. Otherwise apply the
            # persisted device preference so the live setting has real runtime
            # behavior instead of being metadata-only.
            payload["continue_conversation"] = _truthy(self.settings.get("continued_chat"))
            return False
        if message_type == "audio.clock.sync":
            receive_us = time.monotonic_ns() // 1000
            self._send(
                "audio.clock.sync.result",
                {
                    "reply_to": message_id,
                    "ok": True,
                    "server_send_us": _integer(payload.get("server_send_us"), maximum=2**63 - 1),
                    "satellite_receive_us": receive_us,
                    "satellite_send_us": time.monotonic_ns() // 1000,
                },
            )
            return True
        if message_type == "media.session.start":
            self._start_media(payload, message_id)
            return True
        if message_type == "media.session.prepare":
            self._send(
                "media.session.prepare.result",
                {"reply_to": message_id, "ok": False, "error": "synchronized playback is not supported on this satellite"},
            )
            return True
        if message_type == "media.session.commit":
            self._send("media.session.commit.result", {"reply_to": message_id, "ok": False, "error": "no prepared session"})
            return True
        if message_type == "media.session.volume":
            self._set_media_volume(payload, message_id)
            return True
        if message_type == "media.session.stop":
            self._stop_media(ok=True)
            return True
        if message_type == "audio.overlay.start":
            self._start_overlay(payload)
            return True
        if message_type in {"setup.reset", "provisioning.reset"}:
            asyncio.create_task(self._reset_setup())
            return True
        if message_type == "ota.url":
            if self.ota_task is None or self.ota_task.done():
                self.ota_task = asyncio.create_task(self._run_ota(payload))
            else:
                self._send("ota.status", {"status": "error", "progress": 0, "message": "An update is already running."})
            return True
        return False

    def _timer_result(self, reply_to: str, action: str, *, ok: bool = True, **extra: Any) -> None:
        self._send("timer.result", {"reply_to": reply_to, "action": action, "ok": ok, **extra})

    def _start_timer(self, payload: dict[str, Any], reply_to: str, *, replace: bool) -> None:
        duration_ms = _integer(
            payload.get("remaining_ms") or payload.get("duration_ms") or (_integer(payload.get("duration_s")) * 1000),
            maximum=_MAX_TIMER_SECONDS * 1000,
        )
        original_ms = _integer(payload.get("original_duration_ms") or duration_ms, maximum=_MAX_TIMER_SECONDS * 1000)
        timer_id = str(payload.get("id") or uuid.uuid4().hex[:12]).strip()[:47]
        name = str(payload.get("name") or payload.get("label") or "").strip()[:63]
        if duration_ms <= 0:
            self._timer_result(reply_to, "start", ok=False, code="invalid_duration", message="Timer duration must be greater than zero.")
            return
        existing = self.timers.get(timer_id)
        if existing is not None and not replace:
            self._timer_result(reply_to, "start", timer=existing.public(), code="already_exists")
            return
        if existing is None and len(self.timers) >= _MAX_TIMERS:
            self._timer_result(reply_to, "start", ok=False, code="timer_limit", message="This satellite already has the maximum number of timers.")
            return
        if existing is not None and existing.task is not None:
            existing.task.cancel()
        timer = _Timer(timer_id, name, original_ms, time.monotonic() + (duration_ms / 1000.0))
        timer.task = asyncio.create_task(self._timer_wait(timer))
        self.timers[timer_id] = timer
        self._timer_result(reply_to, "start", timer=timer.public())
        self._emit_timer_event("updated" if replace and existing is not None else "armed", timer)

    async def _timer_wait(self, timer: _Timer) -> None:
        try:
            await asyncio.sleep(max(0.0, timer.deadline - time.monotonic()))
        except asyncio.CancelledError:
            return
        if self.timers.get(timer.timer_id) is timer:
            self._ring_timer(timer)

    def _ring_timer(self, timer: _Timer) -> None:
        if timer.ringing:
            return
        timer.ringing = True
        timer.deadline = time.monotonic()
        self.satellite._timer_finished = True  # pylint: disable=protected-access
        self.satellite._timer_ring_start = time.monotonic()  # pylint: disable=protected-access
        self.state.active_wake_words.add(self.state.stop_word.id)
        self.satellite.duck()
        self.satellite._emit(LVAEvent.TIMER_RINGING, timer.public())  # pylint: disable=protected-access
        self.satellite._play_timer_finished()  # pylint: disable=protected-access
        self._emit_timer_event("expired", timer)

    def _select_timers(self, payload: dict[str, Any], *, clear_all: bool = False) -> list[_Timer]:
        timers = list(self.timers.values())
        if clear_all:
            return timers
        ids = {str(value) for value in payload.get("ids", []) if str(value).strip()} if isinstance(payload.get("ids"), list) else set()
        timer_id = str(payload.get("id") or payload.get("timer_id") or "").strip()
        name = str(payload.get("name") or payload.get("label") or "").strip().lower()
        if ids:
            return [timer for timer in timers if timer.timer_id in ids]
        if timer_id:
            return [timer for timer in timers if timer.timer_id == timer_id]
        if name:
            return [timer for timer in timers if timer.name.lower() == name]
        ringing = [timer for timer in timers if timer.ringing]
        return ringing if ringing else (timers if len(timers) == 1 else [])

    def _cancel_timers(self, payload: dict[str, Any], reply_to: str, *, clear_all: bool) -> None:
        selected = self._select_timers(payload, clear_all=clear_all)
        rows = [timer.public() for timer in selected]
        for timer in selected:
            if timer.task is not None:
                timer.task.cancel()
            self.timers.pop(timer.timer_id, None)
            self._emit_timer_event("cleared" if clear_all else "cancelled", timer, active=False)
        self._stop_ringing_if_idle()
        code = "" if selected else "not_found"
        self._timer_result(reply_to, "cancel", timers=rows, affected=len(rows), code=code)

    def _snooze_timers(self, payload: dict[str, Any], reply_to: str) -> None:
        duration_ms = _integer(payload.get("duration_ms") or (_integer(payload.get("duration_s"), 300) * 1000), 300000, maximum=_MAX_TIMER_SECONDS * 1000)
        selected = self._select_timers(payload)
        for timer in selected:
            if timer.task is not None:
                timer.task.cancel()
            timer.ringing = False
            timer.original_duration_ms = duration_ms
            timer.deadline = time.monotonic() + duration_ms / 1000.0
            timer.task = asyncio.create_task(self._timer_wait(timer))
            self._emit_timer_event("snoozed", timer)
        self._stop_ringing_if_idle()
        self._timer_result(reply_to, "snooze", timers=[timer.public() for timer in selected], affected=len(selected), code="" if selected else "not_found")

    def _emit_timer_event(self, event: str, timer: _Timer, *, active: bool = True) -> None:
        row = timer.public()
        row.update({"event": event, "active": active, "state": row["state"] if active else "stopped"})
        self._send("timer.event", row)

    def _reconcile_ringing_timers(self) -> None:
        if any(timer.ringing for timer in self.timers.values()) and not bool(getattr(self.satellite, "_timer_finished", False)):
            for timer in list(self.timers.values()):
                if timer.ringing:
                    self.timers.pop(timer.timer_id, None)
                    self._emit_timer_event("stopped", timer, active=False)

    def _stop_ringing_if_idle(self) -> None:
        if any(timer.ringing for timer in self.timers.values()):
            return
        if bool(getattr(self.satellite, "_timer_finished", False)):
            self.satellite._timer_finished = False  # pylint: disable=protected-access
            self.satellite._timer_ring_start = None  # pylint: disable=protected-access
            self.state.active_wake_words.discard(self.state.stop_word.id)
            self.state.tts_player.stop()
            self.satellite.unduck()
            self.satellite._emit(LVAEvent.IDLE)  # pylint: disable=protected-access

    def _apply_settings(self, payload: dict[str, Any], *, persist: bool) -> None:
        applied: dict[str, Any] = {}
        if "volume_percent" in payload:
            volume = _integer(payload.get("volume_percent"), 80, maximum=100)
            self.state.music_player.set_volume(volume)
            self.state.tts_player.set_volume(volume)
            self.state.persist_volume(volume / 100.0)
            applied["volume_percent"] = volume
        if "muted" in payload:
            muted = _truthy(payload.get("muted"))
            self.satellite._set_muted(muted)  # pylint: disable=protected-access
            applied["muted"] = muted
        if "wake_threshold" in payload:
            try:
                threshold = float(payload.get("wake_threshold"))
            except (TypeError, ValueError):
                threshold = None
            if threshold is not None:
                threshold = max(0.01, min(0.99, threshold))
                self.state.wake_word_1_threshold = threshold
                self.state.preferences.wake_word_1_sensitivity = threshold
                self.state.save_preferences()
                applied["wake_threshold"] = threshold
        if "wake_word" in payload:
            wake_word = str(payload.get("wake_word") or "").strip()
            if wake_word in self.state.available_wake_words:
                self.state.preferences.active_wake_words = [wake_word]
                self.state.active_wake_words = {wake_word}
                self.state.wake_words_changed = True
                self.state.save_preferences()
                applied["wake_word"] = wake_word
        if "wake_engine" in payload:
            engine = str(payload.get("wake_engine") or "micro_wake_word").strip()
            if engine in {"off", "button", "micro_wake_word"}:
                if engine in {"off", "button"}:
                    self.state.active_wake_words.clear()
                elif self.state.preferences.active_wake_words:
                    self.state.active_wake_words = {word for word in self.state.preferences.active_wake_words if word}
                self.state.wake_words_changed = True
                applied["wake_engine"] = engine
        if "continued_chat" in payload:
            applied["continued_chat"] = _truthy(payload.get("continued_chat"))
        if "logging_level" in payload:
            level_name = str(payload.get("logging_level") or "info").strip().upper()
            level = getattr(logging, level_name, logging.INFO)
            logging.getLogger().setLevel(level)
            applied["logging_level"] = level_name.lower()
        if applied:
            self.settings.update(applied)
            if persist:
                self._save_settings()

    def _start_media(self, payload: dict[str, Any], reply_to: str) -> None:
        media = payload.get("media") if isinstance(payload.get("media"), dict) else payload
        url = str(media.get("url") or "").strip()
        if not url:
            self._send("media.session.start.result", {"reply_to": reply_to, "ok": False, "error": "media url is required"})
            return
        self.media_session_id = str(payload.get("session_id") or reply_to or uuid.uuid4().hex).strip()
        self.media_group_id = str(payload.get("group_id") or "").strip()
        volume = _integer(media.get("volume_percent"), int(round(self.state.volume * 100)), maximum=100)
        self.state.music_player.set_volume(volume)
        self.media_started_at = time.monotonic()
        session_id = self.media_session_id
        group_id = self.media_group_id
        self.state.music_player.play(url, done_callback=lambda: self._media_finished(session_id, group_id, True), stop_first=True)
        event = {
            "session_id": session_id,
            "group_id": group_id,
            "channel": "stereo",
            "sample_rate_hz": 48000,
            "actual_start_us": time.monotonic_ns() // 1000,
            "late_by_us": 0,
        }
        self._send("media.session.start.result", {"reply_to": reply_to, "ok": True, **event})
        self._send("media.session.started", event)

    def _media_finished(self, session_id: str, group_id: str, ok: bool) -> None:
        if self.media_session_id != session_id:
            return
        self.media_session_id = ""
        self.media_group_id = ""
        self._send("media.session.finished", {"session_id": session_id, "group_id": group_id, "ok": ok})

    def _stop_media(self, *, ok: bool) -> None:
        session_id = self.media_session_id
        group_id = self.media_group_id
        if not session_id:
            return
        self.state.music_player.stop()
        self._media_finished(session_id, group_id, ok)

    def _set_media_volume(self, payload: dict[str, Any], reply_to: str) -> None:
        session_id = str(payload.get("session_id") or "").strip()
        ok = bool(self.media_session_id and (not session_id or session_id == self.media_session_id))
        if ok:
            self.state.music_player.set_volume(_integer(payload.get("volume_percent"), 100, maximum=100))
        self._send("media.session.volume.result", {"reply_to": reply_to, "ok": ok, "error": "" if ok else "session not found"})

    def _start_overlay(self, payload: dict[str, Any]) -> None:
        foreground = payload.get("foreground") if isinstance(payload.get("foreground"), dict) else payload
        ducking = payload.get("ducking") if isinstance(payload.get("ducking"), dict) else {}
        overlay_id = str(payload.get("overlay_id") or uuid.uuid4().hex).strip()
        url = str(foreground.get("url") or "").strip()
        if not url:
            self._send("audio.overlay.finished", {"overlay_id": overlay_id, "ok": False})
            return
        factor = _integer(ducking.get("target_percent"), 20, maximum=100) / 100.0
        self.state.music_player.duck(factor)
        self.state.tts_player.set_volume(_integer(foreground.get("volume_percent"), 100, maximum=100))
        self._send("audio.overlay.started", {"overlay_id": overlay_id})

        def finished() -> None:
            self.state.music_player.unduck()
            self._send("audio.overlay.finished", {"overlay_id": overlay_id, "ok": True})

        self.state.tts_player.play(url, done_callback=finished, stop_first=True)

    async def _reset_setup(self) -> None:
        self._send("log", {"level": "warn", "message": "Setup reset requested by Tater; rebooting into setup mode."})
        await asyncio.sleep(0.25)
        process = await asyncio.create_subprocess_exec("/usr/bin/tater-provisioning", "reset")
        await process.wait()

    async def _run_ota(self, payload: dict[str, Any]) -> None:
        url = str(payload.get("url") or "").strip()
        if not url:
            self._send("ota.status", {"status": "error", "progress": 0, "message": "Update URL is missing."})
            return
        try:
            self._send("ota.status", {"status": "downloading", "progress": 0, "message": "Downloading signed Tater firmware."})
            digest = await asyncio.to_thread(self._download_ota, url)
            self._send("ota.status", {"status": "installing", "progress": 100, "message": f"Installing signed firmware ({digest[:12]})."})
            process = await asyncio.create_subprocess_exec(
                "/usr/bin/swupdate",
                "-G",
                "-k",
                str(_SWUPDATE_KEY),
                "-H",
                "S420:1.0",
                "-i",
                str(_OTA_PATH),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output, _ = await process.communicate()
            if process.returncode != 0:
                message = output.decode("utf-8", errors="replace").strip()[-300:]
                raise RuntimeError(message or f"swupdate exited with {process.returncode}")
            self._send("ota.status", {"status": "complete", "progress": 100, "message": "Firmware installed; rebooting."})
            await asyncio.sleep(1.0)
            subprocess.Popen(["/sbin/reboot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.exception("Tater OTA failed")
            self._send("ota.status", {"status": "error", "progress": 0, "message": str(exc) or type(exc).__name__})

    def _download_ota(self, url: str) -> str:
        _OTA_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = _OTA_PATH.with_suffix(".swu.part")
        digest = hashlib.sha256()
        request = Request(url, headers={"User-Agent": "Tater-S420/0.1.1"})
        with urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, _OTA_PATH)
        return digest.hexdigest()

    async def close(self) -> None:
        for timer in self.timers.values():
            if timer.task is not None:
                timer.task.cancel()
        if self.ota_task is not None and not self.ota_task.done():
            self.ota_task.cancel()
