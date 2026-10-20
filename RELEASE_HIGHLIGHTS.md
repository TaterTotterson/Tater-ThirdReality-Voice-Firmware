- Releases ThirdReality S420 firmware `0.2.24` with NanoWakeWord CNN and GRU
  support alongside the existing microWakeWord and openWakeWord engines.
- Adds NWW-only and MWW + NWW confirmation modes, architecture selection,
  live model switching, and capability reporting through the Tater-native
  settings channel.
- Installs the matched built-in Hey Tater MWW, OWW, NWW-CNN, and NWW-GRU
  family and securely loads trainer-produced schema-v3 wake bundles with
  calibrated thresholds, size checks, and SHA-256 verification.
- Preserves MWW, OWW, MWW + OWW, AEC, passive BLE presence, Sendspin playback,
  timer controls, and signed OTA updates from the previous release.
