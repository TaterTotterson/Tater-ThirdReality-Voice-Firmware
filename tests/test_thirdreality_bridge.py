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
            self.assertEqual(bridge_module.read_sound_config(config), (0.8, True))

    def test_coerce_bool(self) -> None:
        self.assertFalse(bridge_module.coerce_bool("false"))
        self.assertTrue(bridge_module.coerce_bool("yes"))
        self.assertTrue(bridge_module.coerce_bool(1))

    def test_event_animation(self) -> None:
        self.assertEqual(
            bridge_module.event_animation("thinking"),
            ("tater-thinking.animation", False),
        )
        self.assertEqual(
            bridge_module.event_animation("muted", {"muted": True}),
            ("mics-off_on.animation", True),
        )
        self.assertEqual(
            bridge_module.event_animation("light_command", {"state": False}),
            ("none.animation", True),
        )
        self.assertEqual(
            bridge_module.event_animation("connection", {"status": "connected"}),
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

    def test_s420_led_settings_use_tater_defaults_and_supported_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "settings.json"
            config.write_text(
                json.dumps(
                    {
                        "led_brightness": 65,
                        "led_color": "#FF5A1F",
                        "led_listening_animation": "heartbeat",
                        "led_thinking_animation": "directional",
                    }
                ),
                encoding="utf-8",
            )
            settings = bridge_module.read_led_settings(config)
        self.assertEqual(settings["led_brightness"], 65)
        self.assertEqual(settings["led_color"], "#ff5a1f")
        self.assertEqual(settings["led_listening_animation"], "heartbeat")
        self.assertEqual(settings["led_thinking_animation"], "breathe")

    def test_animation_only_drives_the_visible_s420_status_light(self) -> None:
        content = bridge_module.animation_text("pulse", "#ff5a1f", 80)
        lines = content.strip().splitlines()
        self.assertEqual(lines[0], "loop")
        self.assertGreater(len(lines), 2)
        for line in lines[1:]:
            colors = line.split(":", 1)[1].split(",")
            self.assertEqual(len(colors), 12)
            self.assertNotEqual(colors[0], "000000")
            self.assertEqual(colors[1:], ["000000"] * 11)

    def test_write_tater_animations_creates_all_pipeline_states(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            bridge_module.write_tater_animations(
                dict(bridge_module.TATER_LED_DEFAULTS),
                directory,
            )
            self.assertEqual(
                {path.name for path in directory.iterdir()},
                {
                    "tater-listening.animation",
                    "tater-thinking.animation",
                    "tater-replying.animation",
                },
            )

    def test_unity_sink_volume_is_applied_without_amplification(self) -> None:
        with mock.patch.object(bridge_module.subprocess, "run") as run:
            bridge_module.ensure_unity_sink_volume()
        self.assertEqual(
            run.call_args.args[0],
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "100%"],
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

    async def test_zero_click_dispatch_does_not_open_microphone(self) -> None:
        await self.bridge.dispatch_button(0)
        self.assertEqual(self.websocket.messages, [])

    def test_orphan_release_is_not_a_completed_press(self) -> None:
        self.assertIsNone(bridge_module.completed_press_duration(None, 10.0))

    def test_gpio_bounce_is_not_a_completed_press(self) -> None:
        self.assertIsNone(bridge_module.completed_press_duration(10.0, 10.01))

    def test_normal_press_returns_duration(self) -> None:
        self.assertAlmostEqual(
            bridge_module.completed_press_duration(10.0, 10.25),
            0.25,
        )

    async def test_hardware_registration_names_the_single_status_light(self) -> None:
        with mock.patch.object(bridge_module, "ensure_unity_sink_volume"), mock.patch.object(
            bridge_module, "read_led_settings", return_value=dict(bridge_module.TATER_LED_DEFAULTS)
        ), mock.patch.object(bridge_module, "write_tater_animations"), mock.patch.object(
            bridge_module, "read_sound_config", return_value=(0.8, False)
        ):
            await self.bridge.register_hardware()
        light = next(message for message in self.websocket.messages if message["command"] == "register_light")
        self.assertEqual(light["data"]["name"], "Tater S420 Status Light")
        self.assertNotIn("Ring", light["data"]["name"])


if __name__ == "__main__":
    unittest.main()
