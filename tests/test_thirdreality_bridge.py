import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


BRIDGE_PATH = (
    Path(__file__).parents[1]
    / "buildroot/package/thirdreality/tater-linux-satellite/files/tater-thirdreality-bridge.py"
)
SPEC = importlib.util.spec_from_file_location("tater_thirdreality_bridge", BRIDGE_PATH)
assert SPEC is not None and SPEC.loader is not None
bridge_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge_module)


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages = []

    async def send(self, message: str) -> None:
        self.messages.append(json.loads(message))


class BridgeHelpersTest(unittest.TestCase):
    def test_clamp_volume(self) -> None:
        self.assertEqual(bridge_module.clamp_volume(-1), 0.0)
        self.assertEqual(bridge_module.clamp_volume(2), 1.0)
        self.assertEqual(bridge_module.clamp_volume("0.25"), 0.25)
        self.assertEqual(bridge_module.clamp_volume("bad"), 0.5)

    def test_read_sound_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "sound.json"
            config.write_text('{"volume": 65, "mic_mute": 0}', encoding="utf-8")
            self.assertEqual(bridge_module.read_sound_config(config), (0.65, True))

    def test_read_sound_config_handles_malformed_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "sound.json"
            config.write_text('{"volume": "loud", "mic_mute": "false"}', encoding="utf-8")
            self.assertEqual(bridge_module.read_sound_config(config), (0.5, True))

    def test_coerce_bool(self) -> None:
        self.assertFalse(bridge_module.coerce_bool("false"))
        self.assertTrue(bridge_module.coerce_bool("yes"))
        self.assertTrue(bridge_module.coerce_bool(1))

    def test_event_animation(self) -> None:
        self.assertEqual(
            bridge_module.event_animation("thinking"),
            ("active-thinking.animation", False),
        )
        self.assertEqual(
            bridge_module.event_animation("muted", {"muted": True}),
            ("mics-off_on.animation", True),
        )
        self.assertEqual(
            bridge_module.event_animation("light_command", {"state": False}),
            ("none.animation", True),
        )

    def test_atomic_update_preserves_vendor_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            config = directory / "sound.json"
            config.write_text('{"volume": 25, "mic_gain": 30}', encoding="utf-8")
            with mock.patch.object(bridge_module, "SOUND_LOCK", directory / "lock"):
                bridge_module._atomic_sound_update({"mic_mute": 0}, config)
            self.assertEqual(
                json.loads(config.read_text(encoding="utf-8")),
                {"volume": 25, "mic_gain": 30, "mic_mute": 0},
            )


class BridgeButtonTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bridge = bridge_module.ThirdRealityBridge()
        self.websocket = FakeWebSocket()
        self.bridge.websocket = self.websocket

    async def test_single_press_starts_listening(self) -> None:
        await self.bridge.dispatch_button(1)
        self.assertEqual(
            [message["command"] for message in self.websocket.messages],
            ["button_single_press", "start_listening"],
        )

    async def test_single_press_stops_active_pipeline(self) -> None:
        self.bridge.pipeline_active = True
        await self.bridge.dispatch_button(1)
        self.assertEqual(
            [message["command"] for message in self.websocket.messages],
            ["button_single_press", "stop_pipeline"],
        )


if __name__ == "__main__":
    unittest.main()
