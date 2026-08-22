import importlib.util
import io
from pathlib import Path
import unittest
from unittest import mock

try:
    import numpy as np
except ImportError:  # Host validation images do not all carry firmware NumPy.
    np = None


ROOT = Path(__file__).resolve().parents[1]
AUDIO_PATH = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/s420_audio.py"
)
if np is not None:
    spec = importlib.util.spec_from_file_location("s420_audio", AUDIO_PATH)
    assert spec is not None and spec.loader is not None
    s420_audio = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(s420_audio)
else:
    s420_audio = None


class _Process:
    def __init__(self, payload: bytes) -> None:
        self.stdout = io.BytesIO(payload)
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class _FallbackRecorder:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def record(self, frame_count):
        return np.full((frame_count, 1), 0.25, dtype=np.float32)


class _FallbackMic:
    def recorder(self, **kwargs):
        return _FallbackRecorder()


@unittest.skipIf(np is None, "NumPy is not installed in this host test environment")
class S420AudioTests(unittest.TestCase):
    def test_direct_capture_uses_mic0_and_downmixes_playback_reference(self) -> None:
        frames = np.array(
            [
                [1000, 2000, 3000, 1000],
                [-1000, -2000, -3000, -1000],
            ],
            dtype="<i2",
        )
        process = _Process(frames.tobytes())
        with mock.patch.object(s420_audio.subprocess, "Popen", return_value=process):
            with s420_audio.S420FourChannelRecorder("hw:0,4") as recorder:
                primary = recorder.record(2)
                reference = np.frombuffer(recorder.reference_audio, dtype="<i2")
                status = recorder.status()

        np.testing.assert_allclose(
            primary.reshape(-1),
            np.array([1000, -1000], dtype=np.float32) / 32768.0,
        )
        np.testing.assert_array_equal(reference, np.array([2000, -2000], dtype="<i2"))
        self.assertEqual(status["capture_backend"], "alsa_4ch")
        self.assertEqual(status["channels"]["mic1"]["peak"], 2000)
        self.assertEqual(status["channels"]["ref_left"]["peak"], 3000)

    def test_direct_capture_failure_falls_back_to_existing_mono_input(self) -> None:
        with mock.patch.object(
            s420_audio.subprocess,
            "Popen",
            side_effect=OSError("device busy"),
        ):
            microphone = s420_audio.S420FourChannelMicrophone(
                "hw:0,4",
                fallback_microphone=_FallbackMic(),
            )
            with microphone.recorder(
                samplerate=16000,
                channels=1,
                blocksize=1024,
            ) as recorder:
                audio = recorder.record(4)
                status = recorder.status()

        np.testing.assert_array_equal(audio, np.full((4, 1), 0.25, dtype=np.float32))
        self.assertIsNone(recorder.reference_audio)
        self.assertEqual(status["capture_backend"], "soundcard_fallback")
        self.assertIn("device busy", status["fallback_reason"])


if __name__ == "__main__":
    unittest.main()
