import importlib.util
from pathlib import Path
import struct
import unittest
from unittest.mock import MagicMock, call, patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/ble_scanner.py"
)
SPEC = importlib.util.spec_from_file_location("tater_ble_scanner", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ble_scanner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ble_scanner)


def advertising_packet(*reports: tuple[int, int, bytes, bytes, int]) -> bytes:
    payload = bytearray([0x02, len(reports)])
    for event_type, address_type, address, data, rssi in reports:
        payload.extend((event_type, address_type))
        payload.extend(address)
        payload.append(len(data))
        payload.extend(data)
        payload.extend(struct.pack("b", rssi))
    return bytes([0x04, 0x3E, len(payload)]) + bytes(payload)


class BleScannerTests(unittest.TestCase):
    def test_opens_raw_hci_socket_with_numeric_ioctl_and_libc_bind(self) -> None:
        scanner = ble_scanner.LinuxBleScanner(lambda _payload: None, availability_path=None)
        control_socket = MagicMock()
        control_socket.fileno.return_value = 10
        observer_socket = MagicMock()
        observer_socket.fileno.return_value = 11

        with (
            patch.object(ble_scanner.socket, "socket", side_effect=[control_socket, observer_socket]),
            patch.object(ble_scanner.fcntl, "ioctl") as ioctl,
            patch.object(ble_scanner, "_bind_hci_socket") as bind_hci_socket,
        ):
            opened = scanner._open_socket()

        self.assertIs(opened, observer_socket)
        ioctl.assert_called_once_with(10, ble_scanner._HCIDEVUP, 0)
        bind_hci_socket.assert_called_once_with(observer_socket, 0)
        control_socket.close.assert_called_once_with()
        observer_socket.settimeout.assert_called_once_with(0.25)
        self.assertEqual(
            observer_socket.send.call_args_list,
            [
                call(ble_scanner._hci_command(ble_scanner._OGF_LE_CTL, ble_scanner._OCF_LE_SET_SCAN_ENABLE, b"\x00\x00")),
                call(
                    ble_scanner._hci_command(
                        ble_scanner._OGF_LE_CTL,
                        ble_scanner._OCF_LE_SET_SCAN_PARAMETERS,
                        struct.pack("<BHHBB", 0, 512, 48, 0, 0),
                    )
                ),
                call(ble_scanner._hci_command(ble_scanner._OGF_LE_CTL, ble_scanner._OCF_LE_SET_SCAN_ENABLE, b"\x01\x00")),
            ],
        )

    def test_decodes_legacy_advertising_reports(self) -> None:
        packet = advertising_packet(
            (0, 1, bytes.fromhex("665544332211"), b"\x05\x09Tater", -61),
            (4, 0, bytes.fromhex("ffeeddccbbaa"), b"\x02\x01\x06", -88),
        )

        reports = ble_scanner.parse_le_advertising_reports(packet)

        self.assertEqual(len(reports), 2)
        self.assertEqual(reports[0]["address"], "11:22:33:44:55:66")
        self.assertEqual(reports[0]["address_type"], 1)
        self.assertEqual(reports[0]["rssi"], -61)
        self.assertEqual(reports[0]["data"], b"\x05\x09Tater")
        self.assertEqual(reports[1]["event_type"], 4)

    def test_rejects_truncated_packet_as_a_whole(self) -> None:
        packet = advertising_packet(
            (0, 0, bytes.fromhex("060504030201"), b"\x02\x01\x06", -50),
        )

        self.assertEqual(ble_scanner.parse_le_advertising_reports(packet[:-1]), [])

    def test_batches_match_tater_native_contract_and_dedupe(self) -> None:
        batches = []
        scanner = ble_scanner.LinuxBleScanner(
            batches.append,
            availability_path=None,
        )
        advert = {
            "address": "11:22:33:44:55:66",
            "address_type": 1,
            "rssi": -60,
            "event_type": 0,
            "data": b"\x02\x01\x06",
        }

        self.assertTrue(scanner._ingest_advert(advert, 1000))
        self.assertFalse(scanner._ingest_advert(advert, 1100))
        moved = dict(advert, rssi=-65)
        self.assertTrue(scanner._ingest_advert(moved, 1300))
        self.assertTrue(scanner._flush(1500, force=True))

        self.assertEqual(len(batches), 1)
        payload = batches[0]
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["batch_id"], 1)
        self.assertEqual(payload["device_uptime_ms"], 1500)
        self.assertEqual(
            payload["adverts"],
            [
                {
                    "address": "11:22:33:44:55:66",
                    "address_type": 1,
                    "rssi": -65,
                    "event_type": 0,
                    "data": "020106",
                    "age_ms": 200,
                }
            ],
        )

    def test_batch_and_dedupe_storage_are_bounded(self) -> None:
        scanner = ble_scanner.LinuxBleScanner(lambda _payload: None, availability_path=None)
        for index in range(80):
            address = f"02:00:00:00:{index // 256:02x}:{index % 256:02x}"
            scanner._ingest_advert(
                {
                    "address": address,
                    "address_type": 0,
                    "rssi": -70,
                    "event_type": 0,
                    "data": bytes([index % 256]),
                },
                1000 + index,
            )

        self.assertLessEqual(len(scanner._pending), 24)
        self.assertLessEqual(len(scanner._dedupe), 48)
        self.assertGreater(scanner.status()["adverts_dropped"], 0)


if __name__ == "__main__":
    unittest.main()
