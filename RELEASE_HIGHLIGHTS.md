- Releases ThirdReality S420 firmware `0.2.26` with live satellite identity editing.
- Change the satellite name and room live from Tater 3.0.4 or Home Assistant bridge
  1.4.18, including Home Assistant's device editor through the bridge. An empty
  room clears the assignment; no reset, reboot, or re-pairing is required.
- Persist both fields together in the existing `/data/conf/tater.json` before
  confirming changes. Retain pairing, Wi-Fi, stable device IDs, unrelated settings,
  and the previous identity if saving fails.
- Backport the identity protocol onto the pinned Linux runtime, preserving the
  existing wake engines, audio pipeline, and signed OTA update path.
