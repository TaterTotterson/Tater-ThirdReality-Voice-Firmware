- Releases ThirdReality S420 firmware `0.2.25` with live per-model wake tuning
  for microWakeWord, openWakeWord, and NanoWakeWord CNN and GRU.
- Applies threshold and patience overrides to OWW and NWW in both standalone
  and MWW confirmation modes while retaining each wake bundle's calibrated
  values whenever an override is disabled.
- Advertises wake-model tuning support to Tater and keeps effective settings
  visible in the satellite diagnostics and model-ready log entry.
- Preserves all five wake modes, NanoWakeWord CNN/GRU selection, schema-v3
  custom bundles, AEC, BLE presence, Sendspin, timers, and signed OTA updates.
