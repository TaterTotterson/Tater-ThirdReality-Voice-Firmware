"""Tater-native controls layered onto the reusable Linux audio state machine."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from .peripheral_api import LVAEvent

_LOGGER = logging.getLogger(__name__)
_PROTOCOL_VERSION = 1
_MAX_TIMERS = 8
_MAX_TIMER_SECONDS = 7 * 24 * 60 * 60
_SETTINGS_PATH = Path("/data/conf/tater-live-settings.json")
_OTA_PATH = Path("/data/software.swu")
_SWUPDATE_KEY = Path("/etc/swupdate-public.pem")
_OTA_MAX_BYTES = 192 * 1024 * 1024
_WAKE_MANIFEST_MAX_BYTES = 128 * 1024
_WAKE_MODEL_MAX_BYTES = 2 * 1024 * 1024
_WAKE_SOUND_MAX_BYTES = 2 * 1024 * 1024
_WAKE_DOWNLOAD_TIMEOUT_SECONDS = 30
_WAKE_URL_SCHEMES = {"http", "https"}
_WAKE_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_TATER_WAKE_SOUND_DIR = Path(__file__).resolve().parents[1] / "sounds"
_WAKE_SOUND_FILES = {
    "blip2": "blip2.wav",
    "message-notification-4": "message-notification-4.wav",
    "notification-ding": "notification-ding.wav",
    "notification-squeak": "notification-squeak.wav",
    "phone-chime": "phone-chime.wav",
    "pop-up-sound": "pop-up-sound.wav",
    "short-definite-fart": "short-definite-fart.wav",
    "star_treck_communications_start_transmission": "star_treck_communications_start_transmission.wav",
    "star_treck_computer_work_beep": "star_treck_computer_work_beep.wav",
    "tater_notify_digital_blip": "tater_notify_digital_blip.wav",
    "turning-off-microphone-percussion-1": "turning-off-microphone-percussion-1.wav",
    "wake_word_triggered": "wake_word_triggered.wav",
    "waterdrop": "waterdrop.wav",
}
_WAKE_SOUND_IDS = {"default", "no_sound", "custom", *_WAKE_SOUND_FILES}
_MEDIA_SAMPLE_RATE_HZ = 48000
_MEDIA_PREPARE_TIMEOUT_SECONDS = 60.0
_MEDIA_COMMIT_TIMEOUT_SECONDS = 30.0
_MEDIA_PLAYHEAD_INTERVAL_SECONDS = 1.0
_MEDIA_DEFAULT_OUTPUT_LATENCY_FRAMES = 6144
_MEDIA_MAX_OUTPUT_LATENCY_FRAMES = 24000
_MEDIA_LATENCY_EMA_ALPHA = 0.25
_MEDIA_LATENCY_LEARN_SAMPLES = 3
_MEDIA_RECOVERY_THRESHOLD_FRAMES = 2400
_MEDIA_RECOVERY_SEEK_TIMEOUT_SECONDS = 1.5
_MEDIA_RECOVERY_FADE_SECONDS = 0.12
_AUDIO_PREPARE_TIMEOUT_SECONDS = 10.0
_AUDIO_RAMP_STEP_SECONDS = 0.02
_MEDIA_CHANNELS = {"stereo", "left", "right", "mono"}
_LED_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_LED_ANIMATIONS = {"pulse", "breathe", "heartbeat", "solid"}
_LED_SETTING_KEYS = (
    "led_brightness",
    "led_color",
    "led_listening_animation",
    "led_thinking_animation",
    "led_tool_call_animation",
    "led_replying_animation",
)


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


def _signed_integer(value: Any, default: int = 0, *, limit: int = 2**31 - 1) -> int:
    try:
        result = int(round(float(value)))
    except (TypeError, ValueError):
        result = default
    return max(-abs(limit), min(abs(limit), result))


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


def _validated_web_url(value: Any, *, label: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _WAKE_URL_SCHEMES or not parsed.netloc:
        raise ValueError(f"{label} must use HTTP or HTTPS")
    return url


def _download_limited(url: str, maximum: int) -> bytes:
    request = Request(url, headers={"User-Agent": "Tater-S420/0.2"})
    with urlopen(request, timeout=_WAKE_DOWNLOAD_TIMEOUT_SECONDS) as response:
        final_url = _validated_web_url(response.geturl(), label="redirected wake-word URL")
        if final_url != response.geturl():
            raise ValueError("invalid redirected wake-word URL")
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > maximum:
                    raise ValueError(f"wake-word download exceeds {maximum} bytes")
            except ValueError as exc:
                if "exceeds" in str(exc):
                    raise
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError(f"wake-word download exceeds {maximum} bytes")
    if not data:
        raise ValueError("wake-word download was empty")
    return data


def _custom_wake_id(manifest_url: str) -> str:
    return f"tater_custom_{hashlib.sha256(manifest_url.encode('utf-8')).hexdigest()[:16]}"


def _parse_wake_manifest(manifest_url: str, raw: bytes) -> tuple[dict[str, Any], str, str]:
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("wake-word manifest is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("wake-word manifest must be a JSON object")
    if str(manifest.get("type") or "").strip().lower() != "micro":
        raise ValueError("S420 custom wake words must use the microWakeWord format")
    wake_word = str(manifest.get("wake_word") or "").strip()
    if not wake_word or len(wake_word) > 80:
        raise ValueError("wake-word manifest has an invalid wake_word")
    model_ref = str(manifest.get("model") or manifest.get("model_url") or "").strip()
    if not model_ref:
        raise ValueError("wake-word manifest is missing its TFLite model")
    model_url = _validated_web_url(urljoin(manifest_url, model_ref), label="wake-word model URL")
    micro = manifest.get("micro")
    if not isinstance(micro, dict):
        raise ValueError("wake-word manifest is missing its microWakeWord settings")
    return manifest, wake_word, model_url


def _expected_model_sha256(manifest: dict[str, Any]) -> str:
    for key in ("model_sha256", "model_hash", "sha256"):
        value = str(manifest.get(key) or "").strip()
        if value:
            if not _WAKE_SHA256.fullmatch(value):
                raise ValueError(f"wake-word manifest has an invalid {key}")
            return value.lower()
    return ""


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _download_custom_wake_package(state: Any, manifest_url: str) -> tuple[str, Any, Any]:
    from .models import AvailableWakeWord, WakeWordType

    manifest_url = _validated_web_url(manifest_url, label="wake-word manifest URL")
    manifest_raw = _download_limited(manifest_url, _WAKE_MANIFEST_MAX_BYTES)
    manifest, wake_phrase, model_url = _parse_wake_manifest(manifest_url, manifest_raw)
    model_data = _download_limited(model_url, _WAKE_MODEL_MAX_BYTES)
    model_digest = hashlib.sha256(model_data).hexdigest()
    expected_digest = _expected_model_sha256(manifest)
    if expected_digest and model_digest != expected_digest:
        raise ValueError("wake-word model SHA-256 does not match the manifest")

    model_id = _custom_wake_id(manifest_url)
    cache_dir = Path(state.download_dir) / "external_wake_words"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # pymicro-wakeword derives its runtime ID from the model filename, while
    # Linux Voice derives the available/preference ID from the JSON filename.
    # Keep both stems identical so the audio thread can activate the model.
    model_path = cache_dir / f"{model_id}.tflite"
    config_path = cache_dir / f"{model_id}.json"
    cached_manifest = dict(manifest)
    cached_manifest.update(
        {
            "type": "micro",
            "wake_word": wake_phrase,
            "model": model_path.name,
            "_tater_source_url": manifest_url,
            "_tater_model_url": model_url,
            "_tater_model_sha256": model_digest,
        }
    )
    config_data = (json.dumps(cached_manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    previous_model = model_path.read_bytes() if model_path.is_file() else None
    previous_config = config_path.read_bytes() if config_path.is_file() else None

    try:
        _write_bytes_atomic(model_path, model_data)
        _write_bytes_atomic(config_path, config_data)
        probability_cutoff = max(
            0.01,
            min(0.99, float(manifest.get("micro", {}).get("probability_cutoff", 0.7))),
        )
        available = AvailableWakeWord(
            id=model_id,
            type=WakeWordType.MICRO_WAKE_WORD,
            wake_word=wake_phrase,
            trained_languages=[str(value) for value in manifest.get("trained_languages", []) if str(value).strip()],
            wake_word_path=config_path,
            probability_cutoff=probability_cutoff,
        )
        loaded = available.load()
        if str(getattr(loaded, "id", model_id)) != model_id:
            raise ValueError("wake-word model ID does not match its cached package ID")
    except Exception:
        for path, previous in (
            (model_path, previous_model),
            (config_path, previous_config),
        ):
            if previous is not None:
                _write_bytes_atomic(path, previous)
            else:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        raise
    return model_id, available, loaded


def _wake_sound_cache_path() -> Path:
    return _SETTINGS_PATH.with_name("tater-wake-sound.wav")


def _wake_sound_cache_metadata_path() -> Path:
    return _SETTINGS_PATH.with_name("tater-wake-sound.json")


def _validate_wav(data: bytes) -> None:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("custom wake sound is not a RIFF/WAVE file")


def _cached_custom_wake_sound(url: str) -> Optional[Path]:
    sound_path = _wake_sound_cache_path()
    metadata_path = _wake_sound_cache_metadata_path()
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or str(metadata.get("url") or "") != url:
            return None
        data = sound_path.read_bytes()
        _validate_wav(data)
        expected_sha256 = str(metadata.get("sha256") or "").strip().lower()
        if not _WAKE_SHA256.fullmatch(expected_sha256):
            return None
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            return None
        return sound_path
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _download_custom_wake_sound(url: str) -> Path:
    url = _validated_web_url(url, label="wake-sound URL")
    data = _download_limited(url, _WAKE_SOUND_MAX_BYTES)
    _validate_wav(data)
    sound_path = _wake_sound_cache_path()
    metadata_path = _wake_sound_cache_metadata_path()
    sound_path.parent.mkdir(parents=True, exist_ok=True)
    _write_bytes_atomic(sound_path, data)
    metadata = {
        "url": url,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }
    _write_bytes_atomic(
        metadata_path,
        (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return sound_path


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


@dataclass
class _MediaSession:
    session_id: str
    group_id: str
    reply_to: str
    channel: str
    start_position_ms: int
    prepare_requested: bool
    source_url: str = ""
    loop: bool = False
    prepared: bool = False
    committed: bool = False
    started: bool = False
    scheduled_start_us: int = 0
    audible_start_us: int = 0
    actual_start_us: int = 0
    output_latency_frames: int = _MEDIA_DEFAULT_OUTPUT_LATENCY_FRAMES
    latency_learning_samples: int = 0
    timeline_base_frames: int = 0
    correction_frames_since_report: int = 0
    underrun_events: int = 0
    rejoin_count: int = 0
    rejoin_frames: int = 0
    recovering: bool = False
    was_rebuffering: bool = False
    prepare_task: Optional[asyncio.Task[None]] = None
    commit_timeout_task: Optional[asyncio.Task[None]] = None
    start_task: Optional[asyncio.Task[None]] = None
    playhead_task: Optional[asyncio.Task[None]] = None
    adjust_task: Optional[asyncio.Task[None]] = None
    recovery_task: Optional[asyncio.Task[None]] = None


@dataclass
class _OverlaySession:
    overlay_id: str
    url: str
    group_id: str = ""
    start_at_us: int = 0
    volume_percent: int = 100
    duck_target: float = 0.2
    attack_ms: int = 150
    release_ms: int = 350
    continue_conversation: bool = False
    generation: int = 0
    task: Optional[asyncio.Task[None]] = None
    started: bool = False
    finished: bool = False


@dataclass
class _AudioScene:
    scene_id: str
    foreground_url: str
    background_url: str = ""
    foreground_volume_percent: int = 100
    background_volume_percent: int = 60
    background_loop: bool = True
    duck_target: float = 0.2
    attack_ms: int = 150
    release_ms: int = 350
    fade_ms: int = 350
    generation: int = 0
    task: Optional[asyncio.Task[None]] = None
    started: bool = False
    finished: bool = False


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
        self.media_session: Optional[_MediaSession] = None
        self.overlay_session: Optional[_OverlaySession] = None
        self.audio_scene: Optional[_AudioScene] = None
        self._overlay_generation = 0
        self._scene_generation = 0
        self._music_duck_factor = 1.0
        self._sync_player_available = bool(
            getattr(self.state.music_player, "synchronized_controls_available", False)
            and all(
                callable(getattr(self.state.music_player, method, None))
                for method in (
                    "prepare_synchronized",
                    "synchronized_snapshot",
                    "seek_synchronized",
                    "set_synchronized_speed",
                    "reset_synchronized",
                    "resume",
                )
            )
        )
        self._sync_overlay_available = bool(
            self._sync_player_available
            and getattr(self.state.tts_player, "synchronized_controls_available", False)
            and all(
                callable(getattr(self.state.tts_player, method, None))
                for method in (
                    "prepare_synchronized",
                    "synchronized_snapshot",
                    "reset_synchronized",
                    "resume",
                )
            )
        )
        self.ota_task: Optional[asyncio.Task[None]] = None
        self.wake_model_task: Optional[asyncio.Task[None]] = None
        self.wake_model_generation = 0
        self.wake_model_downloading = False
        self.wake_sound_task: Optional[asyncio.Task[None]] = None
        self.wake_sound_generation = 0
        self.wake_sound_downloading = False
        self._default_wakeup_sound = str(getattr(self.state, "wakeup_sound", "") or "")
        self.settings = self._load_settings()
        self.satellite._tater_barge_in_enabled = _truthy(  # pylint: disable=protected-access
            self.settings.get("barge_in_enabled")
        )
        self.satellite._tater_wakeup_sound = self._default_wakeup_sound  # pylint: disable=protected-access
        self.capabilities: dict[str, Any] = {
            "live_settings": True,
            "custom_wake_words": True,
            "wake_sounds": True,
            "custom_wake_sounds": True,
            "status_led": True,
            "setup_mode": True,
            "timers": True,
            "ota": True,
            "persistent_media_sessions": True,
            "media_session_volume": True,
            "audio_ducking": True,
            "tts_overlays": True,
            "audio_scenes": self._sync_overlay_available,
            "looping_background_audio": self._sync_overlay_available,
            "barge_in": True,
            "synchronized_media_sessions": self._sync_player_available,
            "stereo_channel_selection": self._sync_player_available,
            "media_playhead_telemetry": self._sync_player_available,
            "media_drift_correction": self._sync_player_available,
            "media_rate_slew": self._sync_player_available,
            "media_render_clock": self._sync_player_available,
            "media_output_latency_frames": (
                _MEDIA_DEFAULT_OUTPUT_LATENCY_FRAMES if self._sync_player_available else 0
            ),
            "media_underrun_recovery": self._sync_player_available,
            "media_session_start_position": self._sync_player_available,
            "synchronized_tts_overlays": self._sync_overlay_available,
            "audio_session_version": 2 if self._sync_player_available else 1,
            "audio_scene_version": 1 if self._sync_overlay_available else 0,
            "media_sample_rate_hz": _MEDIA_SAMPLE_RATE_HZ,
        }

    def _send(self, message_type: str, payload: Optional[dict[str, Any]] = None) -> None:
        self.client._submit_frame(_frame(message_type, payload))  # pylint: disable=protected-access

    def _call_soon(self, callback: Any, *args: Any) -> None:
        """Run player callbacks on the asyncio loop that owns this manager."""
        loop = getattr(self.client, "_loop", None)
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(callback, *args)
            return
        try:
            asyncio.get_running_loop().call_soon(callback, *args)
        except RuntimeError:
            callback(*args)

    async def _sleep_until_us(self, deadline_us: int) -> None:
        while deadline_us > 0:
            remaining_us = deadline_us - (time.monotonic_ns() // 1000)
            if remaining_us <= 0:
                return
            if remaining_us > 20_000:
                await asyncio.sleep((remaining_us - 10_000) / 1_000_000.0)
            elif remaining_us > 1_000:
                await asyncio.sleep(0.001)
            else:
                await asyncio.sleep(0)

    async def _wait_player_ready(self, player: Any, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last_snapshot: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last_snapshot = player.synchronized_snapshot()
            if _truthy(last_snapshot.get("loaded")) and not _truthy(last_snapshot.get("seeking")):
                return last_snapshot
            await asyncio.sleep(0.02)
        raise TimeoutError("audio preparation timed out")

    def _set_music_duck(self, factor: float) -> None:
        self._music_duck_factor = max(0.0, min(1.0, float(factor)))
        if self._music_duck_factor >= 0.999:
            self.state.music_player.unduck()
        else:
            self.state.music_player.duck(self._music_duck_factor)

    async def _ramp_music_duck(self, target: float, duration_ms: int) -> None:
        target = max(0.0, min(1.0, float(target)))
        duration_seconds = max(0.0, duration_ms / 1000.0)
        start = self._music_duck_factor
        if duration_seconds <= 0.0 or abs(target - start) < 0.001:
            self._set_music_duck(target)
            return
        steps = max(1, int(round(duration_seconds / _AUDIO_RAMP_STEP_SECONDS)))
        step_delay = duration_seconds / steps
        for index in range(1, steps + 1):
            self._set_music_duck(start + ((target - start) * index / steps))
            await asyncio.sleep(step_delay)

    @staticmethod
    def _url_with_start(url: str, position_seconds: float) -> str:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["start"] = f"{max(0.0, position_seconds):.3f}"
        return urlunparse(parsed._replace(query=urlencode(query)))

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
        if self.audio_scene is not None:
            self._stop_audio_scene(ok=False, notify=False)
        if self.overlay_session is not None:
            self._stop_overlay(ok=False, notify=False)
        if self.media_session_id:
            self._stop_media(ok=False, notify=False)

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
            "wake_model_downloading": self.wake_model_downloading,
            "wake_sound_downloading": self.wake_sound_downloading,
            "wake_word": next(iter(self.state.active_wake_words), ""),
            "wake_sound": str(self.settings.get("wake_sound") or "no_sound"),
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
            self._prepare_media(payload, message_id)
            return True
        if message_type == "media.session.commit":
            self._commit_media(payload, message_id)
            return True
        if message_type == "media.session.volume":
            self._set_media_volume(payload, message_id)
            return True
        if message_type == "media.session.adjust":
            self._adjust_media(payload, message_id)
            return True
        if message_type == "media.session.stop":
            self._stop_media(ok=True)
            return True
        if message_type == "audio.overlay.start":
            self._start_overlay(payload)
            return True
        if message_type == "audio.scene.start":
            self._start_audio_scene(payload)
            return True
        if message_type == "audio.scene.stop":
            self._stop_audio_scene(ok=False)
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
        if "wake_engine" in payload:
            engine = str(payload.get("wake_engine") or "micro_wake_word").strip()
            if engine in {"off", "button", "micro_wake_word"}:
                applied["wake_engine"] = engine
        if "wake_word" in payload:
            wake_word = str(payload.get("wake_word") or "").strip()
            if wake_word and len(wake_word) <= 120:
                applied["wake_word"] = wake_word
        if "wake_word_url" in payload:
            wake_word_url = str(payload.get("wake_word_url") or "").strip()
            if len(wake_word_url) <= 2048:
                applied["wake_word_url"] = wake_word_url
        if "wake_sound_enabled" in payload:
            applied["wake_sound_enabled"] = _truthy(payload.get("wake_sound_enabled"))
        if "wake_sound" in payload:
            wake_sound = str(payload.get("wake_sound") or "").strip().lower()
            if wake_sound in _WAKE_SOUND_IDS:
                applied["wake_sound"] = wake_sound
        if "wake_sound_url" in payload:
            wake_sound_url = str(payload.get("wake_sound_url") or "").strip()
            if len(wake_sound_url) <= 2048:
                applied["wake_sound_url"] = wake_sound_url
        if "continued_chat" in payload:
            applied["continued_chat"] = _truthy(payload.get("continued_chat"))
        if "barge_in_enabled" in payload:
            applied["barge_in_enabled"] = _truthy(payload.get("barge_in_enabled"))
        if "logging_level" in payload:
            level_name = str(payload.get("logging_level") or "info").strip().upper()
            level = getattr(logging, level_name, logging.INFO)
            logging.getLogger().setLevel(level)
            applied["logging_level"] = level_name.lower()
        if "led_brightness" in payload:
            applied["led_brightness"] = _integer(payload.get("led_brightness"), 80, maximum=100)
        if "led_color" in payload:
            color = str(payload.get("led_color") or "").strip()
            if _LED_COLOR.fullmatch(color):
                applied["led_color"] = color.lower()
        for key in _LED_SETTING_KEYS[2:]:
            if key not in payload:
                continue
            animation = str(payload.get(key) or "").strip().lower()
            if animation in _LED_ANIMATIONS:
                applied[key] = animation
        if applied:
            self.settings.update(applied)
            self.satellite._tater_barge_in_enabled = _truthy(  # pylint: disable=protected-access
                self.settings.get("barge_in_enabled")
            )
            if persist:
                self._save_settings()
        if {"wake_word", "wake_word_url", "wake_engine"}.intersection(payload):
            self._apply_wake_selection()
        if not persist or {"wake_sound_enabled", "wake_sound", "wake_sound_url"}.intersection(payload):
            self._apply_wake_sound_selection()

    def _cancel_custom_wake_sound_download(self) -> None:
        self.wake_sound_generation += 1
        if self.wake_sound_task is not None and not self.wake_sound_task.done():
            self.wake_sound_task.cancel()
        self.wake_sound_task = None
        self.wake_sound_downloading = False

    def _apply_wake_sound_selection(self) -> None:
        enabled = _truthy(self.settings.get("wake_sound_enabled"))
        sound_id = str(self.settings.get("wake_sound") or "no_sound").strip().lower()
        if sound_id not in _WAKE_SOUND_IDS:
            sound_id = "no_sound"

        if (not enabled) or sound_id == "no_sound":
            self._cancel_custom_wake_sound_download()
            self.satellite._tater_wakeup_sound = ""  # pylint: disable=protected-access
            return

        if sound_id == "default":
            self._cancel_custom_wake_sound_download()
            self.satellite._tater_wakeup_sound = self._default_wakeup_sound  # pylint: disable=protected-access
            return

        if sound_id in _WAKE_SOUND_FILES:
            self._cancel_custom_wake_sound_download()
            sound_path = _TATER_WAKE_SOUND_DIR / _WAKE_SOUND_FILES[sound_id]
            if sound_path.is_file():
                self.satellite._tater_wakeup_sound = str(sound_path)  # pylint: disable=protected-access
            else:
                self.satellite._tater_wakeup_sound = ""  # pylint: disable=protected-access
                self._send(
                    "log",
                    {
                        "level": "error",
                        "message": f"Tater wake sound '{sound_id}' is missing from this firmware image.",
                    },
                )
            return

        custom_url = str(self.settings.get("wake_sound_url") or "").strip()
        if not custom_url:
            self._cancel_custom_wake_sound_download()
            self.satellite._tater_wakeup_sound = ""  # pylint: disable=protected-access
            self._send("log", {"level": "error", "message": "Custom wake sound selected without a WAV URL."})
            return

        try:
            cached_path = _cached_custom_wake_sound(custom_url)
        except Exception:  # pylint: disable=broad-except
            cached_path = None
        if cached_path is not None:
            self._cancel_custom_wake_sound_download()
            self.satellite._tater_wakeup_sound = str(cached_path)  # pylint: disable=protected-access
            return

        self._cancel_custom_wake_sound_download()
        generation = self.wake_sound_generation
        self.wake_sound_downloading = True
        self.satellite._tater_wakeup_sound = ""  # pylint: disable=protected-access
        self.wake_sound_task = asyncio.create_task(
            self._activate_custom_wake_sound(custom_url, generation)
        )

    async def _activate_custom_wake_sound(self, custom_url: str, generation: int) -> None:
        self._send("log", {"level": "info", "message": "Downloading the Tater custom wake sound."})
        try:
            sound_path = await asyncio.to_thread(_download_custom_wake_sound, custom_url)
            if generation != self.wake_sound_generation:
                return
            if not _truthy(self.settings.get("wake_sound_enabled")):
                return
            if str(self.settings.get("wake_sound") or "") != "custom":
                return
            if str(self.settings.get("wake_sound_url") or "").strip() != custom_url:
                return
            self.satellite._tater_wakeup_sound = str(sound_path)  # pylint: disable=protected-access
            self._send("log", {"level": "info", "message": "The Tater custom wake sound is ready."})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.exception("Unable to install custom wake sound")
            self._send("log", {"level": "error", "message": f"Custom wake-sound download failed: {exc}"})
        finally:
            if generation == self.wake_sound_generation:
                self.wake_sound_downloading = False

    def _activate_wake_word(
        self,
        model_id: str,
        *,
        available: Any = None,
        loaded: Any = None,
    ) -> bool:
        if available is not None:
            self.state.available_wake_words[model_id] = available
        available = self.state.available_wake_words.get(model_id)
        if available is None:
            return False

        wake_words = getattr(self.state, "wake_words", None)
        if wake_words is None:
            wake_words = {}
            self.state.wake_words = wake_words
        if loaded is None:
            loaded = wake_words.get(model_id)
        if loaded is None:
            loaded = available.load()
        wake_words[model_id] = loaded

        self.state.preferences.active_wake_words = [model_id]
        engine = str(self.settings.get("wake_engine") or "micro_wake_word")
        self.state.active_wake_words = {model_id} if engine == "micro_wake_word" else set()
        self.state.wake_words_changed = True
        self.state.save_preferences()
        return True

    def _apply_wake_selection(self) -> None:
        engine = str(self.settings.get("wake_engine") or "micro_wake_word")
        wake_word = str(self.settings.get("wake_word") or "hey_tater").strip()
        wake_word_url = str(self.settings.get("wake_word_url") or "").strip()

        if engine in {"off", "button"}:
            self.state.active_wake_words.clear()
            self.state.wake_words_changed = True
            return
        if engine != "micro_wake_word":
            return
        if wake_word == "custom_url":
            if wake_word_url:
                self._schedule_custom_wake_word(wake_word_url)
            else:
                self._send("log", {"level": "error", "message": "Custom wake word selected without a model URL."})
            return

        self._cancel_custom_wake_download()
        try:
            if not self._activate_wake_word(wake_word):
                self._send("log", {"level": "error", "message": f"Wake word '{wake_word}' is not installed on this satellite."})
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.exception("Unable to activate wake word %s", wake_word)
            self._send("log", {"level": "error", "message": f"Could not activate wake word '{wake_word}': {exc}"})

    def _cancel_custom_wake_download(self) -> None:
        self.wake_model_generation += 1
        if self.wake_model_task is not None and not self.wake_model_task.done():
            self.wake_model_task.cancel()
        self.wake_model_task = None
        self.wake_model_downloading = False

    def _schedule_custom_wake_word(self, manifest_url: str) -> None:
        self._cancel_custom_wake_download()
        generation = self.wake_model_generation
        self.wake_model_downloading = True
        self.wake_model_task = asyncio.create_task(self._activate_custom_wake_word(manifest_url, generation))

    async def _activate_custom_wake_word(self, manifest_url: str, generation: int) -> None:
        self._send("log", {"level": "info", "message": "Downloading the Tater custom wake word."})
        try:
            model_id, available, loaded = await asyncio.to_thread(
                _download_custom_wake_package,
                self.state,
                manifest_url,
            )
            if generation != self.wake_model_generation:
                return
            if str(self.settings.get("wake_word") or "") != "custom_url":
                return
            if str(self.settings.get("wake_word_url") or "").strip() != manifest_url:
                return
            if self._activate_wake_word(model_id, available=available, loaded=loaded):
                phrase = str(getattr(available, "wake_word", "custom wake word") or "custom wake word")
                self._send("log", {"level": "info", "message": f"Tater wake word '{phrase}' is ready."})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.exception("Unable to install custom wake word")
            self._send("log", {"level": "error", "message": f"Custom wake-word download failed: {exc}"})
        finally:
            if generation == self.wake_model_generation:
                self.wake_model_downloading = False

    def _start_media(self, payload: dict[str, Any], reply_to: str) -> None:
        self._queue_media(payload, reply_to, prepare=False)

    def _prepare_media(self, payload: dict[str, Any], reply_to: str) -> None:
        self._queue_media(payload, reply_to, prepare=True)

    def _queue_media(self, payload: dict[str, Any], reply_to: str, *, prepare: bool) -> None:
        media = payload.get("media") if isinstance(payload.get("media"), dict) else payload
        url = str(media.get("url") or "").strip()
        result_type = "media.session.prepare.result" if prepare else "media.session.start.result"
        if not url:
            self._send(result_type, {"reply_to": reply_to, "ok": False, "error": "media url is required"})
            return
        if not self._sync_player_available:
            if prepare:
                self._send(
                    result_type,
                    {"reply_to": reply_to, "ok": False, "error": "synchronized playback controls are unavailable"},
                )
                return
            self._start_legacy_media(payload, reply_to, url)
            return

        if self.audio_scene is not None:
            self._stop_audio_scene(ok=False)
        if self.overlay_session is not None:
            self._stop_overlay(ok=False)
        self._set_music_duck(1.0)
        if self.media_session is not None:
            self._stop_media(ok=False)
        session_id = str(payload.get("session_id") or reply_to or uuid.uuid4().hex).strip()
        group_id = str(payload.get("group_id") or "").strip()
        routing = payload.get("routing") if isinstance(payload.get("routing"), dict) else payload
        channel = str(routing.get("channel") or "stereo").strip().lower()
        if channel not in _MEDIA_CHANNELS:
            channel = "stereo"
        volume = _integer(media.get("volume_percent"), int(round(self.state.volume * 100)), maximum=100)
        self.state.music_player.set_volume(volume)
        session = _MediaSession(
            session_id=session_id,
            group_id=group_id,
            reply_to=reply_to,
            channel=channel,
            start_position_ms=_integer(media.get("start_position_ms"), maximum=7 * 24 * 60 * 60 * 1000),
            prepare_requested=prepare,
            source_url=url,
            loop=_truthy(media.get("loop")),
        )
        self.media_session = session
        self.media_session_id = session_id
        self.media_group_id = group_id
        try:
            self.state.music_player.prepare_synchronized(
                url,
                channel=channel,
                loop=session.loop,
                done_callback=lambda: self._media_player_finished(session_id),
            )
            session.prepare_task = asyncio.create_task(self._await_media_ready(session))
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.exception("Unable to prepare synchronized media")
            self._send(result_type, {"reply_to": reply_to, "ok": False, "error": str(exc) or type(exc).__name__})
            self._stop_media(ok=False)

    def _start_legacy_media(self, payload: dict[str, Any], reply_to: str, url: str) -> None:
        media = payload.get("media") if isinstance(payload.get("media"), dict) else payload
        self.media_session_id = str(payload.get("session_id") or reply_to or uuid.uuid4().hex).strip()
        self.media_group_id = str(payload.get("group_id") or "").strip()
        volume = _integer(media.get("volume_percent"), int(round(self.state.volume * 100)), maximum=100)
        self.state.music_player.set_volume(volume)
        self.media_started_at = time.monotonic()
        session_id = self.media_session_id
        group_id = self.media_group_id
        self.state.music_player.play(
            url,
            done_callback=lambda: self._media_finished(session_id, group_id, True),
            stop_first=False,
        )
        actual_start_us = time.monotonic_ns() // 1000
        event = {
            "session_id": session_id,
            "group_id": group_id,
            "channel": "stereo",
            "sample_rate_hz": _MEDIA_SAMPLE_RATE_HZ,
            "scheduled_start_us": actual_start_us,
            "actual_start_us": actual_start_us,
            "late_by_us": 0,
        }
        self._send("media.session.start.result", {"reply_to": reply_to, "ok": True, **event})
        self._send("media.session.started", event)

    async def _await_media_ready(self, session: _MediaSession) -> None:
        deadline = time.monotonic() + _MEDIA_PREPARE_TIMEOUT_SECONDS
        seek_applied = session.start_position_ms <= 0
        try:
            while self.media_session is session and time.monotonic() < deadline:
                snapshot = self.state.music_player.synchronized_snapshot()
                if not _truthy(snapshot.get("loaded")):
                    await asyncio.sleep(0.02)
                    continue
                if not seek_applied:
                    self.state.music_player.seek_synchronized(session.start_position_ms / 1000.0)
                    seek_applied = True
                    await asyncio.sleep(0.02)
                    continue
                if _truthy(snapshot.get("seeking")):
                    await asyncio.sleep(0.01)
                    continue

                session.prepared = True
                buffered_frames = int(
                    max(0.0, float(snapshot.get("buffered_seconds") or 0.0))
                    * _MEDIA_SAMPLE_RATE_HZ
                )
                ready = {
                    "reply_to": session.reply_to,
                    "ok": True,
                    "session_id": session.session_id,
                    "group_id": session.group_id,
                    "channel": session.channel,
                    "buffered_frames": buffered_frames,
                    "sample_rate_hz": _MEDIA_SAMPLE_RATE_HZ,
                    "output_latency_frames": session.output_latency_frames,
                    "satellite_time_us": time.monotonic_ns() // 1000,
                }
                if session.prepare_requested:
                    self._send("media.session.prepare.result", ready)
                    session.commit_timeout_task = asyncio.create_task(self._media_commit_timeout(session))
                else:
                    self._send("media.session.start.result", ready)
                    self._schedule_media_start(session, time.monotonic_ns() // 1000)
                return
            if self.media_session is session:
                self._fail_media_prepare(session, "media preparation timed out")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.exception("Synchronized media preparation failed")
            if self.media_session is session:
                self._fail_media_prepare(session, str(exc) or type(exc).__name__)

    def _fail_media_prepare(self, session: _MediaSession, error: str) -> None:
        result_type = "media.session.prepare.result" if session.prepare_requested else "media.session.start.result"
        self._send(result_type, {"reply_to": session.reply_to, "ok": False, "error": error})
        self._stop_media(ok=False)

    async def _media_commit_timeout(self, session: _MediaSession) -> None:
        try:
            await asyncio.sleep(_MEDIA_COMMIT_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            return
        if self.media_session is session and not session.committed:
            self._stop_media(ok=False)

    def _commit_media(self, payload: dict[str, Any], reply_to: str) -> None:
        session = self.media_session
        requested_id = str(payload.get("session_id") or "").strip()
        ok = bool(
            session is not None
            and session.prepare_requested
            and session.prepared
            and not session.committed
            and (not requested_id or requested_id == session.session_id)
        )
        if not ok or session is None:
            self._send(
                "media.session.commit.result",
                {"reply_to": reply_to, "ok": False, "error": "prepared session not found"},
            )
            return
        start_at_us = _integer(payload.get("start_at_us"), maximum=2**63 - 1)
        if start_at_us <= 0:
            start_at_us = time.monotonic_ns() // 1000
        session.audible_start_us = _integer(
            payload.get("audible_start_at_us"),
            start_at_us,
            maximum=2**63 - 1,
        )
        session.output_latency_frames = _integer(
            payload.get("output_latency_frames"),
            session.output_latency_frames,
            maximum=_MEDIA_MAX_OUTPUT_LATENCY_FRAMES,
        )
        self._schedule_media_start(session, start_at_us)
        self._send(
            "media.session.commit.result",
            {
                "reply_to": reply_to,
                "ok": True,
                "session_id": session.session_id,
                "group_id": session.group_id,
                "start_at_us": start_at_us,
                "audible_start_at_us": session.audible_start_us,
                "output_latency_frames": session.output_latency_frames,
            },
        )

    def _schedule_media_start(self, session: _MediaSession, start_at_us: int) -> None:
        session.committed = True
        session.scheduled_start_us = start_at_us
        if session.audible_start_us <= 0:
            session.audible_start_us = start_at_us + int(
                round(session.output_latency_frames * 1_000_000.0 / _MEDIA_SAMPLE_RATE_HZ)
            )
        if session.commit_timeout_task is not None:
            session.commit_timeout_task.cancel()
            session.commit_timeout_task = None
        session.start_task = asyncio.create_task(self._run_media_start(session))

    async def _run_media_start(self, session: _MediaSession) -> None:
        try:
            while self.media_session is session:
                remaining = session.scheduled_start_us - (time.monotonic_ns() // 1000)
                if remaining <= 0:
                    break
                if remaining > 20_000:
                    await asyncio.sleep((remaining - 10_000) / 1_000_000.0)
                elif remaining > 1_000:
                    await asyncio.sleep(0.001)
                else:
                    await asyncio.sleep(0)
            if self.media_session is not session:
                return
            self.state.music_player.resume()
            session.actual_start_us = time.monotonic_ns() // 1000
            session.started = True
            self.media_started_at = session.actual_start_us / 1_000_000.0
            event = {
                "session_id": session.session_id,
                "group_id": session.group_id,
                "channel": session.channel,
                "sample_rate_hz": _MEDIA_SAMPLE_RATE_HZ,
                "scheduled_start_us": session.scheduled_start_us,
                "actual_start_us": session.actual_start_us,
                "late_by_us": session.actual_start_us - session.scheduled_start_us,
            }
            self._send("media.session.started", event)
            session.playhead_task = asyncio.create_task(self._report_media_playhead(session))
        except asyncio.CancelledError:
            raise
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unable to start synchronized media")
            if self.media_session is session:
                self._stop_media(ok=False)

    async def _report_media_playhead(self, session: _MediaSession) -> None:
        try:
            while self.media_session is session and session.started:
                await asyncio.sleep(_MEDIA_PLAYHEAD_INTERVAL_SECONDS)
                if self.media_session is not session:
                    return
                snapshot = self.state.music_player.synchronized_snapshot()
                now_us = time.monotonic_ns() // 1000
                raw_rebuffering = _truthy(snapshot.get("rebuffering"))
                was_rebuffering = session.was_rebuffering
                if raw_rebuffering and not session.was_rebuffering:
                    session.underrun_events += 1
                elif (
                    was_rebuffering
                    and not raw_rebuffering
                    and not session.loop
                    and (session.recovery_task is None or session.recovery_task.done())
                ):
                    session.recovery_task = asyncio.create_task(
                        self._recover_media_timeline(session)
                    )
                session.was_rebuffering = raw_rebuffering
                rebuffering = raw_rebuffering or session.recovering
                correction_frames = session.correction_frames_since_report
                session.correction_frames_since_report = 0
                source_frames = session.timeline_base_frames + int(
                    max(0.0, float(snapshot.get("timeline_position_seconds") or snapshot.get("position_seconds") or 0.0))
                    * _MEDIA_SAMPLE_RATE_HZ
                )
                rendered_frames = session.timeline_base_frames + int(
                    max(0.0, float(snapshot.get("rendered_position_seconds") or snapshot.get("position_seconds") or 0.0))
                    * _MEDIA_SAMPLE_RATE_HZ
                )
                if session.latency_learning_samples < _MEDIA_LATENCY_LEARN_SAMPLES:
                    elapsed_frames = int(
                        round(
                            max(0, now_us - session.actual_start_us)
                            * _MEDIA_SAMPLE_RATE_HZ
                            / 1_000_000.0
                        )
                    )
                    start_position_frames = int(
                        round(session.start_position_ms * _MEDIA_SAMPLE_RATE_HZ / 1000.0)
                    )
                    rendered_elapsed_frames = max(0, rendered_frames - start_position_frames)
                    observed_latency_frames = elapsed_frames - rendered_elapsed_frames
                    if 0 < observed_latency_frames <= _MEDIA_MAX_OUTPUT_LATENCY_FRAMES:
                        session.output_latency_frames = (
                            observed_latency_frames
                            if session.latency_learning_samples <= 0
                            else int(
                                round(
                                    ((1.0 - _MEDIA_LATENCY_EMA_ALPHA) * session.output_latency_frames)
                                    + (_MEDIA_LATENCY_EMA_ALPHA * observed_latency_frames)
                                )
                            )
                        )
                        session.latency_learning_samples += 1
                self._send(
                    "media.session.playhead",
                    {
                        "session_id": session.session_id,
                        "group_id": session.group_id,
                        "channel": session.channel,
                        "sample_rate_hz": _MEDIA_SAMPLE_RATE_HZ,
                        "source_frames": source_frames,
                        "rendered_frames": rendered_frames,
                        "output_frames": rendered_frames,
                        "playback_rate": max(0.995, min(1.005, float(snapshot.get("speed") or 1.0))),
                        "buffered_frames": int(max(0.0, float(snapshot.get("buffered_seconds") or 0.0)) * _MEDIA_SAMPLE_RATE_HZ),
                        "satellite_time_us": now_us,
                        "scheduled_start_us": session.scheduled_start_us,
                        "audible_start_us": session.audible_start_us,
                        "output_latency_frames": session.output_latency_frames,
                        "correction_frames": correction_frames,
                        "rebuffering": rebuffering,
                        "underrun_events": session.underrun_events,
                        "rejoin_count": session.rejoin_count,
                        "rejoin_frames": session.rejoin_frames,
                    },
                )
        except asyncio.CancelledError:
            return
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unable to report synchronized media playhead")

    async def _recover_media_timeline(self, session: _MediaSession) -> None:
        """Rejoin the shared audible timeline after an mpv cache underrun."""
        try:
            session.recovering = True
            while (
                self.media_session is session
                and (
                    (self.overlay_session is not None and not self.overlay_session.finished)
                    or (self.audio_scene is not None and not self.audio_scene.finished)
                )
            ):
                await asyncio.sleep(0.05)
            if self.media_session is not session or not session.started:
                return

            now_us = time.monotonic_ns() // 1000
            audible_start_us = session.audible_start_us or session.actual_start_us
            expected_frames = int(
                round(session.start_position_ms * _MEDIA_SAMPLE_RATE_HZ / 1000.0)
            ) + int(
                round(
                    max(0, now_us - audible_start_us)
                    * _MEDIA_SAMPLE_RATE_HZ
                    / 1_000_000.0
                )
            )
            snapshot = self.state.music_player.synchronized_snapshot()
            current_frames = session.timeline_base_frames + int(
                max(
                    0.0,
                    float(
                        snapshot.get("timeline_position_seconds")
                        or snapshot.get("position_seconds")
                        or 0.0
                    ),
                )
                * _MEDIA_SAMPLE_RATE_HZ
            )
            skipped_frames = expected_frames - current_frames
            if skipped_frames <= _MEDIA_RECOVERY_THRESHOLD_FRAMES:
                return

            prior_duck = self._music_duck_factor
            await self._ramp_music_duck(0.0, int(_MEDIA_RECOVERY_FADE_SECONDS * 1000))
            pause = getattr(self.state.music_player, "pause", None)
            if callable(pause):
                pause()

            target_seconds = expected_frames / _MEDIA_SAMPLE_RATE_HZ
            local_target_seconds = max(
                0.0,
                (expected_frames - session.timeline_base_frames) / _MEDIA_SAMPLE_RATE_HZ,
            )
            seek_ok = False
            try:
                self.state.music_player.seek_synchronized(local_target_seconds)
                deadline = time.monotonic() + _MEDIA_RECOVERY_SEEK_TIMEOUT_SECONDS
                while self.media_session is session and time.monotonic() < deadline:
                    seek_snapshot = self.state.music_player.synchronized_snapshot()
                    local_frames = int(
                        max(
                            0.0,
                            float(
                                seek_snapshot.get("timeline_position_seconds")
                                or seek_snapshot.get("position_seconds")
                                or 0.0
                            ),
                        )
                        * _MEDIA_SAMPLE_RATE_HZ
                    )
                    if (
                        not _truthy(seek_snapshot.get("seeking"))
                        and abs(local_frames - int(round(local_target_seconds * _MEDIA_SAMPLE_RATE_HZ)))
                        <= _MEDIA_RECOVERY_THRESHOLD_FRAMES
                    ):
                        seek_ok = True
                        break
                    await asyncio.sleep(0.02)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug("Exact media seek failed; reloading from Tater timeline", exc_info=True)

            if not seek_ok:
                recovery_url = self._url_with_start(session.source_url, target_seconds)
                self.state.music_player.prepare_synchronized(
                    recovery_url,
                    channel=session.channel,
                    loop=False,
                    done_callback=lambda: self._media_player_finished(session.session_id),
                )
                await self._wait_player_ready(
                    self.state.music_player,
                    _MEDIA_RECOVERY_SEEK_TIMEOUT_SECONDS,
                )
                session.timeline_base_frames = expected_frames

            if self.media_session is not session:
                return
            self.state.music_player.resume()
            await self._ramp_music_duck(prior_duck, int(_MEDIA_RECOVERY_FADE_SECONDS * 1000))
            session.rejoin_count += 1
            session.rejoin_frames += max(0, skipped_frames)
        except asyncio.CancelledError:
            raise
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unable to rejoin synchronized media after an underrun")
            if self.media_session is session:
                self._set_music_duck(1.0)
                try:
                    self.state.music_player.resume()
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception("Unable to resume media after recovery failure")
        finally:
            session.recovering = False

    def _adjust_media(self, payload: dict[str, Any], reply_to: str) -> None:
        session = self.media_session
        requested_id = str(payload.get("session_id") or "").strip()
        correction_frames = _signed_integer(payload.get("correction_frames"), limit=480)
        ok = bool(
            self._sync_player_available
            and session is not None
            and session.started
            and (not requested_id or requested_id == session.session_id)
        )
        if not ok or session is None:
            self._send("media.session.adjust.result", {"reply_to": reply_to, "ok": False, "error": "session not found"})
            return
        settle_ms = _integer(payload.get("settle_ms"), 1000, minimum=100, maximum=10000)
        if session.adjust_task is not None:
            session.adjust_task.cancel()
        speed = 1.0 + (correction_frames / (_MEDIA_SAMPLE_RATE_HZ * (settle_ms / 1000.0)))
        self.state.music_player.set_synchronized_speed(speed)
        session.correction_frames_since_report += correction_frames
        session.adjust_task = asyncio.create_task(self._finish_media_slew(session, settle_ms))
        self._send(
            "media.session.adjust.result",
            {
                "reply_to": reply_to,
                "ok": True,
                "session_id": session.session_id,
                "correction_frames": correction_frames,
                "settle_ms": settle_ms,
            },
        )

    async def _finish_media_slew(self, session: _MediaSession, settle_ms: int) -> None:
        try:
            await asyncio.sleep(settle_ms / 1000.0)
        except asyncio.CancelledError:
            return
        if self.media_session is session:
            self.state.music_player.set_synchronized_speed(1.0)

    def _media_player_finished(self, session_id: str) -> None:
        loop = getattr(self.client, "_loop", None)
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._media_finished, session_id, "", True)
            return
        self._media_finished(session_id, "", True)

    def _cancel_media_tasks(self, session: _MediaSession) -> None:
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        for task in (
            session.prepare_task,
            session.commit_timeout_task,
            session.start_task,
            session.playhead_task,
            session.adjust_task,
            session.recovery_task,
        ):
            if task is not None and task is not current and not task.done():
                task.cancel()

    def _media_finished(self, session_id: str, group_id: str, ok: bool) -> None:
        session = self.media_session
        if session is not None:
            if session.session_id != session_id:
                return
            group_id = session.group_id
            self._cancel_media_tasks(session)
            self.media_session = None
            try:
                self.state.music_player.reset_synchronized()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unable to reset synchronized player")
        elif self.media_session_id != session_id:
            return
        self.media_session_id = ""
        self.media_group_id = ""
        self._send("media.session.finished", {"session_id": session_id, "group_id": group_id, "ok": ok})

    def _stop_media(self, *, ok: bool, notify: bool = True) -> None:
        if self.overlay_session is not None:
            self._stop_overlay(ok=False, notify=notify)
        session = self.media_session
        session_id = self.media_session_id
        group_id = self.media_group_id
        if not session_id:
            return
        if session is not None:
            self._cancel_media_tasks(session)
        self.media_session = None
        self.media_session_id = ""
        self.media_group_id = ""
        try:
            if self._sync_player_available:
                self.state.music_player.reset_synchronized()
            self.state.music_player.stop()
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unable to stop media player")
        if notify:
            self._send("media.session.finished", {"session_id": session_id, "group_id": group_id, "ok": ok})

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
        if self.audio_scene is not None:
            self._stop_audio_scene(ok=False)
        if self.overlay_session is not None:
            self._stop_overlay(ok=False)
        self._overlay_generation += 1
        session = _OverlaySession(
            overlay_id=overlay_id,
            url=url,
            group_id=str(payload.get("group_id") or "").strip(),
            start_at_us=_integer(payload.get("start_at_us"), maximum=2**63 - 1),
            volume_percent=_integer(foreground.get("volume_percent"), 100, maximum=100),
            duck_target=_integer(ducking.get("target_percent"), 20, maximum=100) / 100.0,
            attack_ms=_integer(ducking.get("attack_ms"), 150, maximum=10000),
            release_ms=_integer(ducking.get("release_ms"), 350, maximum=10000),
            continue_conversation=_truthy(payload.get("continue_conversation")),
            generation=self._overlay_generation,
        )
        self.overlay_session = session
        session.task = asyncio.create_task(self._run_overlay(session))

    async def _run_overlay(self, session: _OverlaySession) -> None:
        loop = asyncio.get_running_loop()
        playback_finished: asyncio.Future[None] = loop.create_future()

        def finished() -> None:
            def resolve() -> None:
                if not playback_finished.done():
                    playback_finished.set_result(None)

            self._call_soon(resolve)

        try:
            self.state.tts_player.set_volume(session.volume_percent)
            if not self._sync_overlay_available:
                await self._ramp_music_duck(session.duck_target, session.attack_ms)
                self.state.tts_player.play(session.url, done_callback=finished, stop_first=True)
                session.started = True
                actual_start_us = time.monotonic_ns() // 1000
                self._send(
                    "audio.overlay.started",
                    {
                        "overlay_id": session.overlay_id,
                        "group_id": session.group_id,
                        "scheduled_start_us": session.start_at_us,
                        "actual_start_us": actual_start_us,
                        "late_by_us": max(0, actual_start_us - session.start_at_us)
                        if session.start_at_us
                        else 0,
                    },
                )
            else:
                self.state.tts_player.prepare_synchronized(
                    session.url,
                    channel="mono",
                    loop=False,
                    done_callback=finished,
                )
                await self._wait_player_ready(self.state.tts_player, _AUDIO_PREPARE_TIMEOUT_SECONDS)
                output_latency_frames = (
                    self.media_session.output_latency_frames
                    if self.media_session is not None
                    else _MEDIA_DEFAULT_OUTPUT_LATENCY_FRAMES
                )
                latency_us = int(
                    round(output_latency_frames * 1_000_000.0 / _MEDIA_SAMPLE_RATE_HZ)
                )
                audible_deadline_us = session.start_at_us or (
                    (time.monotonic_ns() // 1000) + latency_us
                )
                resume_at_us = audible_deadline_us - latency_us
                await self._sleep_until_us(resume_at_us - (session.attack_ms * 1000))
                await self._ramp_music_duck(session.duck_target, session.attack_ms)
                await self._sleep_until_us(resume_at_us)
                if self.overlay_session is not session:
                    return
                self.state.tts_player.resume()
                actual_resume_us = time.monotonic_ns() // 1000
                actual_audible_us = actual_resume_us + latency_us
                session.started = True
                self._send(
                    "audio.overlay.started",
                    {
                        "overlay_id": session.overlay_id,
                        "group_id": session.group_id,
                        "scheduled_start_us": audible_deadline_us,
                        "actual_start_us": actual_audible_us,
                        "late_by_us": actual_audible_us - audible_deadline_us,
                        "output_latency_frames": output_latency_frames,
                    },
                )

            await playback_finished
            if self.overlay_session is not session:
                return
            await self._ramp_music_duck(1.0, session.release_ms)
            if self._sync_overlay_available:
                self.state.tts_player.reset_synchronized()
            session.finished = True
            self.overlay_session = None
            self._send(
                "audio.overlay.finished",
                {
                    "overlay_id": session.overlay_id,
                    "group_id": session.group_id,
                    "ok": True,
                    "continue_conversation": session.continue_conversation,
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unable to play Tater audio overlay")
            if self.overlay_session is session:
                self._finish_overlay_failure(session)

    def _finish_overlay_failure(self, session: _OverlaySession) -> None:
        session.finished = True
        self.overlay_session = None
        self._set_music_duck(1.0)
        try:
            self.state.tts_player.stop()
            if self._sync_overlay_available:
                self.state.tts_player.reset_synchronized()
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unable to reset failed overlay player")
        self._send(
            "audio.overlay.finished",
            {"overlay_id": session.overlay_id, "group_id": session.group_id, "ok": False},
        )

    def _stop_overlay(self, *, ok: bool, notify: bool = True) -> None:
        session = self.overlay_session
        if session is None:
            return
        self._overlay_generation += 1
        self.overlay_session = None
        session.finished = True
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        if session.task is not None and session.task is not current and not session.task.done():
            session.task.cancel()
        try:
            self.state.tts_player.stop()
            if self._sync_overlay_available:
                self.state.tts_player.reset_synchronized()
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unable to stop audio overlay")
        self._set_music_duck(1.0)
        if notify:
            self._send(
                "audio.overlay.finished",
                {"overlay_id": session.overlay_id, "group_id": session.group_id, "ok": ok},
            )

    def _start_audio_scene(self, payload: dict[str, Any]) -> None:
        foreground = payload.get("foreground") if isinstance(payload.get("foreground"), dict) else {}
        background = payload.get("background") if isinstance(payload.get("background"), dict) else {}
        ducking = payload.get("ducking") if isinstance(payload.get("ducking"), dict) else {}
        finish = payload.get("finish") if isinstance(payload.get("finish"), dict) else {}
        scene_id = str(payload.get("scene_id") or uuid.uuid4().hex).strip()
        foreground_url = str(foreground.get("url") or "").strip()
        if not foreground_url or not self._sync_overlay_available:
            self._send("audio.scene.finished", {"scene_id": scene_id, "ok": False})
            return
        if self.audio_scene is not None:
            self._stop_audio_scene(ok=False)
        if self.overlay_session is not None:
            self._stop_overlay(ok=False)
        if self.media_session_id:
            self._stop_media(ok=False)
        self._scene_generation += 1
        scene = _AudioScene(
            scene_id=scene_id,
            foreground_url=foreground_url,
            background_url=str(background.get("url") or "").strip(),
            foreground_volume_percent=_integer(foreground.get("volume_percent"), 100, maximum=100),
            background_volume_percent=_integer(background.get("volume_percent"), 60, maximum=100),
            background_loop=_truthy(background.get("loop", True)),
            duck_target=_integer(ducking.get("target_percent"), 20, maximum=100) / 100.0,
            attack_ms=_integer(ducking.get("attack_ms"), 150, maximum=10000),
            release_ms=_integer(ducking.get("release_ms"), 350, maximum=10000),
            fade_ms=_integer(finish.get("fade_ms"), 350, maximum=10000),
            generation=self._scene_generation,
        )
        self.audio_scene = scene
        scene.task = asyncio.create_task(self._run_audio_scene(scene))

    async def _run_audio_scene(self, scene: _AudioScene) -> None:
        loop = asyncio.get_running_loop()
        foreground_finished: asyncio.Future[None] = loop.create_future()

        def finished() -> None:
            def resolve() -> None:
                if not foreground_finished.done():
                    foreground_finished.set_result(None)

            self._call_soon(resolve)

        try:
            self.state.tts_player.set_volume(scene.foreground_volume_percent)
            self.state.tts_player.prepare_synchronized(
                scene.foreground_url,
                channel="mono",
                loop=False,
                done_callback=finished,
            )
            if scene.background_url:
                self.state.music_player.set_volume(scene.background_volume_percent)
                self.state.music_player.prepare_synchronized(
                    scene.background_url,
                    channel="stereo",
                    loop=scene.background_loop,
                )
            await self._wait_player_ready(self.state.tts_player, _AUDIO_PREPARE_TIMEOUT_SECONDS)
            if scene.background_url:
                await self._wait_player_ready(self.state.music_player, _AUDIO_PREPARE_TIMEOUT_SECONDS)
            if self.audio_scene is not scene:
                return

            if scene.background_url:
                self._set_music_duck(1.0)
                self.state.music_player.resume()
                await self._ramp_music_duck(scene.duck_target, scene.attack_ms)
            self.state.tts_player.resume()
            scene.started = True
            await foreground_finished
            if self.audio_scene is not scene:
                return

            if scene.background_url:
                await self._ramp_music_duck(1.0, scene.release_ms)
                await self._ramp_music_duck(0.0, scene.fade_ms)
                self.state.music_player.stop()
            self.state.tts_player.reset_synchronized()
            self.state.music_player.reset_synchronized()
            self._set_music_duck(1.0)
            scene.finished = True
            self.audio_scene = None
            self._send("audio.scene.finished", {"scene_id": scene.scene_id, "ok": True})
        except asyncio.CancelledError:
            raise
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unable to play Tater audio scene")
            if self.audio_scene is scene:
                self._stop_audio_scene(ok=False)

    def _stop_audio_scene(self, *, ok: bool, notify: bool = True) -> None:
        scene = self.audio_scene
        if scene is None:
            return
        self._scene_generation += 1
        self.audio_scene = None
        scene.finished = True
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        if scene.task is not None and scene.task is not current and not scene.task.done():
            scene.task.cancel()
        try:
            self.state.tts_player.stop()
            self.state.music_player.stop()
            self.state.tts_player.reset_synchronized()
            self.state.music_player.reset_synchronized()
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unable to stop audio scene")
        self._set_music_duck(1.0)
        if notify:
            self._send("audio.scene.finished", {"scene_id": scene.scene_id, "ok": ok})

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
            expected_sha256 = str(payload.get("sha256") or "").strip().lower()
            if expected_sha256 and not _WAKE_SHA256.fullmatch(expected_sha256):
                raise ValueError("Update SHA-256 is invalid.")
            expected_size = int(payload.get("size_bytes") or 0)
            if expected_size < 0 or expected_size > _OTA_MAX_BYTES:
                raise ValueError("Update size is outside the supported S420 range.")
            self._send("ota.status", {"status": "downloading", "progress": 0, "message": "Downloading signed Tater firmware."})
            digest = await asyncio.to_thread(
                self._download_ota,
                url,
                expected_sha256=expected_sha256,
                expected_size=expected_size,
            )
            self._send(
                "ota.status",
                {
                    "status": "rebooting",
                    "progress": 92,
                    "message": f"Verified signed firmware ({digest[:12]}); rebooting into the recovery installer.",
                },
            )
            process = await asyncio.create_subprocess_exec(
                "/usr/bin/swupdate",
                "-G",
                "-k",
                str(_SWUPDATE_KEY),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output, _ = await process.communicate()
            if process.returncode != 0:
                message = output.decode("utf-8", errors="replace").strip()[-300:]
                raise RuntimeError(message or f"swupdate exited with {process.returncode}")
            # The vendor -G mode normally reboots before returning. If reboot
            # was delayed or rejected, explicitly request it after recovery was
            # armed. Recovery verifies the SWUpdate signature before writing.
            await asyncio.sleep(1.0)
            subprocess.Popen(["/sbin/reboot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.exception("Tater OTA failed")
            self._send("ota.status", {"status": "error", "progress": 0, "message": str(exc) or type(exc).__name__})

    def _download_ota(self, url: str, *, expected_sha256: str = "", expected_size: int = 0) -> str:
        url = _validated_web_url(url, label="firmware URL")
        _OTA_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = _OTA_PATH.with_suffix(".swu.part")
        digest = hashlib.sha256()
        request = Request(url, headers={"User-Agent": "Tater-S420/0.2.0"})
        received = 0
        try:
            with urlopen(request, timeout=60) as response, temporary.open("wb") as output:
                content_length = int(response.headers.get("Content-Length") or 0)
                if content_length > _OTA_MAX_BYTES:
                    raise ValueError("Update is too large for the S420 data partition.")
                if expected_size and content_length and content_length != expected_size:
                    raise ValueError("Update Content-Length does not match the release manifest.")
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > _OTA_MAX_BYTES:
                        raise ValueError("Update is too large for the S420 data partition.")
                    output.write(chunk)
                    digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
            actual_sha256 = digest.hexdigest()
            if expected_size and received != expected_size:
                raise ValueError("Downloaded update size does not match the release manifest.")
            if expected_sha256 and actual_sha256 != expected_sha256:
                raise ValueError("Downloaded update SHA-256 does not match the release manifest.")
            os.replace(temporary, _OTA_PATH)
            return actual_sha256
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    async def close(self) -> None:
        if self.audio_scene is not None:
            self._stop_audio_scene(ok=False, notify=False)
        if self.overlay_session is not None:
            self._stop_overlay(ok=False, notify=False)
        if self.media_session_id:
            self._stop_media(ok=False, notify=False)
        for timer in self.timers.values():
            if timer.task is not None:
                timer.task.cancel()
        if self.ota_task is not None and not self.ota_task.done():
            self.ota_task.cancel()
        if self.wake_model_task is not None and not self.wake_model_task.done():
            self.wake_model_task.cancel()
            try:
                await self.wake_model_task
            except asyncio.CancelledError:
                pass
        if self.wake_sound_task is not None and not self.wake_sound_task.done():
            self.wake_sound_task.cancel()
            try:
                await self.wake_sound_task
            except asyncio.CancelledError:
                pass
