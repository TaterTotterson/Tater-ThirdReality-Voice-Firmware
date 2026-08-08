#!/usr/bin/env python3
"""Bridge ThirdReality hardware to Tater Linux Voice's local peripheral API."""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import struct
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

try:
    import websockets
except ImportError:  # Allows dependency-free host-side unit tests.
    websockets = None  # type: ignore[assignment]

_LOGGER = logging.getLogger("tater-thirdreality-bridge")

PERIPHERAL_URL = "ws://127.0.0.1:6055"
SOUND_CONFIG = Path("/data/conf/sound.json")
SOUND_LOCK = Path("/tmp/sound_config.lock")
LIVE_SETTINGS = Path("/data/conf/tater-live-settings.json")
MIC_MUTE_GPIO = Path("/sys/class/gpio/gpio438/value")
INPUT_DEVICE = Path("/dev/input/event0")
ANIMATION_DIR = Path("/usr/share/thirdreality/animation")
TATER_ANIMATION_DIR = Path("/data/tater/led-animations")

EV_KEY = 1
KEY_HOME = 102
INPUT_EVENT = struct.Struct("llHHI")
CLICK_WINDOW_SECONDS = 0.5
MIN_PRESS_SECONDS = 0.03
LONG_PRESS_SECONDS = 1.5

EVENT_ANIMATIONS: dict[str, tuple[str, bool]] = {
    "wake_word_detected": ("tater-listening.animation", False),
    "listening": ("tater-listening.animation", False),
    "thinking": ("tater-thinking.animation", False),
    "tts_speaking": ("tater-replying.animation", False),
    "tts_finished": ("active-ending.animation", True),
    "idle": ("active-ending.animation", True),
    "pipeline_error": ("error.animation", True),
    "disconnected": ("error.animation", True),
    "timer_ringing": ("alert.animation", False),
}
TATER_LED_DEFAULTS: dict[str, Any] = {
    "led_brightness": 80,
    "led_color": "#ff5a1f",
    "led_listening_animation": "pulse",
    "led_thinking_animation": "breathe",
    "led_replying_animation": "pulse",
}
TATER_LED_STYLES = {"pulse", "breathe", "heartbeat", "solid"}
PIPELINE_ACTIVE_EVENTS = {
    "wake_word_detected",
    "listening",
    "thinking",
    "tts_speaking",
}
PIPELINE_IDLE_EVENTS = {
    "tts_finished",
    "idle",
    "pipeline_error",
    "disconnected",
}


def clamp_volume(value: Any) -> float:
    """Coerce a volume into the normalized 0.0-1.0 range."""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


def coerce_bool(value: Any, default: bool = False) -> bool:
    """Coerce JSON- and config-shaped values without treating "false" as true."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return default


def completed_press_duration(
    pressed_at: Optional[float],
    released_at: float,
) -> Optional[float]:
    """Return a valid press duration, ignoring orphan releases and GPIO bounce."""
    if pressed_at is None:
        return None
    duration = max(0.0, released_at - pressed_at)
    if duration < MIN_PRESS_SECONDS:
        return None
    return duration


def read_sound_config(path: Path = SOUND_CONFIG) -> tuple[float, bool]:
    """Read the vendor sound config as normalized volume and muted state."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return 0.8, False
    if not isinstance(data, dict):
        return 0.8, False
    try:
        volume = clamp_volume(float(data.get("volume", 80)) / 100.0)
    except (TypeError, ValueError):
        volume = 0.8
    muted = not coerce_bool(data.get("mic_mute", 1), default=True)
    return volume, muted


