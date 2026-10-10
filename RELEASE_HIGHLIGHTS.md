- Releases ThirdReality S420 firmware `0.2.22` with selectable microWakeWord,
  openWakeWord, and Dual Wake Word modes in Tater's existing wake-word settings.
- Adds native ARM64 ONNX openWakeWord inference using the S420's existing
  beamformed microphone stream, without duplicating audio capture or beamforming.
- Runs one microWakeWord detector and one openWakeWord detector in Dual mode and
  requires both to agree before opening the microphone, reducing false wakes.
- Reads each wake model's threshold and patience directly from its published JSON
  metadata, including separate Dual-mode confirmation tuning.
- Adds accurate openWakeWord readiness, model source, inference, and error
  diagnostics while preserving timer stop-wake handling, Sendspin playback, AEC,
  passive BLE presence, and signed OTA updates.
- Fixes Sendspin startup on the S420 so Music Assistant and other compatible
  controllers can discover the speaker and use its FLAC or PCM playback modes.
