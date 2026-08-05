#! /bin/sh
#
# System-V init script for the openntp daemon
#

PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
DESC="network time protocol daemon"
NAME=ntpd
DAEMON=/usr/sbin/$NAME
NTPDATE_BIN=/usr/bin/ntpdate

# Gracefully exit if the package has been removed.
test -x $DAEMON || exit 0

# Read config file if it is present.
if [ -r /etc/default/$NAME ]; then
    . /etc/default/$NAME
fi

if [ -x $NTPDATE_BIN ] ; then
    while ! wpa_cli -i wlan0 status 2>/dev/null | grep -q '^wpa_state=COMPLETED$'; do
        # The setup AP is deliberately offline. Its supervisor will restart us
        # after provisioning has completed and the device has rebooted.
        [ -f /tmp/tater-provisioning-active ] && exit 0
        sleep 1
    done

    MAX_RETRIES=5
    RETRY_DELAY=4
    attempt=0
    ntp_synced=false
    while [ $attempt -lt $MAX_RETRIES ]; do
        # Re-read config each iteration so DHCP Option 42 updates take effect
        [ -r /etc/default/$NAME ] && . /etc/default/$NAME
        # Prefer a site-local server supplied by DHCP Option 42.
        if [ -n "$NTPSERVERS_DHCP" ]; then
            $NTPDATE_BIN -b $NTPDATE_OPTS $NTPSERVERS_DHCP > /dev/null 2>&1 && { ntp_synced=true; break; }
        fi
        # Fall back to US-based NIST time servers.
        $NTPDATE_BIN -b $NTPDATE_OPTS $NTPSERVERS_DNS > /dev/null 2>&1 && { ntp_synced=true; break; }
        killall -9 ntpd > /dev/null 2>&1
        attempt=$((attempt + 1))
        [ $attempt -lt $MAX_RETRIES ] && sleep $RETRY_DELAY
    done

    if [ "$ntp_synced" = true ]; then
        echo "ntpdate OK"
    else
        echo "ntpdate FAILED after $MAX_RETRIES attempts, starting services anyway"
    fi

    # Tater-native pairing is handled by the voice client. Setup guidance is
    # announced only while the local provisioning hotspot is active.
    [ -f /data/first_wifi_connected ] || touch /data/first_wifi_connected
    #If the platform have RTC, we will write back to RTC HW
    if [ -e /dev/rtc ] || [ -e /dev/rtc0 ] || [ -e /dev/misc/rtc ]; then
        hwclock -w -u
    fi
fi

echo -n "Starting $DESC: $NAME"
start-stop-daemon -S -q -x $DAEMON

exit 0