def event_animation(event: str, data: Optional[dict[str, Any]] = None) -> Optional[tuple[str, bool]]:
    """Resolve a peripheral event into an LED animation and idle flag."""
    if event == "muted":
        muted = coerce_bool((data or {}).get("muted", False))
        return ("mics-off_on.animation", True) if muted else ("none.animation", True)
    if event == "connection" and (data or {}).get("status") == "connected":
        return "none.animation", True
    if event == "light_command":
        payload = data or {}
        if not coerce_bool(payload.get("state", False)):
            return "none.animation", True
        effect = str(payload.get("effect") or "").strip().lower()
        manual_effects = {
            "listening": "tater-listening.animation",
            "thinking": "tater-thinking.animation",
            "speaking": "tater-replying.animation",
            "alert": "alert.animation",
            "error": "error.animation",
            "muted": "mics-off_on.animation",
        }
        filename = manual_effects.get(effect)
        return (filename, False) if filename else None
    return EVENT_ANIMATIONS.get(event)


def read_led_settings(path: Path = LIVE_SETTINGS) -> dict[str, Any]:
    """Load the small set of effects the S420's single status light supports."""
    settings = dict(TATER_LED_DEFAULTS)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        value = {}
    if not isinstance(value, dict):
        value = {}

    try:
        settings["led_brightness"] = max(0, min(100, int(round(float(value.get("led_brightness", 80))))))
    except (TypeError, ValueError):
        pass
    color = str(value.get("led_color") or "").strip().lower()
    if len(color) == 7 and color.startswith("#"):
        try:
            int(color[1:], 16)
            settings["led_color"] = color
        except ValueError:
            pass
    for key in (
        "led_listening_animation",
        "led_thinking_animation",
        "led_replying_animation",
    ):
        style = str(value.get(key) or "").strip().lower()
        if style in TATER_LED_STYLES:
            settings[key] = style
    return settings


def _scaled_color(color: str, brightness: int, intensity: float) -> str:
    factor = max(0.0, min(1.0, brightness / 100.0)) * max(0.0, min(1.0, intensity))
    channels = [int(color[offset : offset + 2], 16) for offset in (1, 3, 5)]
    return "".join(f"{int(round(channel * factor)):02x}" for channel in channels)


def animation_text(style: str, color: str, brightness: int) -> str:
    """Create an S420 animation using only its visible center status light."""
    patterns: dict[str, list[tuple[int, float]]] = {
        "pulse": [(55, value) for value in (0.12, 0.28, 0.52, 0.78, 1.0, 0.78, 0.52, 0.28)],
        "breathe": [(95, value) for value in (0.10, 0.20, 0.36, 0.58, 0.80, 1.0, 0.80, 0.58, 0.36, 0.20)],
        "heartbeat": [(70, value) for value in (0.08, 1.0, 0.15, 0.08, 0.68, 0.12, 0.08, 0.08)],
        "solid": [(250, 1.0)],
    }
    frames = patterns.get(style, patterns["pulse"])
    lines = ["loop"]
    for duration, intensity in frames:
        visible = _scaled_color(color, brightness, intensity)
        lines.append(f"{duration}:{','.join([visible] + ['000000'] * 11)}")
    return "\n".join(lines) + "\n"


