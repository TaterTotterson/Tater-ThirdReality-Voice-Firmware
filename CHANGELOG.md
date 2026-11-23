# 0.2.28 - 2026-11-21

- Fix the runtime wheel packaging failure caused by declaring its Python
  package version as both static and dynamic. CI now builds the wheel with
  Buildroot's Python packaging tools before starting the full firmware build.
- Build directly from the published shared Tater Linux Satellite runtime.
  Remove the separate shared Python copies and the superseded backport patches.
- Use the Native/Echo wake-boundary model and preserve early command audio
  through wake verification, wake sounds, and voice-start setup.
- Keep S420 capture/AEC, LEDs/buttons, provisioning, signed OTA, existing
  settings, and the init-managed Sendspin player in the hardware adapter.
- Validate the actual pinned and installed runtime, including its source
  checksum, instead of inspecting old patch text. Source updates retain the
  previous pin if the hardware patch or Python compilation fails.
- Unit and source-install checks pass; physical S420 testing remains pending.
