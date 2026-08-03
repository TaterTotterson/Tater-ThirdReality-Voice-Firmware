# Provisioning

The production image uses the same setup contract as Tater's native satellites.
It does not include Bluetooth or Improv provisioning.

## First boot

1. Power on an unconfigured speaker.
2. Join the open `Tater-Setup-XXXX` Wi-Fi network, where `XXXX` is derived from
   the final four hexadecimal digits of the speaker's Wi-Fi MAC address.
3. Most phones open the captive page automatically. If not, browse to
   `http://192.168.4.1`.
4. Enter the 2.4 GHz Wi-Fi network and password, Tater server, one-time pairing
   code or API token, and optional room and speaker name.
5. Select **Save and restart**. The hotspot stops, the speaker joins the saved
   Wi-Fi, and Tater pairing begins.

The setup AP is intentionally open so a phone can join it without a device-
specific password. It is active only when the required Wi-Fi or Tater settings
are absent. Its DHCP and wildcard DNS services are bound to `wlan0`, use the
`192.168.4.0/24` subnet, and provide no internet route.

A temporary Wi-Fi failure does not reopen the hotspot. A speaker with saved
settings keeps retrying its configured network.

## Reopen setup

Long-press the Tap button to clear the saved Wi-Fi profile, Tater pairing token,
and Tater settings, then restart into `Tater-Setup-XXXX`. Long-pressing Home
performs the full factory reset and also clears the Wi-Fi profile.

From the serial recovery console, the equivalent command is:

```sh
tater-provisioning reset
```

## Serial recovery

The serial console remains available for recovery and advanced configuration.
Connect the ThirdReality debug board to the serial header at 115200 baud, then
run:

```sh
tater-configure \
  --server-url https://tater.example.com \
  --pairing-code YOUR_ONE_TIME_CODE \
  --room Kitchen \
  --name "Kitchen Tater"
```

Inspect the redacted configuration with `tater-configure --show`. Restart the
voice service with `/etc/init.d/S99ha-speaker voice-assistant restart`.

## Persistent data

The paired device token is stored at `/data/conf/tater-device-token` with mode
0600. Settings live in `/data/conf/tater.json`; audio preferences remain in
`/data/conf/tater-preferences.json`. After a successful pairing, the one-time
pairing code is erased from the settings on the next service start. The Wi-Fi
station profile is stored in `/etc/wpa_supplicant.conf` with mode 0600.

The production image has no network SSH or ADB service. The hotspot is a local
setup surface only; it is not available once provisioning is complete.
