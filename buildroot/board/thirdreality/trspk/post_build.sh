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
    "$TARGET_DIR/etc/init.d/S99ha-speaker" \
    "$TARGET_DIR/etc/inetd.conf" \
    "$TARGET_DIR/usr/bin/adbd" \
    "$TARGET_DIR/usr/bin/dbus-cleanup-sockets" \
    "$TARGET_DIR/usr/bin/dbus-monitor" \
    "$TARGET_DIR/usr/bin/dbus-run-session" \
    "$TARGET_DIR/usr/bin/dbus-test-tool" \
    "$TARGET_DIR/usr/bin/dbus-update-activation-environment" \
    "$TARGET_DIR/usr/bin/aioesphomeapi-discover" \
    "$TARGET_DIR/usr/bin/aioesphomeapi-logs" \
    "$TARGET_DIR/usr/bin/linux-voice-assistant-server" \
    "$TARGET_DIR/usr/bin/telnet" \
    "$TARGET_DIR/usr/bin/tftp" \
    "$TARGET_DIR/usr/share/thirdreality/audio/ready_to_connect_ha.wav" \
    "$TARGET_DIR/usr/sbin/inetd" \
    "$TARGET_DIR/usr/sbin/telnetd"

# Remove metadata left by an incremental build of the pre-0.1.1 package.
# Fresh builds never create this directory, but Buildroot does not uninstall
# files from an older Python wheel when its version changes.
rm -rf "$TARGET_DIR/usr/lib/python3.11/site-packages/linux_voice_assistant-0.0.0.dist-info"
rm -rf "$TARGET_DIR/usr/lib/python3.11/site-packages/aioesphomeapi-42.7.0-py3.11.egg-info"
find "$TARGET_DIR/usr/lib/python3.11/site-packages/wakewords" -type f \
    \( -name 'hey_home_assistant.*' -o -iname '*nabu*' \) -delete 2>/dev/null || true

# Rename any compatibility directory retained by an incremental tree. Fresh
# package installs already use the private Tater module name.
if [ -d "$TARGET_DIR/usr/lib/python3.11/site-packages/aioesphomeapi" ]; then
    rm -rf "$TARGET_DIR/usr/lib/python3.11/site-packages/tater_protocol_compat"
    mv "$TARGET_DIR/usr/lib/python3.11/site-packages/aioesphomeapi" \
        "$TARGET_DIR/usr/lib/python3.11/site-packages/tater_protocol_compat"
fi

# Tater reuses only the generated protobuf/model compatibility types. Remove
# every unused network client, discovery, logging, and reconnect module.
PROTOCOL_COMPAT_DIR="$TARGET_DIR/usr/lib/python3.11/site-packages/tater_protocol_compat"
rm -rf "$PROTOCOL_COMPAT_DIR/_frame_helper"
rm -f \
    "$PROTOCOL_COMPAT_DIR/ble_defs.pyc" \
    "$PROTOCOL_COMPAT_DIR/client.pyc" \
    "$PROTOCOL_COMPAT_DIR/client_base.pyc" \
    "$PROTOCOL_COMPAT_DIR/connection.pyc" \
    "$PROTOCOL_COMPAT_DIR/discover.pyc" \
    "$PROTOCOL_COMPAT_DIR/host_resolver.pyc" \
    "$PROTOCOL_COMPAT_DIR/log_parser.pyc" \
    "$PROTOCOL_COMPAT_DIR/log_reader.pyc" \
    "$PROTOCOL_COMPAT_DIR/log_runner.pyc" \
    "$PROTOCOL_COMPAT_DIR/model_conversions.pyc" \
    "$PROTOCOL_COMPAT_DIR/reconnect_logic.pyc" \
    "$PROTOCOL_COMPAT_DIR/singleton.pyc" \
    "$PROTOCOL_COMPAT_DIR/timezone.pyc" \
    "$PROTOCOL_COMPAT_DIR/zeroconf.pyc"

# A reused output tree can retain the vendor NTP init script even after its
# package source changes. Its HA prompt is never installed, and this boundary
# check also removes the obsolete playback command itself.
if [ -f "$TARGET_DIR/etc/init.d/ntpdate.sh" ]; then
    sed -i '/ready_to_connect_ha\.wav/d' "$TARGET_DIR/etc/init.d/ntpdate.sh"
fi

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
