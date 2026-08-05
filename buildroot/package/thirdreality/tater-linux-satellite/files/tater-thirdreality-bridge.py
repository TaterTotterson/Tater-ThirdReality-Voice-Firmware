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
MIC_MUTE_GPIO = Path("/sys/class/gpio/gpio438/value")
INPUT_DEVICE = Path("/dev/input/event0")
ANIMATION_DIR = Path("/usr/share/thirdreality/animation")

EV_KEY = 1
KEY_HOME = 102
INPUT_EVENT = struct.Struct("llHHI")
CLICK_WINDOW_SECONDS = 0.5
LONG_PRESS_SECONDS = 1.5

EVENT_ANIMATIONS: dict[str, tuple[str, bool]] = {
    "wake_word_detected": ("active-waking.animation", False),
    "listening": ("active-waking.animation", False),
    "thinking": ("active-thinking.animation", False),
    "tts_speaking": ("active-talking.animation", False),
    "tts_finished": ("active-ending.animation", True),
    "idle": ("active-ending.animation", True),
    "pipeline_error": ("error.animation", True),
    "disconnected": ("error.animation", True),
    "timer_ringing": ("alert.animation", False),
}
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


def read_sound_config(path: Path = SOUND_CONFIG) -> tuple[float, bool]:
    """Read the vendor sound config as normalized volume and muted state."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return 0.5, False
    if not isinstance(data, dict):
        return 0.5, False
    try:
        volume = clamp_volume(float(data.get("volume", 50)) / 100.0)
    except (TypeError, ValueError):
        volume = 0.5
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
            "listening": "active-waking.animation",
            "thinking": "active-thinking.animation",
            "speaking": "active-talking.animation",
            "alert": "alert.animation",
            "error": "error.animation",
            "muted": "mics-off_on.animation",
        }
        filename = manual_effects.get(effect)
        return (filename, False) if filename else None
    return EVENT_ANIMATIONS.get(event)


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


def show_animation(filename: str, to_idle: bool = False) -> None:
    animation = ANIMATION_DIR / filename
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
        await self.send_command("register_button")
        await self.send_command(
            "register_light",
            {
                "name": "ThirdReality LED Ring",
                "object_id": "thirdreality_led_ring",
                "effects": ["Listening", "Thinking", "Speaking", "Alert", "Error", "Muted"],
                "supports_rgb": False,
                "supports_brightness": False,
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
        elif event in PIPELINE_IDLE_EVENTS:
            self.pipeline_active = False

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
            await asyncio.sleep(0.25)

    async def dispatch_button(self, clicks: int, long_press: bool = False) -> None:
        if long_press:
            await self.send_command("button_long_press")
            return
        if clicks <= 1:
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
                            pressed_at = time.monotonic()
                        elif value == 0:
                            released_at = time.monotonic()
                            duration = released_at - pressed_at if pressed_at is not None else 0.0
                            pressed_at = None
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
