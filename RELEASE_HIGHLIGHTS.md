- Releases ThirdReality S420 firmware `0.2.21` on top of the production-stability
  baseline restored in `0.2.20`.
- Adds the pinned official Sendspin Linux player with local mDNS discovery,
  encrypted pairing support, unpaired Tater compatibility, and synchronized
  48 kHz PCM/FLAC playback from Tater, Music Assistant, and other compatible
  controllers.
- Adds persistent `stereo`, `left`, `right`, and `mono` output routing for
  multi-room groups and stereo pairs, and supervises the Sendspin service so it
  restarts automatically if it exits.
- Removes the retired Tater `audio.clock.sync` and `media.session.*` playback
  implementation while retaining native reply TTS, announcements, audio scenes,
  wake handling, AEC, passive BLE presence, and signed OTA.
- Adds No Animation for listening, thinking, tool-call, and replying LED states
  without suppressing setup, error, timer, mute, volume, OTA, or connection
  indicators.
- Keeps the `0.2.20` rollback decision: experimental connectable BLE enrollment
  remains removed while passive, non-connectable BLE presence reporting stays
  enabled.
