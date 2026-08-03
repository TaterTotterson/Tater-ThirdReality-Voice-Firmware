#!/bin/sh

# Store build timestamp so the device boots with a sane default time
# instead of 1970-01-01 (no RTC battery). This accelerates NTP sync
# and avoids TLS/DNS failures caused by expired certificates.
date -u +%Y%m%d%H%M > $TARGET_DIR/etc/build_timestamp

# A reused Buildroot output directory can retain files that disappeared from
# an overlay or BusyBox applet set. Enforce the Tater production policy at the
# final rootfs boundary so neither fresh nor incremental images expose them.
rm -f \
    "$TARGET_DIR/etc/init.d/S41inetd" \
    "$TARGET_DIR/etc/init.d/S55adbd" \
    "$TARGET_DIR/etc/inetd.conf" \
    "$TARGET_DIR/usr/bin/adbd" \
    "$TARGET_DIR/usr/bin/dbus-cleanup-sockets" \
    "$TARGET_DIR/usr/bin/dbus-monitor" \
    "$TARGET_DIR/usr/bin/dbus-run-session" \
    "$TARGET_DIR/usr/bin/dbus-test-tool" \
    "$TARGET_DIR/usr/bin/dbus-update-activation-environment" \
    "$TARGET_DIR/usr/bin/telnet" \
    "$TARGET_DIR/usr/bin/tftp" \
    "$TARGET_DIR/usr/sbin/inetd" \
    "$TARGET_DIR/usr/sbin/telnetd"

# PulseAudio builds these network media modules by default even when Avahi is
# disabled. Tater uses its native music path and must not expose RTP/RAOP/Rygel
# receivers or senders if a configuration is changed later.
rm -f \
    "$TARGET_DIR/usr/lib/pulseaudio/modules/libraop.so" \
    "$TARGET_DIR/usr/lib/pulseaudio/modules/librtp.so" \
    "$TARGET_DIR/usr/lib/pulseaudio/modules/module-raop-sink.so" \
    "$TARGET_DIR/usr/lib/pulseaudio/modules/module-rtp-recv.so" \
    "$TARGET_DIR/usr/lib/pulseaudio/modules/module-rtp-send.so" \
    "$TARGET_DIR/usr/lib/pulseaudio/modules/module-rygel-media-server.so"

exit 0
