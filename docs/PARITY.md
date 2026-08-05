# Firmware parity

The firmware pins Tater Linux Voice by full commit SHA. A scheduled workflow
runs `script/update_tater_linux_source.sh --check` weekly so drift is visible;
use `--update` to advance the pin and then rerun CI and hardware tests.

| Capability | Status | Implementation |
| --- | --- | --- |
| Tater native pairing and device token | Ready | Tater Linux Voice outbound WebSocket |
| Tater-style setup hotspot | Ready | `Tater-Setup-XXXX`, captive DNS, and local setup form on `192.168.4.1` |
| Hey Tater wake word and microphone streaming | Ready | Shared Tater `hey_tater.tflite` model; `pymicro-wakeword` runtime |
| STT, TTS, tool progress, continued conversation | Ready | Pinned Tater Linux Voice state machine |
| ThirdReality LEDs | Ready | Local peripheral bridge to the D-Bus LED service |
| Hardware volume and microphone mute | Ready | Bidirectional `/data/conf/sound.json` synchronization |
| Home button press-to-talk | Ready | Single press starts or stops the active pipeline |
| Tater-native media playback | Ready | Single-device music sessions and ducked TTS overlays from the authenticated Tater server |
| Signed SWUpdate artifacts | Ready | Build-time external signing key and embedded public key |
| Native Tater timer control | Ready | Up to eight local timers; start, list, cancel, snooze, alarm, and stop-word ringing control |
| Native Tater OTA command | Ready | Authenticated URL command, local download, mandatory SWUpdate signature verification, and reboot |
| Remote Tater settings UI | Ready (S420 subset) | Live volume, mute, wake model/threshold, wake engine, continued chat, and logging level |
| Tater setup/reset command | Ready | Clears Wi-Fi and pairing, then reboots into `Tater-Setup-XXXX` |
| Production-owned secure boot | Pending | SWUpdate is rekeyed; proprietary Amlogic boot-FIP trust is not |
| Barge-in while TTS is playing | Not advertised | Client reports `barge_in: false` |
| Synchronized stereo and drift correction | Not advertised | The S420 Linux/mpv path does not guarantee sample-accurate scheduling |
| Audio scenes and looping backgrounds | Not advertised | Basic music plus TTS overlays are supported; the full ESP scene mixer is not |
| Physical-device regression pass | Pending | Requires a ThirdReality S420 unit and audio fixtures |

Capabilities stay disabled in the native hello until their complete path is
implemented and tested. The S420 intentionally does not claim the ESP
satellite's synchronized stereo, drift correction, scene mixer, or barge-in.
