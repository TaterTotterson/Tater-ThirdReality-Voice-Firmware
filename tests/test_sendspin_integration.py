"""Structural checks for the ThirdReality Sendspin firmware integration."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "buildroot/package/thirdreality/sendspin-client"


def _check_sendspin_package_is_enabled_and_pinned() -> None:
    defconfig = (ROOT / "buildroot/configs/3reality_trspk_defconfig").read_text()
    package = (PACKAGE / "sendspin-client.mk").read_text()

    assert "BR2_PACKAGE_SENDSPIN_CLIENT=y" in defconfig
    assert "github,Sendspin,sendspin-cpp-cli" in package
    assert "github,Sendspin,sendspin-cpp" in package
    assert "SENDSPIN_CLIENT_VERSION = 05f99441f6a1255a1becf3cf4ab65eead11d63d8" in package
    assert "SENDSPIN_CLIENT_NOISE_C_VERSION" in package
    assert "SENDSPIN_CLI_WITH_PULSE=ON" in package
    assert "BUILD_SHARED_LIBS=OFF" in package
    assert "SENDSPIN_CLI_WITH_MDNS=ON" in package


def _check_opus_disabled_build_does_not_advertise_opus() -> None:
    patch = (PACKAGE / "0002-filter-disabled-opus-from-advertisement.patch").read_text()

    assert "#ifdef SENDSPIN_ENABLE_OPUS" in patch
    assert "std::array<SendspinCodecFormat, 2> CODEC_PREFERENCE" in patch
    assert "SendspinCodecFormat::FLAC, SendspinCodecFormat::PCM" in patch


def _check_legacy_music_assistant_noise_handshake_is_accepted() -> None:
    patch = (
        PACKAGE / "0003-accept-legacy-noise-handshake-without-psk-category.patch"
    ).read_text()

    assert "aiosendspin 9.1.1" in patch
    assert "psk_category_code.empty()" in patch
    assert "PskCategory::LONG_TERM" in patch
    assert "PskCategory::PAIRING" in patch
    assert "PskCategory::SENTINEL" in patch
    assert "explicit unknown category remains malformed" in patch


def _check_runtime_exposes_full_sendspin_player() -> None:
    wrapper = (PACKAGE / "files/tater-sendspin").read_text()
    supervisor = (
        ROOT
        / "buildroot/package/thirdreality/tater-s420-firmware/script/S99tater-satellite"
    ).read_text()

    assert "--allow-unpaired" in wrapper
    assert "--port 8928" in wrapper
    assert "--output pulse" in wrapper
    assert "--audio-format pcm:48000:16:2,flac:48000:16:2" in wrapper
    assert "--mdns-name" in wrapper
    assert "TATER_SENDSPIN_OUTPUT_CHANNEL" in wrapper
    assert "--no-config" not in wrapper
    assert "start_sendspin" in supervisor
    assert "sendspin|voice-assistant" in supervisor


def _check_stereo_pair_routing_is_applied_in_pulse_sink() -> None:
    patch = (PACKAGE / "0001-add-tater-output-channel-routing.patch").read_text()

    assert "OutputChannel::Left" in patch
    assert "OutputChannel::Right" in patch
    assert "OutputChannel::Mono" in patch
    assert "TATER_SENDSPIN_OUTPUT_CHANNEL" in patch
    assert "return {{48000}, {16}, {2}};" in patch


def _check_tater_runtime_no_longer_advertises_legacy_media_sync() -> None:
    runtime = (
        ROOT
        / "buildroot/package/thirdreality/tater-linux-satellite/files/tater_features.py"
    ).read_text()

    assert '"sendspin_player": True' in runtime
    assert '"synchronized_media_sessions"' not in runtime
    assert '"audio_session_version"' not in runtime
    assert "def _start_media(" not in runtime
    assert "def _prepare_media(" not in runtime
    assert "def _commit_media(" not in runtime


class SendspinIntegrationTests(unittest.TestCase):
    def test_sendspin_package_is_enabled_and_pinned(self) -> None:
        _check_sendspin_package_is_enabled_and_pinned()

    def test_runtime_exposes_full_sendspin_player(self) -> None:
        _check_runtime_exposes_full_sendspin_player()

    def test_opus_disabled_build_does_not_advertise_opus(self) -> None:
        _check_opus_disabled_build_does_not_advertise_opus()

    def test_legacy_music_assistant_noise_handshake_is_accepted(self) -> None:
        _check_legacy_music_assistant_noise_handshake_is_accepted()

    def test_stereo_pair_routing_is_applied_in_pulse_sink(self) -> None:
        _check_stereo_pair_routing_is_applied_in_pulse_sink()

    def test_tater_runtime_no_longer_advertises_legacy_media_sync(self) -> None:
        _check_tater_runtime_no_longer_advertises_legacy_media_sync()


if __name__ == "__main__":
    unittest.main()
