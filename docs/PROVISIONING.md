# Provisioning

The production image keeps ThirdReality's Bluetooth Improv Wi-Fi flow. Use the
Home Assistant mobile app to provide the 2.4 GHz network credentials.

Tater enrollment is deliberately separate from Wi-Fi enrollment:

1. Connect the ThirdReality debug board to the serial header at 115200 baud.
2. At the local recovery shell, run:

   ```sh
   tater-configure \
     --server-url https://tater.example.com \
     --pairing-code YOUR_ONE_TIME_CODE \
     --room Kitchen \
     --name "Kitchen Tater"
   ```

3. Inspect the redacted configuration with `tater-configure --show`.
4. Watch the service with `ps` or restart it with
   `/etc/init.d/S99ha-speaker voice-assistant restart`.

The paired device token is stored at `/data/conf/tater-device-token` with mode
0600. Settings live in `/data/conf/tater.json`; audio preferences remain in
`/data/conf/tater-preferences.json`. After a successful pairing, the one-time
pairing code is erased from the settings on the next service start. It can also
be removed immediately with `tater-configure --clear-pairing-code`.

The production image has no network SSH or ADB service. Configuration therefore
requires local physical access until a Tater-managed provisioning flow is
implemented.
