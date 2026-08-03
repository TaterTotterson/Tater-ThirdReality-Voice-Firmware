# Firmware parity

The firmware pins Tater Linux Voice by full commit SHA. A scheduled workflow
runs `script/update_tater_linux_source.sh --check` weekly so drift is visible;
use `--update` to advance the pin and then rerun CI and hardware tests.

| Capability | Status | Implementation |
| --- | --- | --- |
| Tater native pairing and device token | Ready | Tater Linux Voice outbound WebSocket |
| Tater-style setup hotspot | Ready | `Tater-Setup-XXXX`, captive DNS, and local setup form on `192.168.4.1` |
| Local wake word and microphone streaming | Ready | `pymicro-wakeword` / `pyopen-wakeword` |
| STT, TTS, tool progress, continued conversation | Ready | Pinned Tater Linux Voice state machine |
| ThirdReality LEDs | Ready | Local peripheral bridge to the D-Bus LED service |
| Hardware volume and microphone mute | Ready | Bidirectional `/data/conf/sound.json` synchronization |
| Home button press-to-talk | Ready | Single press starts or stops the active pipeline |
| Tater-native media playback | Ready | Authenticated playback commands from the configured Tater server |
| Signed SWUpdate artifacts | Ready | Build-time external signing key |
| Production-owned secure boot | Pending | SWUpdate is rekeyed; proprietary Amlogic boot-FIP trust is not |
| Native Tater timer control | Not advertised | Tater Linux client currently reports `timers: false` |
| Native Tater OTA command | Not advertised | Signed manual OTA exists; client reports `ota: false` |
| Barge-in while TTS is playing | Not advertised | Client reports `barge_in: false` |
| Remote Tater settings UI | Planned | Current settings use the local configuration file |
| Physical-device regression pass | Pending | Requires a ThirdReality S420 unit and audio fixtures |

Capabilities stay disabled in the native hello until their complete path is
implemented and tested; the device must not claim features it cannot execute.
