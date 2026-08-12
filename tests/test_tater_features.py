import asyncio
from enum import Enum
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FEATURES_PATH = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/tater_features.py"
)


class _Event(str, Enum):
    TIMER_RINGING = "timer_ringing"
    IDLE = "idle"


class _WakeWordType(str, Enum):
    MICRO_WAKE_WORD = "micro"


class _PackageWakeWord:
    def __init__(self, **values) -> None:
        self.__dict__.update(values)

    def load(self):
        config = json.loads(Path(self.wake_word_path).read_text(encoding="utf-8"))
        return types.SimpleNamespace(id=Path(config["model"]).stem)


package = types.ModuleType("linux_voice_assistant")
package.__path__ = [str(FEATURES_PATH.parent)]
peripheral = types.ModuleType("linux_voice_assistant.peripheral_api")
peripheral.LVAEvent = _Event
models = types.ModuleType("linux_voice_assistant.models")
models.AvailableWakeWord = _PackageWakeWord
models.WakeWordType = _WakeWordType
sys.modules.setdefault("linux_voice_assistant", package)
sys.modules.setdefault("linux_voice_assistant.peripheral_api", peripheral)
sys.modules.setdefault("linux_voice_assistant.models", models)
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
        self.synchronized_controls_available = True
        self.prepared = []
        self.snapshot = {
            "loaded": True,
            "position_seconds": 0.0,
            "buffered_seconds": 2.0,
            "seeking": False,
            "rebuffering": False,
            "paused": False,
            "speed": 1.0,
        }
        self.speed = 1.0
        self.resume_count = 0
        self.pause_count = 0

    def set_volume(self, value):
        self.volume = value

    def play(self, url, done_callback=None, stop_first=False):
        self.played.append((url, stop_first))
        self.done_callback = done_callback

    def prepare_synchronized(self, url, *, channel="stereo", loop=False, done_callback=None):
        self.prepared.append((url, channel, loop))
        self.done_callback = done_callback
        self.snapshot["paused"] = True

    def synchronized_snapshot(self):
        return dict(self.snapshot)

    def seek_synchronized(self, position_seconds):
        self.snapshot["position_seconds"] = position_seconds

    def set_synchronized_speed(self, speed):
        self.speed = speed
        self.snapshot["speed"] = speed

    def reset_synchronized(self):
        self.speed = 1.0
        self.snapshot["speed"] = 1.0

    def resume(self):
        self.resume_count += 1
        self.snapshot["paused"] = False

    def pause(self):
        self.pause_count += 1
        self.snapshot["paused"] = True

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


class _AvailableWakeWord:
    def __init__(self, wake_word="Hey Tater") -> None:
        self.wake_word = wake_word
        self.loaded = object()
        self.load_count = 0

    def load(self):
        self.load_count += 1
        return self.loaded


