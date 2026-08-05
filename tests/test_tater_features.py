import asyncio
from enum import Enum
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
FEATURES_PATH = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/tater_features.py"
)


class _Event(str, Enum):
    TIMER_RINGING = "timer_ringing"
    IDLE = "idle"


package = types.ModuleType("linux_voice_assistant")
package.__path__ = [str(FEATURES_PATH.parent)]
peripheral = types.ModuleType("linux_voice_assistant.peripheral_api")
peripheral.LVAEvent = _Event
sys.modules.setdefault("linux_voice_assistant", package)
sys.modules.setdefault("linux_voice_assistant.peripheral_api", peripheral)
spec = importlib.util.spec_from_file_location(
    "linux_voice_assistant.tater_features", FEATURES_PATH
)
assert spec is not None and spec.loader is not None
tater_features = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tater_features
spec.loader.exec_module(tater_features)


class _Player:
    def __init__(self) -> None:
        self.volume = 100
        self.played = []
        self.done_callback = None
        self.duck_factor = None

    def set_volume(self, value):
        self.volume = value

    def play(self, url, done_callback=None, stop_first=False):
        self.played.append((url, stop_first))
        self.done_callback = done_callback

    def stop(self):
        callback = self.done_callback
        self.done_callback = None
        if callback is not None:
            callback()

    def duck(self, factor=0.5):
        self.duck_factor = factor

    def unduck(self):
        self.duck_factor = None


class _Preferences:
    def __init__(self) -> None:
        self.active_wake_words = ["hey_tater"]
        self.wake_word_1_sensitivity = None


class _State:
    def __init__(self) -> None:
        self.music_player = _Player()
        self.tts_player = _Player()
        self.stop_word = types.SimpleNamespace(id="stop")
        self.active_wake_words = {"hey_tater"}
        self.available_wake_words = {"hey_tater": object()}
        self.preferences = _Preferences()
        self.wake_word_1_threshold = 0.97
        self.wake_words_changed = False
        self.volume = 0.8
        self.saved = 0

    def persist_volume(self, value):
        self.volume = value

    def save_preferences(self):
        self.saved += 1


class _Satellite:
    def __init__(self, state) -> None:
        self.state = state
        self._timer_finished = False
        self._timer_ring_start = None
        self.events = []
        self.muted = False

    def _emit(self, event, data=None):
        self.events.append((event, data))

    def _play_timer_finished(self):
        pass

    def duck(self):
        self.state.music_player.duck()

    def unduck(self):
        self.state.music_player.unduck()

    def _set_muted(self, value):
        self.muted = value


class _Client:
    def __init__(self) -> None:
        self.state = _State()
        self.satellite = _Satellite(self.state)
        self.frames = []

    def _submit_frame(self, frame):
        self.frames.append(json.loads(frame))


class TaterFeatureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.original_settings_path = tater_features._SETTINGS_PATH
        tater_features._SETTINGS_PATH = Path(self.temporary.name) / "settings.json"
        self.client = _Client()
        self.manager = tater_features.TaterFeatureManager(self.client)

    async def asyncTearDown(self) -> None:
        await self.manager.close()
        tater_features._SETTINGS_PATH = self.original_settings_path
        self.temporary.cleanup()

    def _messages(self, message_type):
        return [frame for frame in self.client.frames if frame["type"] == message_type]

    async def test_capabilities_do_not_claim_synchronized_audio(self) -> None:
        self.assertTrue(self.manager.capabilities["timers"])
        self.assertTrue(self.manager.capabilities["ota"])
        self.assertTrue(self.manager.capabilities["live_settings"])
        self.assertFalse(self.manager.capabilities["synchronized_media_sessions"])
        self.assertFalse(self.manager.capabilities["media_drift_correction"])

    async def test_timer_start_list_and_cancel_round_trip(self) -> None:
        self.assertTrue(
            self.manager.handle_message(
                {
                    "type": "timer.start",
                    "id": "request-start",
                    "payload": {"id": "tea", "name": "Tea", "duration_ms": 60000},
                }
            )
        )
        start = self._messages("timer.result")[-1]["payload"]
        self.assertTrue(start["ok"])
        self.assertEqual(start["reply_to"], "request-start")
        self.assertEqual(start["timer"]["id"], "tea")

        self.manager.handle_message({"type": "timer.list", "id": "request-list", "payload": {}})
        listed = self._messages("timer.result")[-1]["payload"]
        self.assertEqual(listed["count"], 1)

        self.manager.handle_message(
            {"type": "timer.cancel", "id": "request-cancel", "payload": {"id": "tea"}}
        )
        cancelled = self._messages("timer.result")[-1]["payload"]
        self.assertEqual(cancelled["affected"], 1)
        self.assertFalse(self.manager.timers)

    async def test_settings_apply_and_persist(self) -> None:
        self.manager.handle_message(
            {
                "type": "settings",
                "payload": {
                    "volume_percent": 42,
                    "wake_threshold": 0.91,
                    "logging_level": "warning",
                },
            }
        )
        self.assertEqual(self.client.state.music_player.volume, 42)
        self.assertEqual(self.client.state.tts_player.volume, 42)
        self.assertAlmostEqual(self.client.state.volume, 0.42)
        self.assertAlmostEqual(self.client.state.wake_word_1_threshold, 0.91)
        persisted = json.loads(tater_features._SETTINGS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(persisted["volume_percent"], 42)

    async def test_invalid_settings_do_not_break_the_native_session(self) -> None:
        self.manager.handle_message(
            {
                "type": "settings",
                "payload": {"wake_threshold": "not-a-number", "wake_engine": "unsupported"},
            }
        )
        self.assertAlmostEqual(self.client.state.wake_word_1_threshold, 0.97)
        self.assertNotIn("wake_threshold", self.manager.settings)
        self.assertNotIn("wake_engine", self.manager.settings)

    async def test_continued_chat_setting_applies_when_response_has_no_override(self) -> None:
        self.manager.handle_message(
            {"type": "settings", "payload": {"continued_chat": True}}
        )
        body = {"type": "play.url", "payload": {"url": "https://tater.test/reply.flac"}}
        self.assertFalse(self.manager.handle_message(body))
        self.assertTrue(body["payload"]["continue_conversation"])

        explicit = {
            "type": "play.url",
            "payload": {"url": "https://tater.test/reply.flac", "continue_conversation": False},
        }
        self.assertFalse(self.manager.handle_message(explicit))
        self.assertFalse(explicit["payload"]["continue_conversation"])

    async def test_basic_media_session_and_overlay(self) -> None:
        self.manager.handle_message(
            {
                "type": "media.session.start",
                "id": "media-request",
                "payload": {
                    "session_id": "session-1",
                    "media": {"url": "https://tater.test/music.flac", "volume_percent": 55},
                },
            }
        )
        self.assertEqual(self.manager.media_session_id, "session-1")
        self.assertEqual(self.client.state.music_player.volume, 55)
        self.assertTrue(self._messages("media.session.started"))

        self.manager.handle_message(
            {
                "type": "audio.overlay.start",
                "payload": {
                    "overlay_id": "reply-1",
                    "foreground": {"url": "https://tater.test/reply.flac"},
                    "ducking": {"target_percent": 25},
                },
            }
        )
        self.assertEqual(self.client.state.music_player.duck_factor, 0.25)
        self.assertTrue(self._messages("audio.overlay.started"))
        self.client.state.tts_player.done_callback()
        self.assertIsNone(self.client.state.music_player.duck_factor)
        self.assertTrue(self._messages("audio.overlay.finished"))

    async def test_clock_sync_replies_to_request(self) -> None:
        self.manager.handle_message(
            {
                "type": "audio.clock.sync",
                "id": "clock-request",
                "payload": {"server_send_us": 9876543210123},
            }
        )
        result = self._messages("audio.clock.sync.result")[-1]["payload"]
        self.assertEqual(result["reply_to"], "clock-request")
        self.assertEqual(result["server_send_us"], 9876543210123)
        self.assertGreater(result["satellite_send_us"], 0)


if __name__ == "__main__":
    unittest.main()
