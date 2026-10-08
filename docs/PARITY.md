# Firmware parity

The firmware pins Tater Linux Voice by full commit SHA. A scheduled workflow
runs `script/update_tater_linux_source.sh --check` weekly so drift is visible;
use `--update` to advance the pin and then rerun CI and hardware tests.

| Capability | Status | Implementation |
| --- | --- | --- |
| Tater native pairing and device token | Ready | Tater Linux Voice outbound WebSocket |
| Tater-style setup hotspot | Ready | `Tater-Setup-XXXX`, captive DNS, and local setup form on `192.168.4.1` |
| Hey Tater wake word and microphone streaming | Ready | Shared Tater `hey_tater.tflite` model; `pymicro-wakeword` runtime |
| Wake during local music | Implemented; hardware validation pending | Direct `hw:0,4` capture uses mic 0 for voice and channels 2/3 as a synchronized WebRTC playback reference; AEC is enabled only while mpv renders audio, mic gain remains 1×, and capture falls back automatically to the previous mono path |
| Wake sensitivity and TV-nearby profile | Implemented; hardware validation pending | Sensitivity changes the effective microWakeWord threshold; `tv_nearby` admits a more permissive candidate and requires Tater verification with fail-open behavior |
| STT wake verification | Implemented; hardware validation pending | Observe and enforce modes send the configured 0.5–2 second PCM wake window over the authenticated Tater connection using the shared `TWV1` contract; enforcement rejects false wakes and fails open if verification is unavailable or times out |
| BLE presence | Implemented; hardware validation pending | The onboard AP6212/BCM43438 runs a bounded passive raw-HCI observer, emits the shared `ble.advertisements` v1 batches, and pauses scanning during voice, playback, or OTA activity |
| STT, TTS, tool progress, continued conversation | Ready | Pinned Tater Linux Voice state machine; each response follows Tater's explicit mic-reopen decision rather than a persisted fallback |
| ThirdReality LEDs | Ready | Local peripheral bridge to the D-Bus LED service with configurable animated listening, thinking, tool-call, and replying states |
| Hardware volume and microphone mute | Ready | Bidirectional `/data/conf/sound.json` synchronization |
| Home button press-to-talk | Ready | Single press starts or stops the active pipeline |
| Sendspin media playback | Implemented; hardware validation pending | The official headless Linux client exposes the S420 to Tater, Music Assistant, and other Sendspin servers with PCM/FLAC decoding, mDNS discovery, and PulseAudio render-clock feedback |
| Signed SWUpdate artifacts | Ready | Build-time external signing key and embedded public key |
| Native Tater timer control | Ready | Up to eight local timers; start, list, cancel, snooze, alarm, and stop-word ringing control |
| Native Tater OTA command | Ready | Authenticated URL command, local download, mandatory SWUpdate signature verification, and reboot |
| Remote Tater settings UI | Ready (S420 subset) | Live volume, mute, Sendspin stereo/left/right/mono routing, wake model/threshold/sensitivity/environment, wake engine, STT wake-verifier mode/window/timeout, built-in or custom cached wake sounds, continued chat, TTS barge-in, LED theme, and logging level |
| Tater wake-sound catalog | Implemented; hardware validation pending | The Wake Sound switch, No Sound, default chime, all embedded Tater choices, and checksum-bound custom WAV cache control the acknowledgement before microphone streaming |
| Tater setup/reset command | Ready | Clears Wi-Fi and pairing, then reboots into `Tater-Setup-XXXX` |
| Production-owned secure boot | Platform constraint | SWUpdate is rekeyed, but the proprietary Amlogic boot-FIP root remains owned by ThirdReality |
| Barge-in while TTS is playing | Implemented; hardware validation pending | Disabled by default; when enabled in Tater, a wake word cancels active TTS without opening a second pipeline during other states |
| Synchronized stereo and multi-room | Implemented; hardware validation pending | Sendspin owns stream timing, buffering, render-clock feedback, volume, and group synchronization; an S420-specific PulseAudio route selects stereo, left, right, or mono output |
| TTS overlays and announcements | Implemented; hardware validation pending | Single-device Tater reply/announcement overlays remain native; grouped playback is sent through Sendspin by the controller |
| Audio scenes and looping backgrounds | Implemented; hardware validation pending | Two mpv players provide simultaneous foreground/background playback, looping beds, independent source volumes, duck attack/release, and finish fade |
| Stream recovery | Implemented; hardware validation pending | Sendspin owns network buffering and synchronized stream recovery; the native five-second watchdog still resets frozen TTS overlays and audio scenes and restores ducking |
| Browser USB factory flashing | Platform constraint | The S420 uses Amlogic's native USB-burn protocol and requires the ThirdReality debug/log board; Tater desktop provides the supported local USB path |
| Physical-device regression pass | Core path complete | Local USB factory flashing, Tater boot verification, hotspot provisioning, pairing, voice/media playback, and signed OTA have been exercised on physical S420 hardware |

The S420 now advertises Sendspin v1 playback and output-channel selection plus
the native audio-scene v1, stalled-playback-recovery, and TTS barge-in
capabilities. The retired Tater `media.session.*` clock/sync protocol is no
longer advertised or executed. Unit and structural tests cover those paths;
physical S420 regression testing is still required for Sendspin and can further
refine audio-scene, overlay, recovery, and barge-in behavior. Secure-boot
ownership and browser-based factory flashing remain Amlogic/platform limits,
not missing Tater application features.
