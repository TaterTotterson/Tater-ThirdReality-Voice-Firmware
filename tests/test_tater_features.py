import asyncio
from enum import Enum
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
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
    LIGHT_COMMAND = "light_command"


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
            "buffered_seconds_known": True,
            "duration_seconds": 5.0,
            "seeking": False,
            "rebuffering": False,
            "paused": False,
            "speed": 1.0,
        }
        self.speed = 1.0
        self.resume_count = 0
        self.synchronized_resume_count = 0
        self.pause_count = 0
        self.stop_count = 0
        self.jumps = []

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

    def jump_synchronized(self, delta_seconds):
        self.jumps.append(delta_seconds)
        self.snapshot["position_seconds"] += delta_seconds

    def set_synchronized_speed(self, speed):
        self.speed = speed
        self.snapshot["speed"] = speed

    def reset_synchronized(self):
        self.speed = 1.0
        self.snapshot["speed"] = 1.0

    def resume(self):
        self.resume_count += 1
        self.snapshot["paused"] = False

    def resume_synchronized(self):
        self.synchronized_resume_count += 1
        raise RuntimeError("S420 python-mpv async resume is unavailable")

    def pause(self):
        self.pause_count += 1
        self.snapshot["paused"] = True

    def stop(self):
        self.stop_count += 1
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
        self.muted = False
        self.volume = 0.8
        self.saved = 0
        self.wakeup_sound = "/factory/wake_word_triggered.flac"

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
        self.verified_wakes = []

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
        self.state.muted = value

    def _tater_start_verified_wake(self, wake_word_phrase):
        self.verified_wakes.append(wake_word_phrase)


class _Client:
    def __init__(self) -> None:
        self.state = _State()
        self.satellite = _Satellite(self.state)
        self.frames = []
        self.binary_frames = []
        self.connected = True
        self._loop = None

    def _submit_frame(self, frame):
        if isinstance(frame, (bytes, bytearray)):
            self.binary_frames.append(bytes(frame))
        else:
            self.frames.append(json.loads(frame))


class TaterFeatureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.original_settings_path = tater_features._SETTINGS_PATH
        self.original_ota_path = tater_features._OTA_PATH
        self.original_wake_sound_dir = tater_features._TATER_WAKE_SOUND_DIR
        tater_features._SETTINGS_PATH = Path(self.temporary.name) / "settings.json"
        tater_features._OTA_PATH = Path(self.temporary.name) / "software.swu"
        tater_features._TATER_WAKE_SOUND_DIR = Path(self.temporary.name) / "wake_sounds"
        tater_features._TATER_WAKE_SOUND_DIR.mkdir()
        (tater_features._TATER_WAKE_SOUND_DIR / "blip2.wav").write_bytes(
            b"RIFF\x04\x00\x00\x00WAVE"
        )
        self.client = _Client()
        self.client._loop = asyncio.get_running_loop()
        self.manager = tater_features.TaterFeatureManager(self.client)

    async def asyncTearDown(self) -> None:
        await self.manager.close()
        tater_features._SETTINGS_PATH = self.original_settings_path
        tater_features._OTA_PATH = self.original_ota_path
        tater_features._TATER_WAKE_SOUND_DIR = self.original_wake_sound_dir
        self.temporary.cleanup()

    def _messages(self, message_type):
        return [frame for frame in self.client.frames if frame["type"] == message_type]

    async def test_capabilities_claim_sendspin_and_native_audio_features(self) -> None:
        self.assertTrue(self.manager.capabilities["timers"])
        self.assertTrue(self.manager.capabilities["ota"])
        self.assertTrue(self.manager.capabilities["live_settings"])
        self.assertTrue(self.manager.capabilities["custom_wake_words"])
        self.assertTrue(self.manager.capabilities["openwakeword"])
        self.assertTrue(self.manager.capabilities["wake_detector_selection"])
        self.assertTrue(self.manager.capabilities["dual_wake_confirmation"])
        self.assertEqual(self.manager.capabilities["dual_wake_agreement_ms"], 1200)
        self.assertTrue(self.manager.capabilities["status_led"])
        self.assertTrue(self.manager.capabilities["sendspin_player"])
        self.assertEqual(self.manager.capabilities["sendspin_version"], 1)
        self.assertTrue(self.manager.capabilities["sendspin_output_channel_selection"])
        self.assertEqual(
            self.manager.capabilities["sendspin_output_channel_modes"],
            ["stereo", "left", "right", "mono"],
        )
        self.assertTrue(self.manager.capabilities["audio_stall_recovery"])
        self.assertTrue(self.manager.capabilities["audio_scenes"])
        self.assertTrue(self.manager.capabilities["looping_background_audio"])
        self.assertTrue(self.manager.capabilities["barge_in"])
        self.assertTrue(self.manager.capabilities["wake_verifier"])
        self.assertTrue(self.manager.capabilities["wake_sensitivity"])
        self.assertTrue(self.manager.capabilities["wake_environment_profiles"])
        self.assertTrue(self.manager.capabilities["wake_during_playback"])
        self.assertTrue(self.manager.capabilities["playback_reference_aec"])
        self.assertEqual(self.manager.capabilities["audio_scene_version"], 1)
        self.assertNotIn("synchronized_media_sessions", self.manager.capabilities)

    async def test_detector_mode_is_authoritative_over_stale_flags(self) -> None:
        with mock.patch.object(self.manager, "_apply_oww_selection") as apply_oww:
            self.manager._apply_settings(  # pylint: disable=protected-access
                {
                    "wake_detector_mode": "mww",
                    "wake_mww_enabled": True,
                    "wake_oww_enabled": True,
                },
                persist=True,
            )
        self.assertEqual(self.manager.settings["wake_detector_mode"], "mww")
        self.assertTrue(self.manager.settings["wake_mww_enabled"])
        self.assertFalse(self.manager.settings["wake_oww_enabled"])
        apply_oww.assert_called_once()

    async def test_dual_mode_requires_both_detector_events(self) -> None:
        class Worker:
            def __init__(self) -> None:
                self.event = None

            def pop_detection(self):
                event, self.event = self.event, None
                return event

            def close(self):
                pass

            def status(self):
                return {"ready": True}

        worker = Worker()
        self.manager.settings["wake_detector_mode"] = "dual"
        self.manager._oww_worker = worker  # pylint: disable=protected-access
        worker.event = (time.monotonic(), 0.91)
        self.assertFalse(self.manager.resolve_wake_detection(False))
        self.assertTrue(self.manager.resolve_wake_detection(True))
        self.assertEqual(self.manager._oww_agreements, 1)  # pylint: disable=protected-access

    async def test_oww_only_mode_does_not_require_mww(self) -> None:
        worker = mock.Mock()
        worker.pop_detection.return_value = (time.monotonic(), 0.75)
        worker.status.return_value = {"ready": True}
        self.manager.settings["wake_detector_mode"] = "oww"
        self.manager._oww_worker = worker  # pylint: disable=protected-access
        self.assertTrue(self.manager.resolve_wake_detection(False))
        worker.close.assert_not_called()

    async def test_bundle_uses_mode_specific_calibration(self) -> None:
        bundle = {
            "type": "tater_wake_word_bundle",
            "wake_word": "Hey Tater",
            "open_wake_word": {
                "metadata": "hey_tater.oww.json",
                "metadata_sha256": "a" * 64,
                "artifacts": {
                    "onnx": {
                        "file": "hey_tater.oww.onnx",
                        "sha256": "b" * 64,
                        "size_bytes": 123,
                    }
                },
                "recommended_threshold": 0.56,
                "recommended_patience": 3,
                "recommended_confirmation_threshold": 0.90,
                "recommended_confirmation_patience": 2,
            },
        }
        _phrase, _section, threshold, patience = tater_features._oww_bundle_details(  # pylint: disable=protected-access
            bundle,
            confirmation=False,
        )
        self.assertEqual((threshold, patience), (0.56, 3))
        _phrase, _section, threshold, patience = tater_features._oww_bundle_details(  # pylint: disable=protected-access
            bundle,
            confirmation=True,
        )
        self.assertEqual((threshold, patience), (0.90, 2))
        self.assertNotIn("audio_session_version", self.manager.capabilities)

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

    async def test_timer_keeps_counting_offline_then_rings_and_snoozes(self) -> None:
        self.manager.handle_message(
            {
                "type": "timer.start",
                "id": "request-start",
                "payload": {"id": "offline", "duration_ms": 20},
            }
        )
        self.manager.disconnected()
        await asyncio.sleep(0.06)

        self.assertTrue(self.manager.timers["offline"].ringing)
        self.assertTrue(self.client.satellite._timer_finished)
        self.assertEqual(self.client.satellite.events[-1][0], _Event.TIMER_RINGING)
        timer_events = self._messages("timer.event")
        self.assertEqual(timer_events[-1]["payload"]["event"], "expired")

        self.manager.handle_message(
            {
                "type": "timer.snooze",
                "id": "request-snooze",
                "payload": {"id": "offline", "duration_ms": 100},
            }
        )
        self.assertFalse(self.manager.timers["offline"].ringing)
        self.assertFalse(self.client.satellite._timer_finished)
        snoozed = self._messages("timer.result")[-1]["payload"]
        self.assertEqual(snoozed["action"], "snooze")
        self.assertEqual(snoozed["affected"], 1)

    async def test_settings_apply_and_persist(self) -> None:
        with mock.patch.object(self.manager, "_restart_sendspin") as restart_sendspin:
            self.manager.handle_message(
                {
                    "type": "settings",
                    "payload": {
                        "volume_percent": 42,
                        "wake_threshold": 0.91,
                        "logging_level": "warning",
                        "barge_in_enabled": True,
                        "output_channel_mode": "left",
                    },
                }
            )
        restart_sendspin.assert_called_once_with()
        self.assertEqual(self.client.state.music_player.volume, 42)
        self.assertEqual(self.client.state.tts_player.volume, 42)
        self.assertAlmostEqual(self.client.state.volume, 0.42)
        self.assertAlmostEqual(self.client.state.wake_word_1_threshold, 0.91)
        persisted = json.loads(tater_features._SETTINGS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(persisted["volume_percent"], 42)
        self.assertEqual(persisted["output_channel_mode"], "left")
        self.assertTrue(persisted["barge_in_enabled"])
        self.assertTrue(self.client.satellite._tater_barge_in_enabled)
        self.assertEqual(self.manager.status()["sendspin"]["output_channel_mode"], "left")

    async def test_wake_verifier_settings_are_validated_and_reported(self) -> None:
        self.manager.handle_message(
            {
                "type": "settings",
                "payload": {
                    "wake_verifier_mode": "enforce",
                    "wake_verifier_window_ms": 9999,
                    "wake_verifier_timeout_ms": 1,
                },
            }
        )
        self.assertEqual(self.manager.settings["wake_verifier_mode"], "enforce")
        self.assertEqual(self.manager.settings["wake_verifier_window_ms"], 2000)
        self.assertEqual(self.manager.settings["wake_verifier_timeout_ms"], 100)
        verifier = self.manager.status()["wake_engine"]["verifier"]
        self.assertFalse(verifier["pending"])
        self.assertEqual(verifier["completed"], 0)

    async def test_wake_sensitivity_changes_effective_threshold_without_losing_base(self) -> None:
        self.manager.handle_message(
            {
                "type": "settings",
                "payload": {
                    "wake_threshold": 0.99,
                    "wake_sensitivity": "high",
                    "wake_environment": "far_field",
                },
            }
        )
        self.assertAlmostEqual(
            self.client.state.wake_word_1_threshold,
            242.0 / 255.0,
        )
        policy = self.manager.status()["wake_engine"]["policy"]
        self.assertEqual(policy["sensitivity"], "high")
        self.assertEqual(policy["environment"], "far_field")
        self.assertAlmostEqual(policy["configured_threshold"], 0.99)

        self.manager.handle_message(
            {
                "type": "settings",
                "payload": {"wake_sensitivity": "normal"},
            }
        )
        self.assertAlmostEqual(self.client.state.wake_word_1_threshold, 0.99)

    async def test_wake_sensitivity_persists_original_base_across_restart(self) -> None:
        self.manager.handle_message(
            {
                "type": "settings",
                "payload": {"wake_sensitivity": "high"},
            }
        )
        persisted = json.loads(tater_features._SETTINGS_PATH.read_text(encoding="utf-8"))
        self.assertAlmostEqual(persisted["wake_threshold"], 0.97)
        self.assertAlmostEqual(
            self.client.state.preferences.wake_word_1_sensitivity,
            242.0 / 255.0,
        )

        restarted_client = _Client()
        restarted_client.state.preferences.wake_word_1_sensitivity = 242.0 / 255.0
        restarted_client.state.wake_word_1_threshold = 242.0 / 255.0
        restarted_client._loop = asyncio.get_running_loop()
        restarted = tater_features.TaterFeatureManager(restarted_client)
        try:
            restarted.connected()
            restarted.handle_message(
                {
                    "type": "settings",
                    "payload": {"wake_sensitivity": "normal"},
                }
            )
            self.assertAlmostEqual(restarted_client.state.wake_word_1_threshold, 0.97)
        finally:
            await restarted.close()

    async def test_tv_nearby_forces_fail_open_wake_verification(self) -> None:
        self.manager.handle_message(
            {
                "type": "settings",
                "payload": {
                    "wake_threshold": 0.99,
                    "wake_sensitivity": "high",
                    "wake_environment": "tv_nearby",
                    "wake_verifier_mode": "off",
                },
            }
        )
        policy = self.manager.status()["wake_engine"]["policy"]
        self.assertAlmostEqual(policy["effective_threshold"], 219.0 / 255.0)
        self.assertTrue(policy["require_verification"])

        self.manager.capture_wake_verifier_audio(b"\x05\x00" * 16000)
        self.assertTrue(self.manager.begin_wake_verification("Hey Tater"))
        await asyncio.sleep(0)
        packet = self.client.binary_frames[-1]
        request_id = struct.Struct("<4sBBHIII").unpack_from(packet)[4]
        self.assertEqual(struct.Struct("<4sBBHIII").unpack_from(packet)[3], 1)

        self.manager.handle_message(
            {
                "type": "wake.verify.result",
                "payload": {
                    "request_id": request_id,
                    "accepted": False,
                    "available": False,
                    "reason": "verifier unavailable",
                },
            }
        )
        self.assertEqual(self.client.satellite.verified_wakes, ["Hey Tater"])
        self.assertEqual(
            self.manager.status()["wake_engine"]["verifier"]["fail_open"],
            1,
        )

    async def test_wake_verifier_observe_uploads_twv1_without_deferring(self) -> None:
        self.manager.handle_message(
            {
                "type": "settings",
                "payload": {
                    "wake_verifier_mode": "observe",
                    "wake_verifier_window_ms": 500,
                },
            }
        )
        self.manager.capture_wake_verifier_audio(b"\x01\x00" * 16000)

        self.assertFalse(self.manager.begin_wake_verification("Hey Tater"))
        self.assertEqual(len(self.client.binary_frames), 1)
        packet = self.client.binary_frames[-1]
        header = struct.Struct("<4sBBHIII")
        magic, version, codec, flags, request_id, sample_rate, sample_count = header.unpack_from(packet)
        self.assertEqual((magic, version, codec, flags), (b"TWV1", 1, 1, 0))
        self.assertGreater(request_id, 0)
        self.assertEqual(sample_rate, 16000)
        self.assertEqual(sample_count, 8000)
        self.assertEqual(len(packet) - header.size, sample_count * 2)

        self.assertTrue(
            self.manager.handle_message(
                {
                    "type": "wake.verify.result",
                    "payload": {
                        "request_id": request_id,
                        "accepted": False,
                        "available": True,
                        "reason": "wake phrase not present",
                    },
                }
            )
        )
        verifier = self.manager.status()["wake_engine"]["verifier"]
        self.assertEqual(verifier["completed"], 1)
        self.assertEqual(verifier["rejections"], 1)
        self.assertFalse(self.client.satellite.verified_wakes)

    async def test_wake_verifier_enforce_waits_for_acceptance(self) -> None:
        self.manager.handle_message(
            {
                "type": "settings",
                "payload": {
                    "wake_verifier_mode": "enforce",
                    "wake_verifier_timeout_ms": 1000,
                },
            }
        )
        self.manager.capture_wake_verifier_audio(b"\x02\x00" * 16000)

        self.assertTrue(self.manager.begin_wake_verification("Hey Tater"))
        await asyncio.sleep(0)
        packet = self.client.binary_frames[-1]
        request_id = struct.Struct("<4sBBHIII").unpack_from(packet)[4]
        self.assertEqual(struct.Struct("<4sBBHIII").unpack_from(packet)[3], 1)
        self.assertTrue(self.manager.status()["wake_engine"]["verifier"]["pending"])
        self.assertFalse(self.client.satellite.verified_wakes)

        self.manager.handle_message(
            {
                "type": "wake.verify.result",
                "payload": {
                    "request_id": request_id,
                    "accepted": True,
                    "available": True,
                    "reason": "accepted",
                },
            }
        )
        self.assertEqual(self.client.satellite.verified_wakes, ["Hey Tater"])
        verifier = self.manager.status()["wake_engine"]["verifier"]
        self.assertFalse(verifier["pending"])
        self.assertEqual(verifier["completed"], 1)

    async def test_wake_verifier_enforce_rejects_and_timeout_fails_open(self) -> None:
        self.manager.handle_message(
            {
                "type": "settings",
                "payload": {
                    "wake_verifier_mode": "enforce",
                    "wake_verifier_timeout_ms": 100,
                },
            }
        )
        self.manager.capture_wake_verifier_audio(b"\x03\x00" * 16000)
        self.assertTrue(self.manager.begin_wake_verification("Hey Tater"))
        await asyncio.sleep(0)
        request_id = struct.Struct("<4sBBHIII").unpack_from(self.client.binary_frames[-1])[4]
        self.manager.handle_message(
            {
                "type": "wake.verify.result",
                "payload": {
                    "request_id": request_id,
                    "accepted": False,
                    "available": True,
                    "reason": "rejected",
                },
            }
        )
        self.assertFalse(self.client.satellite.verified_wakes)
        self.assertEqual(self.manager.status()["wake_engine"]["verifier"]["rejections"], 1)

        self.manager.capture_wake_verifier_audio(b"\x04\x00" * 16000)
        self.assertTrue(self.manager.begin_wake_verification("Hey Tater"))
        await asyncio.sleep(0.15)
        self.assertEqual(self.client.satellite.verified_wakes, ["Hey Tater"])
        verifier = self.manager.status()["wake_engine"]["verifier"]
        self.assertEqual(verifier["completed"], 2)
        self.assertEqual(verifier["fail_open"], 1)

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

    async def test_wake_sound_settings_select_embedded_default_and_silence(self) -> None:
        self.manager.handle_message(
            {
                "type": "settings",
                "payload": {"wake_sound_enabled": True, "wake_sound": "blip2"},
            }
        )
        self.assertEqual(
            self.client.satellite._tater_wakeup_sound,
            str(tater_features._TATER_WAKE_SOUND_DIR / "blip2.wav"),
        )

        self.manager.handle_message(
            {
                "type": "settings",
                "payload": {"wake_sound_enabled": True, "wake_sound": "default"},
            }
        )
        self.assertEqual(
            self.client.satellite._tater_wakeup_sound,
            self.client.state.wakeup_sound,
        )

        self.manager.handle_message(
            {
                "type": "settings",
                "payload": {"wake_sound_enabled": False, "wake_sound": "default"},
            }
        )
        self.assertEqual(self.client.satellite._tater_wakeup_sound, "")
        persisted = json.loads(tater_features._SETTINGS_PATH.read_text(encoding="utf-8"))
        self.assertFalse(persisted["wake_sound_enabled"])
        self.assertEqual(persisted["wake_sound"], "default")

    async def test_custom_wake_sound_downloads_caches_and_activates_live(self) -> None:
        custom_path = Path(self.temporary.name) / "tater-wake-sound.wav"
        custom_path.write_bytes(b"RIFF\x04\x00\x00\x00WAVE")
        with mock.patch.object(
            tater_features,
            "_download_custom_wake_sound",
            return_value=custom_path,
        ) as download:
            self.manager.handle_message(
                {
                    "type": "settings",
                    "payload": {
                        "wake_sound_enabled": True,
                        "wake_sound": "custom",
                        "wake_sound_url": "https://tater.test/wake.wav",
                    },
                }
            )
            await asyncio.wait_for(self.manager.wake_sound_task, timeout=1)

        download.assert_called_once_with("https://tater.test/wake.wav")
        self.assertEqual(self.client.satellite._tater_wakeup_sound, str(custom_path))
        self.assertFalse(self.manager.wake_sound_downloading)
        self.assertIn("ready", self._messages("log")[-1]["payload"]["message"].lower())

    async def test_custom_wake_sound_cache_requires_matching_url_and_digest(self) -> None:
        url = "https://tater.test/wake.wav"
        data = b"RIFF\x04\x00\x00\x00WAVE"
        sound_path = tater_features._wake_sound_cache_path()
        metadata_path = tater_features._wake_sound_cache_metadata_path()
        sound_path.write_bytes(data)
        metadata_path.write_text(
            json.dumps({"url": url, "sha256": hashlib.sha256(data).hexdigest()}),
            encoding="utf-8",
        )
        self.assertEqual(tater_features._cached_custom_wake_sound(url), sound_path)
        self.assertIsNone(
            tater_features._cached_custom_wake_sound("https://tater.test/other.wav")
        )
        sound_path.write_bytes(data + b"changed")
        self.assertIsNone(tater_features._cached_custom_wake_sound(url))

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

    async def test_tool_call_start_selects_the_configured_led_state(self) -> None:
        handled = self.manager.handle_message(
            {
                "type": "voice.event",
                "payload": {
                    "event": "VOICE_ASSISTANT_TOOL_CALL_START",
                    "data": {"tool": "weather_forecast"},
                },
            }
        )

        self.assertFalse(handled)
        self.assertEqual(
            self.client.satellite.events[-1],
            (_Event.LIGHT_COMMAND, {"state": True, "effect": "tool_call"}),
        )

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

    async def test_native_overlay_remains_available_with_sendspin(self) -> None:
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
        self.assertIn(
            (_Event.LIGHT_COMMAND, {"state": True, "effect": "speaking"}),
            self.client.satellite.events,
        )
        self.client.state.tts_player.done_callback()
        await asyncio.sleep(0.01)
        self.assertIsNone(self.client.state.music_player.duck_factor)
        self.assertTrue(self._messages("audio.overlay.finished"))
        self.assertIn(
            (_Event.LIGHT_COMMAND, {"state": False}),
            self.client.satellite.events,
        )

    async def test_retired_tater_media_sync_messages_are_ignored(self) -> None:
        for message_type in sorted(tater_features._RETIRED_MEDIA_MESSAGES):
            self.assertTrue(
                self.manager.handle_message(
                    {"type": message_type, "id": "retired", "payload": {}}
                )
            )
        self.assertFalse(
            any(
                frame["type"].startswith("media.session")
                or frame["type"].startswith("audio.clock")
                for frame in self.client.frames
            )
        )

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
        self.assertIn(
            (_Event.LIGHT_COMMAND, {"state": True, "effect": "speaking"}),
            self.client.satellite.events,
        )
        self.client.state.tts_player.done_callback()
        await asyncio.sleep(0.01)
        finished = self._messages("audio.scene.finished")[-1]["payload"]
        self.assertEqual(finished, {"scene_id": "weather-scene", "ok": True})
        self.assertIsNone(self.client.state.music_player.duck_factor)
        self.assertIn(
            (_Event.LIGHT_COMMAND, {"state": False}),
            self.client.satellite.events,
        )

    async def test_overlay_watchdog_resets_stalled_tts_and_restores_music(self) -> None:
        original_watchdog_interval = tater_features._PLAYBACK_WATCHDOG_INTERVAL_SECONDS
        original_stall_timeout = tater_features._PLAYBACK_STALL_TIMEOUT_SECONDS
        tater_features._PLAYBACK_WATCHDOG_INTERVAL_SECONDS = 0.01
        tater_features._PLAYBACK_STALL_TIMEOUT_SECONDS = 0.03
        try:
            self.manager.handle_message(
                {
                    "type": "audio.overlay.start",
                    "payload": {
                        "overlay_id": "stalled-overlay",
                        "foreground": {"url": "https://tater.test/stalled-tts.flac"},
                        "ducking": {
                            "target_percent": 20,
                            "attack_ms": 0,
                            "release_ms": 0,
                        },
                    },
                }
            )
            await asyncio.sleep(0.1)

            self.assertIsNone(self.manager.overlay_session)
            self.assertGreaterEqual(self.client.state.tts_player.stop_count, 1)
            self.assertIsNone(self.client.state.music_player.duck_factor)
            finished = self._messages("audio.overlay.finished")[-1]["payload"]
            self.assertEqual(finished["overlay_id"], "stalled-overlay")
            self.assertFalse(finished["ok"])
        finally:
            tater_features._PLAYBACK_WATCHDOG_INTERVAL_SECONDS = original_watchdog_interval
            tater_features._PLAYBACK_STALL_TIMEOUT_SECONDS = original_stall_timeout

    async def test_overlay_watchdog_allows_normal_render_progress(self) -> None:
        original_watchdog_interval = tater_features._PLAYBACK_WATCHDOG_INTERVAL_SECONDS
        original_stall_timeout = tater_features._PLAYBACK_STALL_TIMEOUT_SECONDS
        tater_features._PLAYBACK_WATCHDOG_INTERVAL_SECONDS = 0.01
        tater_features._PLAYBACK_STALL_TIMEOUT_SECONDS = 0.04
        try:
            self.manager.handle_message(
                {
                    "type": "audio.overlay.start",
                    "payload": {
                        "overlay_id": "healthy-overlay",
                        "foreground": {"url": "https://tater.test/healthy-tts.flac"},
                        "ducking": {
                            "target_percent": 20,
                            "attack_ms": 0,
                            "release_ms": 0,
                        },
                    },
                }
            )

            async def advance_and_finish() -> None:
                for position in (0.01, 0.02, 0.03, 0.04):
                    await asyncio.sleep(0.01)
                    self.client.state.tts_player.snapshot["position_seconds"] = position
                callback = self.client.state.tts_player.done_callback
                self.assertIsNotNone(callback)
                callback()

            await advance_and_finish()
            await asyncio.sleep(0.02)

            self.assertIsNone(self.manager.overlay_session)
            finished = self._messages("audio.overlay.finished")[-1]["payload"]
            self.assertEqual(finished["overlay_id"], "healthy-overlay")
            self.assertTrue(finished["ok"])
            self.assertEqual(self.client.state.tts_player.stop_count, 0)
        finally:
            tater_features._PLAYBACK_WATCHDOG_INTERVAL_SECONDS = original_watchdog_interval
            tater_features._PLAYBACK_STALL_TIMEOUT_SECONDS = original_stall_timeout

    async def test_audio_scene_watchdog_stops_stalled_players(self) -> None:
        original_watchdog_interval = tater_features._PLAYBACK_WATCHDOG_INTERVAL_SECONDS
        original_stall_timeout = tater_features._PLAYBACK_STALL_TIMEOUT_SECONDS
        tater_features._PLAYBACK_WATCHDOG_INTERVAL_SECONDS = 0.01
        tater_features._PLAYBACK_STALL_TIMEOUT_SECONDS = 0.03
        try:
            self.manager.handle_message(
                {
                    "type": "audio.scene.start",
                    "payload": {
                        "scene_id": "stalled-scene",
                        "foreground": {"url": "https://tater.test/stalled-scene.flac"},
                        "background": {
                            "url": "https://tater.test/stalled-bed.flac",
                            "loop": True,
                        },
                        "ducking": {"attack_ms": 0, "release_ms": 0},
                        "finish": {"fade_ms": 0},
                    },
                }
            )
            await asyncio.sleep(0.1)

            self.assertIsNone(self.manager.audio_scene)
            self.assertGreaterEqual(self.client.state.tts_player.stop_count, 1)
            self.assertGreaterEqual(self.client.state.music_player.stop_count, 1)
            self.assertIsNone(self.client.state.music_player.duck_factor)
            finished = self._messages("audio.scene.finished")[-1]["payload"]
            self.assertEqual(finished["scene_id"], "stalled-scene")
            self.assertFalse(finished["ok"])
        finally:
            tater_features._PLAYBACK_WATCHDOG_INTERVAL_SECONDS = original_watchdog_interval
            tater_features._PLAYBACK_STALL_TIMEOUT_SECONDS = original_stall_timeout

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
