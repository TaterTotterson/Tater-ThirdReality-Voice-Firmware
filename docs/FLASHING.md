# Flashing the Tater S420

The S420 has two firmware paths. They use different artifacts and must not be
interchanged.

| Situation | Artifact | Transport |
| --- | --- | --- |
| First install or full recovery | `*-factory.img` | Amlogic USB burn mode |
| Normal update after Tater is installed | `*-ota.swu` | Authenticated Tater native OTA |

Every release includes a manifest with the exact byte size and SHA-256 of both
artifacts. Tater verifies those fields before presenting or sending a file.
The S420 verifies the OTA download again, and recovery verifies its SWUpdate
signature before NAND is written.

The routine OTA contains only the system root, kernel/boot image, and device
tree. It does not write the data partition, bootloader, or U-Boot environment;
those remain factory/recovery-only so an update cannot trigger a setup reset.

## First install

The full image is not an ESP image and must never be passed to `esptool`.
Use **Tater → Settings → Voice → Firmware → Local USB**, select the
ThirdReality S420, and follow the guided connection flow. Keep both the main USB
cable and ThirdReality debug board connected. Tater verifies the release
manifest and factory-image checksum, uses its pinned Amlogic helper to enter USB
burn mode, writes every partition, reboots the speaker, and verifies that the
installed Tater runtime starts successfully.

This Local USB path is supported by the Tater macOS app. It cannot be moved to
the ESP Browser USB flasher because the S420 uses Amlogic USB-burn mode and its
debug console during recovery rather than an ESP WebUSB bootloader.

As a manual Windows alternative, install the Amlogic USB Burning Tool from
`tools/Aml_Burn_Tool.zip`, select the release's `*-factory.img`, keep the normal
erase defaults, and start the burn. Do not remove power, the debug board, or USB
until the tool reports 100 percent success. The bundled program is the vendor's
Windows utility; it is not executed by the firmware build or by Tater.

Linux x86_64 users may use the community `aml-linux-usb-burn` utility with the
`axg` SoC setting. This path is not bundled because it contains proprietary
Amlogic binaries and should be treated as an advanced recovery option.

After a successful first boot, join `Tater-Setup-XXXX` and open
`http://192.168.4.1` to enter Wi-Fi and the Tater pairing code.

## Normal Tater update

Once Tater firmware is installed, use **Settings → Voice → Firmware → Update
Firmware**. Tater sends the release URL, SHA-256, and byte size through the
authenticated satellite connection. The speaker stages the file as
`/data/software.swu`, reboots once into recovery, installs the signed update,
and then returns to the normal system. Wi-Fi, pairing, room, and live settings
remain under `/data`.

The debug board is not required for routine OTA updates.

## Recovery checks

- A normal boot reports `firmware_version=<release>` in `/proc/cmdline`.
- Recovery reports its own older recovery version; do not confuse that with
  the installed system version.
- If recovery cannot validate the SWUpdate signature, it refuses the image and
  returns to the normal system without installing it.
- Keep the debug board available for serial diagnostics at 115200 baud.
