from __future__ import annotations

import importlib.util
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "buildroot/package/thirdreality/tater-linux-satellite/files/ble_enrollment.py"
)
SPEC = importlib.util.spec_from_file_location("thirdreality_ble_enrollment", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ble_enrollment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ble_enrollment)


class BleEnrollmentTests(unittest.TestCase):
    def test_reads_only_valid_identity_resolving_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            info = Path(directory) / "info"
            info.write_text(
                "[General]\nName=My Watch\n"
                "[LongTermKey]\nKey=ffffffffffffffffffffffffffffffff\n"
                "[IdentityResolvingKey]\nKey=00112233445566778899AABBCCDDEEFF\n",
                encoding="utf-8",
            )
            self.assertEqual(
                ble_enrollment.read_identity_key(info),
                "00112233445566778899aabbccddeeff",
            )

    def test_rejects_missing_or_malformed_identity_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            info = Path(directory) / "info"
            info.write_text("[IdentityResolvingKey]\nKey=not-a-key\n", encoding="utf-8")
            self.assertEqual(ble_enrollment.read_identity_key(info), "")

    def test_controller_script_answers_bluez_gatt_prompts(self) -> None:
        enrollment = ble_enrollment.LinuxBleEnrollment(lambda *_: None, object())
        commands = []
        with (
            patch.object(
                enrollment,
                "_write_command",
                side_effect=lambda _process, command, **_kwargs: commands.append(command),
            ),
            patch.object(enrollment, "_wait_for_output"),
        ):
            enrollment._configure_controller(
                object(),
                queue.Queue(),
                "Tater Enroll 1234",
                90,
            )

        self.assertEqual(
            ["/usr/bin/bluetoothctl", "--agent", "NoInputNoOutput"],
            enrollment._bluetoothctl_command("/usr/bin/bluetoothctl"),
        )
        self.assertIn('system-alias "Tater Enroll 1234"', commands)
        self.assertIn('name "Tater Enroll 1234"', commands)
        self.assertIn("discoverable off", commands)
        self.assertNotIn("agent NoInputNoOutput", commands)
        service_index = commands.index("register-service 180d")
        self.assertEqual("yes", commands[service_index + 1])
        location_index = commands.index("register-characteristic 2a38 read")
        self.assertEqual("00", commands[location_index + 1])
        measurement_index = commands.index("register-characteristic 2a37 notify")
        self.assertEqual("00 48", commands[measurement_index + 1])
        self.assertEqual("register-application", commands[measurement_index + 2])

    def test_bluez_setup_errors_are_not_reported_as_advertising(self) -> None:
        enrollment = ble_enrollment.LinuxBleEnrollment(lambda *_: None, object())
        output = queue.Queue()
        output.put("Failed to register advertisement: org.bluez.Error.Failed")
        process = Mock()
        process.poll.return_value = None

        with self.assertRaisesRegex(RuntimeError, "register the advertisement"):
            enrollment._wait_for_output(
                process,
                output,
                "Advertising object registered",
                "register the advertisement",
            )


if __name__ == "__main__":
    unittest.main()
