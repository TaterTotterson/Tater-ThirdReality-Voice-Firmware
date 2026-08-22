"""S420 four-channel ALSA capture with a safe mono fallback.

The S420 codec exposes two physical microphones on channels 0/1 and the
rendered stereo speaker loopback on channels 2/3 of ``hw:0,4``. Production
voice audio deliberately uses only microphone 0. Microphone 1 is measured for
diagnostics, while channels 2/3 are downmixed only for playback-reference AEC.
"""

from __future__ import annotations

import logging
import math
import subprocess
from typing import Any, Optional

import numpy as np

_LOGGER = logging.getLogger(__name__)
_CHANNEL_NAMES = ("mic0", "mic1", "ref_left", "ref_right")
_SAMPLE_WIDTH_BYTES = 2
_HARDWARE_CHANNELS = 4


class S420FourChannelMicrophone:
    """SoundCard-compatible microphone using the S420 direct ALSA endpoint."""

    def __init__(self, device: str, *, fallback_microphone: Any = None) -> None:
        self.device = str(device or "hw:0,4")
        self.fallback_microphone = fallback_microphone
        self.name = f"S420 four-channel capture ({self.device})"

    def recorder(self, *, samplerate: int, channels: int, blocksize: int):
        if channels != 1:
            raise ValueError("S420 production capture exposes one processed microphone channel")
        return S420FourChannelRecorder(
            self.device,
            samplerate=samplerate,
            blocksize=blocksize,
            fallback_microphone=self.fallback_microphone,
        )


class S420FourChannelRecorder:
    """Read mic0 plus stereo playback reference from one synchronized stream."""

    def __init__(
        self,
        device: str,
        *,
        samplerate: int = 16000,
        blocksize: int = 1024,
        fallback_microphone: Any = None,
    ) -> None:
        self.device = str(device or "hw:0,4")
        self.samplerate = int(samplerate)
        self.blocksize = int(blocksize)
        self.fallback_microphone = fallback_microphone
        self.reference_audio: Optional[bytes] = None
        self.backend = "starting"
        self.fallback_reason = ""
        self._process: Optional[subprocess.Popen[bytes]] = None
        self._fallback_context: Any = None
        self._fallback_recorder: Any = None
        self._level_squares = np.zeros(_HARDWARE_CHANNELS, dtype=np.float64)
        self._level_peaks = np.zeros(_HARDWARE_CHANNELS, dtype=np.int32)
        self._level_samples = 0

    def __enter__(self):
        try:
            self._start_direct()
        except Exception as exc:  # pylint: disable=broad-except
            self._activate_fallback(str(exc) or type(exc).__name__)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _start_direct(self) -> None:
        if self.samplerate != 16000:
            raise ValueError("S420 playback-reference AEC requires 16 kHz capture")
        command = [
            "arecord",
            "-q",
            "-D",
            self.device,
            "-t",
            "raw",
            "-f",
            "S16_LE",
            "-r",
            str(self.samplerate),
            "-c",
            str(_HARDWARE_CHANNELS),
        ]
        self._process = subprocess.Popen(  # pylint: disable=consider-using-with
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        if self._process.stdout is None:
            self._close_direct()
            raise RuntimeError("arecord did not provide an audio stream")
        self.backend = "alsa_4ch"
        self.fallback_reason = ""
        _LOGGER.info("Using S420 synchronized four-channel capture from %s", self.device)

    def _activate_fallback(self, reason: str) -> None:
        self._close_direct()
        if self.fallback_microphone is None:
            raise RuntimeError(f"S420 four-channel capture failed: {reason}")
        if self._fallback_recorder is None:
            _LOGGER.warning(
                "S420 four-channel capture unavailable (%s); using the existing mono input",
                reason,
            )
            self._fallback_context = self.fallback_microphone.recorder(
                samplerate=self.samplerate,
                channels=1,
                blocksize=self.blocksize,
            )
            self._fallback_recorder = self._fallback_context.__enter__()
        self.backend = "soundcard_fallback"
        self.fallback_reason = str(reason)[:160]
        self.reference_audio = None

    @staticmethod
    def _read_exact(stream: Any, byte_count: int) -> bytes:
        data = bytearray()
        while len(data) < byte_count:
            chunk = stream.read(byte_count - len(data))
            if not chunk:
                raise RuntimeError("four-channel ALSA stream ended")
            data.extend(chunk)
        return bytes(data)

    def _record_direct(self, frame_count: int) -> np.ndarray:
        process = self._process
        if process is None or process.stdout is None:
            raise RuntimeError("four-channel ALSA stream is not open")
        if process.poll() is not None:
            raise RuntimeError(f"arecord exited with status {process.returncode}")
        byte_count = frame_count * _HARDWARE_CHANNELS * _SAMPLE_WIDTH_BYTES
        interleaved = self._read_exact(process.stdout, byte_count)
        samples = np.frombuffer(interleaved, dtype="<i2").reshape(frame_count, _HARDWARE_CHANNELS)

        measured = samples.astype(np.float64)
        self._level_squares += np.sum(measured * measured, axis=0)
        self._level_peaks = np.maximum(
            self._level_peaks,
            np.max(np.abs(measured), axis=0).astype(np.int32),
        )
        self._level_samples += frame_count

        reference = (
            samples[:, 2].astype(np.int32) + samples[:, 3].astype(np.int32)
        ) // 2
        self.reference_audio = np.clip(reference, -32768, 32767).astype("<i2").tobytes()

        primary = samples[:, 0].astype(np.float32) / 32768.0
        return primary.reshape(-1, 1)

    def record(self, frame_count: int) -> np.ndarray:
        frame_count = int(frame_count)
        if frame_count <= 0:
            raise ValueError("frame_count must be positive")
        if self.backend == "alsa_4ch":
            try:
                return self._record_direct(frame_count)
            except Exception as exc:  # pylint: disable=broad-except
                self._activate_fallback(str(exc) or type(exc).__name__)

        self.reference_audio = None
        return self._fallback_recorder.record(frame_count)

    @staticmethod
    def _dbfs(square_sum: float, sample_count: int) -> Optional[float]:
        if square_sum <= 0.0 or sample_count <= 0:
            return None
        rms = math.sqrt(square_sum / sample_count) / 32768.0
        return round(20.0 * math.log10(max(rms, 1.0 / 32768.0)), 1)

    def status(self) -> dict[str, Any]:
        levels: dict[str, Any] = {}
        for index, name in enumerate(_CHANNEL_NAMES):
            levels[name] = {
                "rms_dbfs": self._dbfs(self._level_squares[index], self._level_samples),
                "peak": int(self._level_peaks[index]),
            }
        self._level_squares.fill(0.0)
        self._level_peaks.fill(0)
        self._level_samples = 0
        return {
            "capture_backend": self.backend,
            "capture_device": self.device,
            "reference_available": self.backend == "alsa_4ch",
            "fallback_reason": self.fallback_reason,
            "channels": levels,
        }

    def _close_direct(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        if process.stdout is not None:
            process.stdout.close()

    def close(self) -> None:
        self._close_direct()
        if self._fallback_context is not None:
            self._fallback_context.__exit__(None, None, None)
        self._fallback_context = None
        self._fallback_recorder = None