class _State:
    def __init__(self) -> None:
        self.music_player = _Player()
        self.tts_player = _Player()
        self.stop_word = types.SimpleNamespace(id="stop")
        self.active_wake_words = {"hey_tater"}
        self.available_wake_words = {"hey_tater": _AvailableWakeWord()}
        self.wake_words = {}
        self.download_dir = Path(tempfile.gettempdir())
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
        self.original_ota_path = tater_features._OTA_PATH
        tater_features._SETTINGS_PATH = Path(self.temporary.name) / "settings.json"
        tater_features._OTA_PATH = Path(self.temporary.name) / "software.swu"
        self.client = _Client()
        self.manager = tater_features.TaterFeatureManager(self.client)

    async def asyncTearDown(self) -> None:
        await self.manager.close()
        tater_features._SETTINGS_PATH = self.original_settings_path
        tater_features._OTA_PATH = self.original_ota_path
        self.temporary.cleanup()

    def _messages(self, message_type):
        return [frame for frame in self.client.frames if frame["type"] == message_type]

    async def test_capabilities_claim_tater_audio_session_v2(self) -> None:
        self.assertTrue(self.manager.capabilities["timers"])
        self.assertTrue(self.manager.capabilities["ota"])
        self.assertTrue(self.manager.capabilities["live_settings"])
        self.assertTrue(self.manager.capabilities["custom_wake_words"])
        self.assertTrue(self.manager.capabilities["status_led"])
        self.assertTrue(self.manager.capabilities["synchronized_media_sessions"])
        self.assertTrue(self.manager.capabilities["stereo_channel_selection"])
        self.assertTrue(self.manager.capabilities["media_playhead_telemetry"])
        self.assertTrue(self.manager.capabilities["media_drift_correction"])
        self.assertTrue(self.manager.capabilities["media_rate_slew"])
        self.assertTrue(self.manager.capabilities["media_render_clock"])
        self.assertTrue(self.manager.capabilities["media_underrun_recovery"])
        self.assertTrue(self.manager.capabilities["synchronized_tts_overlays"])
        self.assertTrue(self.manager.capabilities["audio_scenes"])
        self.assertTrue(self.manager.capabilities["looping_background_audio"])
        self.assertTrue(self.manager.capabilities["barge_in"])
        self.assertEqual(self.manager.capabilities["media_output_latency_frames"], 6144)
        self.assertEqual(self.manager.capabilities["audio_session_version"], 2)
        self.assertEqual(self.manager.capabilities["audio_scene_version"], 1)

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
                    "barge_in_enabled": True,
                },
            }
        )
        self.assertEqual(self.client.state.music_player.volume, 42)
        self.assertEqual(self.client.state.tts_player.volume, 42)
        self.assertAlmostEqual(self.client.state.volume, 0.42)
        self.assertAlmostEqual(self.client.state.wake_word_1_threshold, 0.91)
        persisted = json.loads(tater_features._SETTINGS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(persisted["volume_percent"], 42)
        self.assertTrue(persisted["barge_in_enabled"])
        self.assertTrue(self.client.satellite._tater_barge_in_enabled)

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

    async def test_installed_wake_word_is_loaded_and_activated(self) -> None:
        self.client.state.active_wake_words.clear()
        self.manager.handle_message(
            {
                "type": "settings",
                "payload": {"wake_engine": "micro_wake_word", "wake_word": "hey_tater"},
            }
        )
        self.assertEqual(self.client.state.active_wake_words, {"hey_tater"})
        self.assertIn("hey_tater", self.client.state.wake_words)
        self.assertEqual(self.client.state.preferences.active_wake_words, ["hey_tater"])
        self.assertTrue(self.client.state.wake_words_changed)

    async def test_custom_wake_word_downloads_and_activates_live(self) -> None:
        available = _AvailableWakeWord("Hello Potato")
        loaded = object()
        with mock.patch.object(
            tater_features,
            "_download_custom_wake_package",
            return_value=("tater_custom_1234", available, loaded),
        ) as download:
            self.manager.handle_message(
                {
                    "type": "settings",
                    "payload": {
                        "wake_engine": "micro_wake_word",
                        "wake_word": "custom_url",
                        "wake_word_url": "https://tater.test/hello-potato.json",
                    },
                }
            )
            await asyncio.wait_for(self.manager.wake_model_task, timeout=1)

        download.assert_called_once()
        self.assertEqual(self.client.state.active_wake_words, {"tater_custom_1234"})
        self.assertIs(self.client.state.wake_words["tater_custom_1234"], loaded)
        self.assertEqual(
            self.client.state.preferences.active_wake_words,
            ["tater_custom_1234"],
        )
        persisted = json.loads(tater_features._SETTINGS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(persisted["wake_word"], "custom_url")
        self.assertEqual(
            persisted["wake_word_url"],
            "https://tater.test/hello-potato.json",
        )
        self.assertIn("Hello Potato", self._messages("log")[-1]["payload"]["message"])

    async def test_custom_wake_failure_keeps_previous_model_active(self) -> None:
        with mock.patch.object(
            tater_features,
            "_download_custom_wake_package",
            side_effect=ValueError("bad manifest"),
        ):
            self.manager.handle_message(
                {
                    "type": "settings",
                    "payload": {
                        "wake_word": "custom_url",
                        "wake_word_url": "https://tater.test/broken.json",
                    },
                }
            )
            await asyncio.wait_for(self.manager.wake_model_task, timeout=1)

        self.assertEqual(self.client.state.active_wake_words, {"hey_tater"})
        self.assertIn("failed", self._messages("log")[-1]["payload"]["message"].lower())

    async def test_s420_led_settings_are_validated_and_persisted(self) -> None:
        self.manager.handle_message(
            {
                "type": "settings",
                "payload": {
                    "led_brightness": 67,
                    "led_color": "#FF5A1F",
                    "led_listening_animation": "pulse",
                    "led_thinking_animation": "breathe",
                    "led_tool_call_animation": "unsupported-ring-effect",
                    "led_replying_animation": "solid",
                },
            }
        )
        self.assertEqual(self.manager.settings["led_brightness"], 67)
        self.assertEqual(self.manager.settings["led_color"], "#ff5a1f")
        self.assertEqual(self.manager.settings["led_listening_animation"], "pulse")
        self.assertEqual(self.manager.settings["led_thinking_animation"], "breathe")
        self.assertEqual(self.manager.settings["led_replying_animation"], "solid")
        self.assertNotIn("led_tool_call_animation", self.manager.settings)

    async def test_custom_wake_package_keeps_runtime_and_preference_ids_aligned(self) -> None:
        manifest_url = "https://tater.test/models/hello.json"
        manifest = {
            "type": "micro",
            "wake_word": "Hello Potato",
            "model": "hello.tflite",
            "trained_languages": ["en"],
            "micro": {"probability_cutoff": 0.92, "sliding_window_size": 5},
        }
        model_data = b"test-tflite-model"
        state = types.SimpleNamespace(download_dir=Path(self.temporary.name))
        with mock.patch.object(
            tater_features,
            "_download_limited",
            side_effect=[json.dumps(manifest).encode("utf-8"), model_data],
        ):
            model_id, available, loaded = tater_features._download_custom_wake_package(
                state,
                manifest_url,
            )

        self.assertEqual(loaded.id, model_id)
        self.assertEqual(available.id, model_id)
        self.assertEqual(Path(available.wake_word_path).stem, model_id)
        cached = json.loads(Path(available.wake_word_path).read_text(encoding="utf-8"))
        self.assertEqual(Path(cached["model"]).stem, model_id)
        self.assertEqual(
            cached["_tater_model_sha256"],
            tater_features.hashlib.sha256(model_data).hexdigest(),
        )

    async def test_custom_wake_package_rejects_non_web_urls(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTP or HTTPS"):
            tater_features._validated_web_url("file:///tmp/model.json", label="model URL")

    async def test_invalid_custom_wake_update_preserves_last_good_cache(self) -> None:
        manifest_url = "https://tater.test/models/replace.json"
        manifest = {
            "type": "micro",
            "wake_word": "Hello Potato",
            "model": "replace.tflite",
            "micro": {"probability_cutoff": 0.9, "sliding_window_size": 5},
        }
        state = types.SimpleNamespace(download_dir=Path(self.temporary.name))
        with mock.patch.object(
            tater_features,
            "_download_limited",
            side_effect=[json.dumps(manifest).encode("utf-8"), b"known-good-model"],
        ):
            _model_id, available, _loaded = tater_features._download_custom_wake_package(
                state,
                manifest_url,
            )
        config_path = Path(available.wake_word_path)
        model_path = config_path.with_suffix(".tflite")
        previous_config = config_path.read_bytes()
        previous_model = model_path.read_bytes()

        class _BrokenWakeWord(_PackageWakeWord):
            def load(self):
                raise ValueError("invalid tflite")

        with mock.patch.object(
            tater_features,
            "_download_limited",
            side_effect=[json.dumps(manifest).encode("utf-8"), b"broken-model"],
        ), mock.patch.object(models, "AvailableWakeWord", _BrokenWakeWord):
            with self.assertRaisesRegex(ValueError, "invalid tflite"):
                tater_features._download_custom_wake_package(state, manifest_url)

        self.assertEqual(config_path.read_bytes(), previous_config)
        self.assertEqual(model_path.read_bytes(), previous_model)

    async def test_continued_chat_setting_does_not_override_tater_response_decision(self) -> None:
        self.manager.handle_message(
            {"type": "settings", "payload": {"continued_chat": True}}
        )
        body = {"type": "play.url", "payload": {"url": "https://tater.test/reply.flac"}}
        self.assertFalse(self.manager.handle_message(body))
        self.assertNotIn("continue_conversation", body["payload"])

        reopen = {
            "type": "play.url",
            "payload": {"url": "https://tater.test/reply.flac", "continue_conversation": True},
        }
        self.assertFalse(self.manager.handle_message(reopen))
        self.assertTrue(reopen["payload"]["continue_conversation"])

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
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(self.manager.media_session_id, "session-1")
        self.assertEqual(self.client.state.music_player.volume, 55)
        self.assertTrue(self._messages("media.session.started"))

        self.manager.handle_message(
            {
                "type": "audio.overlay.start",
                "payload": {
                    "overlay_id": "reply-1",
                    "foreground": {"url": "https://tater.test/reply.flac"},
                    "ducking": {
                        "target_percent": 25,
                        "attack_ms": 0,
                        "release_ms": 0,
                    },
                },
            }
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(self.client.state.music_player.duck_factor, 0.25)
        self.assertTrue(self._messages("audio.overlay.started"))
        self.client.state.tts_player.done_callback()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertIsNone(self.client.state.music_player.duck_factor)
        self.assertTrue(self._messages("audio.overlay.finished"))

    async def test_synchronized_overlay_honors_audible_deadline(self) -> None:
        start_at_us = (tater_features.time.monotonic_ns() // 1000) + 180_000
        self.manager.handle_message(
            {
                "type": "audio.overlay.start",
                "payload": {
                    "overlay_id": "scheduled-reply",
                    "group_id": "kitchen-pair",
                    "start_at_us": start_at_us,
                    "foreground": {"url": "https://tater.test/reply.flac"},
                    "ducking": {"target_percent": 30, "attack_ms": 0, "release_ms": 0},
                },
            }
        )
        await asyncio.sleep(0.02)
        self.assertFalse(self._messages("audio.overlay.started"))
        await asyncio.sleep(0.18)
        started = self._messages("audio.overlay.started")[-1]["payload"]
        self.assertEqual(started["scheduled_start_us"], start_at_us)
        self.assertEqual(started["group_id"], "kitchen-pair")
        self.assertGreaterEqual(self.client.state.tts_player.resume_count, 1)
        self.client.state.tts_player.done_callback()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    async def test_audio_scene_mixes_background_and_foreground_then_fades(self) -> None:
        self.manager.handle_message(
            {
                "type": "audio.scene.start",
                "payload": {
                    "scene_id": "weather-scene",
                    "foreground": {
                        "url": "https://tater.test/weather.flac",
                        "volume_percent": 95,
                    },
                    "background": {
                        "url": "https://tater.test/bed.flac",
                        "volume_percent": 60,
                        "loop": True,
                    },
                    "ducking": {"target_percent": 35, "attack_ms": 0, "release_ms": 0},
                    "finish": {"fade_ms": 0},
                },
            }
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(
            self.client.state.music_player.prepared[-1],
            ("https://tater.test/bed.flac", "stereo", True),
        )
        self.assertEqual(
            self.client.state.tts_player.prepared[-1],
            ("https://tater.test/weather.flac", "mono", False),
        )
        self.assertEqual(self.client.state.music_player.duck_factor, 0.35)
        self.assertGreaterEqual(self.client.state.music_player.resume_count, 1)
        self.assertGreaterEqual(self.client.state.tts_player.resume_count, 1)
        self.client.state.tts_player.done_callback()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        finished = self._messages("audio.scene.finished")[-1]["payload"]
        self.assertEqual(finished, {"scene_id": "weather-scene", "ok": True})
        self.assertIsNone(self.client.state.music_player.duck_factor)

    async def test_media_underrun_rejoins_shared_timeline(self) -> None:
        self.manager.handle_message(
            {
                "type": "media.session.start",
                "id": "media-request",
                "payload": {
                    "session_id": "session-recovery",
                    "media": {"url": "https://tater.test/music.flac"},
                },
            }
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        session = self.manager.media_session
        self.assertIsNotNone(session)
        session.audible_start_us = (tater_features.time.monotonic_ns() // 1000) - 2_000_000
        self.client.state.music_player.snapshot["position_seconds"] = 0.0
        await self.manager._recover_media_timeline(session)
        self.assertEqual(session.rejoin_count, 1)
        self.assertGreaterEqual(session.rejoin_frames, 90000)
        self.assertGreaterEqual(self.client.state.music_player.pause_count, 1)
        self.assertGreaterEqual(self.client.state.music_player.resume_count, 2)

    async def test_synchronized_media_prepare_commit_channel_and_playhead(self) -> None:
        original_interval = tater_features._MEDIA_PLAYHEAD_INTERVAL_SECONDS
        tater_features._MEDIA_PLAYHEAD_INTERVAL_SECONDS = 0.01
        try:
            self.manager.handle_message(
                {
                    "type": "media.session.prepare",
                    "id": "prepare-request",
                    "payload": {
                        "session_id": "stereo-session",
                        "group_id": "pair-kitchen",
                        "media": {
                            "url": "https://tater.test/music.flac",
                            "volume_percent": 65,
                            "start_position_ms": 1250,
                        },
                        "routing": {"channel": "left"},
                    },
                }
            )
            await asyncio.sleep(0.05)

            prepared = self._messages("media.session.prepare.result")[-1]["payload"]
            self.assertTrue(prepared["ok"])
            self.assertEqual(prepared["reply_to"], "prepare-request")
            self.assertEqual(prepared["sample_rate_hz"], 48000)
            self.assertEqual(prepared["output_latency_frames"], 6144)
            self.assertEqual(
                self.client.state.music_player.prepared[-1],
                ("https://tater.test/music.flac", "left", False),
            )
            self.assertAlmostEqual(
                self.client.state.music_player.snapshot["position_seconds"],
                1.25,
            )
            self.assertEqual(self.client.state.music_player.resume_count, 0)

            start_at_us = (tater_features.time.monotonic_ns() // 1000) + 20_000
            self.manager.handle_message(
                {
                    "type": "media.session.commit",
                    "id": "commit-request",
                    "payload": {
                        "session_id": "stereo-session",
                        "group_id": "pair-kitchen",
                        "start_at_us": start_at_us,
                    },
                }
            )
            committed = self._messages("media.session.commit.result")[-1]["payload"]
            self.assertTrue(committed["ok"])
            self.assertEqual(self.client.state.music_player.resume_count, 0)

            await asyncio.sleep(0.05)
            started = self._messages("media.session.started")[-1]["payload"]
            self.assertEqual(started["channel"], "left")
            self.assertEqual(started["scheduled_start_us"], start_at_us)
            self.assertGreaterEqual(self.client.state.music_player.resume_count, 1)
            playhead = self._messages("media.session.playhead")[-1]["payload"]
            self.assertIn("rendered_frames", playhead)
            self.assertIn("output_latency_frames", playhead)
            self.assertEqual(playhead["output_frames"], playhead["rendered_frames"])
            self.assertEqual(playhead["playback_rate"], 1.0)
        finally:
            tater_features._MEDIA_PLAYHEAD_INTERVAL_SECONDS = original_interval

    async def test_synchronized_media_rate_slew_is_applied_and_reset(self) -> None:
        self.manager.handle_message(
            {
                "type": "media.session.start",
                "id": "media-request",
                "payload": {
                    "session_id": "session-slew",
                    "media": {"url": "https://tater.test/music.flac"},
                },
            }
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.manager.handle_message(
            {
                "type": "media.session.adjust",
                "id": "adjust-request",
                "payload": {
                    "session_id": "session-slew",
                    "correction_frames": 48,
                    "mode": "slew",
                    "settle_ms": 100,
                },
            }
        )
        adjusted = self._messages("media.session.adjust.result")[-1]["payload"]
        self.assertTrue(adjusted["ok"])
        self.assertGreater(self.client.state.music_player.speed, 1.0)
        await asyncio.sleep(0.12)
        self.assertEqual(self.client.state.music_player.speed, 1.0)

    async def test_commit_without_prepared_session_is_rejected(self) -> None:
        self.manager.handle_message(
            {
                "type": "media.session.commit",
                "id": "commit-request",
                "payload": {"session_id": "missing", "start_at_us": 123},
            }
        )
        result = self._messages("media.session.commit.result")[-1]["payload"]
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["error"])

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

    async def test_ota_download_is_staged_only_after_hash_and_size_verify(self) -> None:
        firmware = b"signed-s420-update" * 4096
        expected_sha256 = hashlib.sha256(firmware).hexdigest()

        class _Response(io.BytesIO):
            def __init__(self, data: bytes) -> None:
                super().__init__(data)
                self.headers = {"Content-Length": str(len(data))}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        with mock.patch.object(
            tater_features,
            "urlopen",
            return_value=_Response(firmware),
        ):
            actual_sha256 = self.manager._download_ota(
                "https://updates.tater.test/s420.swu",
                expected_sha256=expected_sha256,
                expected_size=len(firmware),
            )

        self.assertEqual(actual_sha256, expected_sha256)
        self.assertEqual(tater_features._OTA_PATH.read_bytes(), firmware)
        self.assertFalse(tater_features._OTA_PATH.with_suffix(".swu.part").exists())

    async def test_ota_download_rejects_hash_mismatch_without_replacing_image(self) -> None:
        firmware = b"tampered-s420-update"
        tater_features._OTA_PATH.write_bytes(b"previous-known-good-update")

        class _Response(io.BytesIO):
            def __init__(self, data: bytes) -> None:
                super().__init__(data)
                self.headers = {"Content-Length": str(len(data))}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        with mock.patch.object(
            tater_features,
            "urlopen",
            return_value=_Response(firmware),
        ):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                self.manager._download_ota(
                    "https://updates.tater.test/s420.swu",
                    expected_sha256="0" * 64,
                    expected_size=len(firmware),
                )

        self.assertEqual(
            tater_features._OTA_PATH.read_bytes(),
            b"previous-known-good-update",
        )
        self.assertFalse(tater_features._OTA_PATH.with_suffix(".swu.part").exists())

    async def test_ota_arms_recovery_after_verified_download(self) -> None:
        digest = "a" * 64
        process = mock.Mock(returncode=0)
        process.communicate = mock.AsyncMock(return_value=(b"", None))

        with mock.patch.object(
            asyncio,
            "to_thread",
            new=mock.AsyncMock(return_value=digest),
        ) as download, mock.patch.object(
            asyncio,
            "create_subprocess_exec",
            new=mock.AsyncMock(return_value=process),
        ) as swupdate, mock.patch.object(
            asyncio,
            "sleep",
            new=mock.AsyncMock(),
        ), mock.patch.object(tater_features.subprocess, "Popen") as reboot:
            await self.manager._run_ota(
                {
                    "url": "https://updates.tater.test/s420.swu",
                    "sha256": digest,
                    "size_bytes": 123456,
                }
            )

        download.assert_awaited_once_with(
            self.manager._download_ota,
            "https://updates.tater.test/s420.swu",
            expected_sha256=digest,
            expected_size=123456,
        )
        swupdate.assert_awaited_once_with(
            "/usr/bin/swupdate",
            "-G",
            "-k",
            str(tater_features._SWUPDATE_KEY),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        reboot.assert_called_once_with(
            ["/sbin/reboot"],
            stdout=tater_features.subprocess.DEVNULL,
            stderr=tater_features.subprocess.DEVNULL,
        )
        self.assertEqual(self._messages("ota.status")[-1]["payload"]["status"], "rebooting")
        self.assertEqual(self._messages("ota.status")[-1]["payload"]["progress"], 92)


if __name__ == "__main__":
    unittest.main()