def write_tater_animations(
    settings: dict[str, Any],
    directory: Path = TATER_ANIMATION_DIR,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    color = str(settings["led_color"])
    brightness = int(settings["led_brightness"])
    states = {
        "listening": str(settings["led_listening_animation"]),
        "thinking": str(settings["led_thinking_animation"]),
        "replying": str(settings["led_replying_animation"]),
    }
    for state, style in states.items():
        path = directory / f"tater-{state}.animation"
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(animation_text(style, color, brightness), encoding="utf-8")
        os.replace(temporary, path)


def _atomic_sound_update(updates: dict[str, Any], path: Path = SOUND_CONFIG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    SOUND_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with SOUND_LOCK.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, json.JSONDecodeError):
                current = {}
            if not isinstance(current, dict):
                current = {}
            current.update(updates)
            temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            temporary.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def apply_hardware_volume(volume: float) -> None:
    percent = int(round(clamp_volume(volume) * 100))
    _atomic_sound_update({"volume": percent})


def apply_hardware_mute(muted: bool) -> None:
    gpio_value = "0" if muted else "1"
    try:
        if MIC_MUTE_GPIO.exists():
            MIC_MUTE_GPIO.write_text(gpio_value, encoding="utf-8")
    except OSError:
        _LOGGER.exception("Unable to update microphone mute GPIO")
    _atomic_sound_update({"mic_mute": int(gpio_value)})


def ensure_unity_sink_volume() -> None:
    """Keep PulseAudio neutral; Tater's player owns the one user volume stage."""
    try:
        subprocess.run(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "100%"],
            check=False,
            timeout=2,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        _LOGGER.exception("Unable to set the PulseAudio sink to unity volume")


def show_animation(filename: str, to_idle: bool = False) -> None:
    tater_animation = TATER_ANIMATION_DIR / filename
    animation = tater_animation if tater_animation.exists() else ANIMATION_DIR / filename
    command = [
        "dbus-send",
        "--system",
        "--type=signal",
        "/com/3r/EventBus",
        "com._3reality.EventBus.LedShow",
        f"boolean:{'true' if to_idle else 'false'}",
        f"array:string:{animation}",
    ]
    try:
        subprocess.run(command, check=False, timeout=2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        _LOGGER.exception("Unable to show LED animation %s", filename)


class ThirdRealityBridge:
    """Maintain hardware synchronization across peripheral API reconnects."""

    def __init__(self, url: str = PERIPHERAL_URL) -> None:
        self.url = url
        self.websocket: Any = None
        self.send_lock = asyncio.Lock()
        self.pipeline_active = False
        self.last_volume: Optional[float] = None
        self.last_muted: Optional[bool] = None
        self.last_led_settings: Optional[dict[str, Any]] = None
        self.current_led_event = "idle"

    async def send_command(self, command: str, data: Optional[dict[str, Any]] = None) -> None:
        websocket = self.websocket
        if websocket is None:
            return
        message: dict[str, Any] = {"command": command}
        if data:
            message["data"] = data
        async with self.send_lock:
            try:
                await websocket.send(json.dumps(message, separators=(",", ":")))
            except Exception:
                _LOGGER.debug("Peripheral command failed during reconnect: %s", command)

    async def register_hardware(self) -> None:
        await asyncio.to_thread(ensure_unity_sink_volume)
        led_settings = await asyncio.to_thread(read_led_settings)
        await asyncio.to_thread(write_tater_animations, led_settings)
        self.last_led_settings = led_settings
        await self.send_command("register_button")
        await self.send_command(
            "register_light",
            {
                "name": "Tater S420 Status Light",
                "object_id": "tater_s420_status_light",
                "effects": ["Tater Pulse", "Tater Breathe", "Tater Heartbeat", "Steady Tater Glow"],
                "supports_rgb": True,
                "supports_brightness": True,
            },
        )
        volume, muted = read_sound_config()
        self.last_volume = volume
        self.last_muted = muted
        await self.send_command("set_volume", {"volume": volume})
        await self.send_command("mute_mic" if muted else "unmute_mic")

    async def handle_event(self, raw: str) -> None:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(message, dict):
            return
        event = str(message.get("event") or "")
        data = message.get("data")
        payload = data if isinstance(data, dict) else {}

        if event == "snapshot":
            # Persistent hardware state is authoritative when the bridge first
            # reconnects, so do not overwrite it with a stale process snapshot.
            if self.last_muted:
                show_animation("mics-off_on.animation", True)
            elif not bool(payload.get("tater_connected", False)):
                show_animation("error.animation", True)
            return

        if event == "volume_changed":
            volume = clamp_volume(payload.get("volume"))
            self.last_volume = volume
            await asyncio.to_thread(apply_hardware_volume, volume)
        elif event == "muted":
            muted = coerce_bool(payload.get("muted", False))
            self.last_muted = muted
            await asyncio.to_thread(apply_hardware_mute, muted)

        if event in PIPELINE_ACTIVE_EVENTS:
            self.pipeline_active = True
            self.current_led_event = event
        elif event in PIPELINE_IDLE_EVENTS:
            self.pipeline_active = False
            self.current_led_event = event

        animation = event_animation(event, payload)
        if animation is not None:
            await asyncio.to_thread(show_animation, animation[0], animation[1])

    async def hardware_sync_loop(self) -> None:
        while True:
            volume, muted = await asyncio.to_thread(read_sound_config)
            if self.last_volume is None or abs(volume - self.last_volume) > 0.001:
                self.last_volume = volume
                await self.send_command("set_volume", {"volume": volume})
            if self.last_muted is None or muted != self.last_muted:
                self.last_muted = muted
                await self.send_command("mute_mic" if muted else "unmute_mic")
            led_settings = await asyncio.to_thread(read_led_settings)
            if led_settings != self.last_led_settings:
                self.last_led_settings = led_settings
                await asyncio.to_thread(write_tater_animations, led_settings)
                animation = event_animation(self.current_led_event)
                if animation is not None:
                    await asyncio.to_thread(show_animation, animation[0], animation[1])
            await asyncio.sleep(0.25)

    async def dispatch_button(self, clicks: int, long_press: bool = False) -> None:
        if long_press:
            _LOGGER.info("Home button long press")
            await self.send_command("button_long_press")
            return
        if clicks <= 0:
            _LOGGER.debug("Ignoring home button dispatch without a completed click")
            return
        _LOGGER.info("Home button press clicks=%s pipeline_active=%s", clicks, self.pipeline_active)
        if clicks == 1:
            await self.send_command("button_single_press")
            await self.send_command("stop_pipeline" if self.pipeline_active else "start_listening")
        elif clicks == 2:
            await self.send_command("button_double_press")
        else:
            await self.send_command("button_triple_press")

    async def button_loop(self) -> None:
        while True:
            try:
                descriptor = os.open(INPUT_DEVICE, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                await asyncio.sleep(5)
                continue

            click_count = 0
            last_release: Optional[float] = None
            pressed_at: Optional[float] = None
            try:
                while True:
                    now = time.monotonic()
                    if click_count and last_release is not None and now - last_release >= CLICK_WINDOW_SECONDS:
                        await self.dispatch_button(click_count)
                        click_count = 0
                        last_release = None

                    try:
                        chunk = os.read(descriptor, INPUT_EVENT.size * 8)
                    except BlockingIOError:
                        await asyncio.sleep(0.05)
                        continue

                    if not chunk:
                        await asyncio.sleep(0.05)
                        continue

                    for offset in range(0, len(chunk) - INPUT_EVENT.size + 1, INPUT_EVENT.size):
                        _, _, event_type, code, value = INPUT_EVENT.unpack_from(chunk, offset)
                        if event_type != EV_KEY or code != KEY_HOME:
                            continue
                        if value == 1:
                            if pressed_at is None:
                                pressed_at = time.monotonic()
                        elif value == 0:
                            released_at = time.monotonic()
                            duration = completed_press_duration(pressed_at, released_at)
                            pressed_at = None
                            if duration is None:
                                _LOGGER.debug("Ignoring unmatched or bounced home button release")
                                continue
                            if duration >= LONG_PRESS_SECONDS:
                                click_count = 0
                                last_release = None
                                await self.dispatch_button(0, long_press=True)
                            else:
                                click_count += 1
                                last_release = released_at
            except OSError:
                _LOGGER.warning("Home button input disappeared; reopening")
            finally:
                os.close(descriptor)

    async def connection_loop(self) -> None:
        if websockets is None:
            raise RuntimeError("python-websockets is required")
        while True:
            try:
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=20) as websocket:
                    self.websocket = websocket
                    _LOGGER.info("Connected to Tater Linux Voice peripheral API")
                    await self.register_hardware()
                    async for raw in websocket:
                        if isinstance(raw, str):
                            await self.handle_event(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOGGER.warning("Peripheral API unavailable (%s); retrying", exc)
            finally:
                self.websocket = None
                self.pipeline_active = False
                await asyncio.to_thread(show_animation, "error.animation", True)
            await asyncio.sleep(2)

    async def run(self) -> None:
        await asyncio.gather(
            self.connection_loop(),
            self.hardware_sync_loop(),
            self.button_loop(),
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(ThirdRealityBridge().run())


if __name__ == "__main__":
    main()
