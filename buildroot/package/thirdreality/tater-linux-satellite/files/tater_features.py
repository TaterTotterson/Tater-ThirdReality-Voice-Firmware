"""S420 provisioning, signed OTA and player supervision hooks."""

from . import shared_features as shared
import asyncio
import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

_LOGGER = shared._LOGGER
_OTA_PATH = Path("/data/software.swu")
_SWUPDATE_KEY = Path("/etc/swupdate-public.pem")
_OTA_MAX_BYTES = 192 * 1024 * 1024
_WAKE_SHA256 = shared._WAKE_SHA256
_validated_web_url = shared._validated_web_url

# S420 paths are supplied here; the shared runtime remains XDG-compatible.
shared._SETTINGS_PATH = Path("/data/conf/tater-live-settings.json")
shared._OWW_SHARED_DIR = Path("/usr/share/tater/openwakeword")
shared._OWW_BUILTIN_BUNDLE = shared._OWW_SHARED_DIR / "hey_tater.wake-bundle.json"
shared._OWW_BUILTIN_MODEL = shared._OWW_SHARED_DIR / "hey_tater.oww.onnx"
shared._NWW_BUILTIN_MODELS = {
    key: shared._OWW_SHARED_DIR / f"hey_tater.nww.{key}.onnx" for key in ("cnn", "gru")
}
shared._TATER_WAKE_SOUND_DIR = Path(__file__).resolve().parents[1] / "sounds"


class TaterFeatureManager(shared.TaterFeatureManager):
    def __init__(self, client):
        client.state.tater_playback_reference_aec = True
        super().__init__(client)
        if hasattr(client, "capabilities"):
            client.capabilities.pop("persistent_media_sessions", None)
            client.capabilities.pop("audio_session_version", None)
        if hasattr(client, "sendspin"):
            client.sendspin.external = True
            client.sendspin.available = True
            client.sendspin.marker = Path("/tmp/tater-sendspin-playing")
            client.sendspin.app_name = "Tater-Sendspin"
            client.sendspin.output_channel_mode = str(
                self.settings.get("output_channel_mode") or "stereo"
            )
        self.capabilities.update(
            ota=True,
            setup_mode=True,
            status_led=True,
            openwakeword=True,
            nanowakeword=True,
            nanowakeword_architectures=["cnn", "gru"],
            playback_reference_aec=True,
            wake_during_playback=True,
            barge_in=True,
            sendspin_player=True,
            sendspin_version=1,
            sendspin_output_channel_selection=True,
            sendspin_output_channel_modes=["stereo", "left", "right", "mono"],
        )

    def _load_settings(self):
        try:
            legacy = shared.json.loads(shared._SETTINGS_PATH.read_text())
        except (OSError, ValueError):
            legacy = {}
        return {**legacy, **dict(getattr(self.state, "native_settings", {}) or {})}

    def _save_settings(self):
        super()._save_settings()
        shared._SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        shared._write_bytes_atomic(
            shared._SETTINGS_PATH,
            (shared.json.dumps(self.settings, indent=2) + "\n").encode(),
        )
        if hasattr(self.client, "sendspin"):
            self.client.sendspin.output_channel_mode = str(
                self.settings.get("output_channel_mode") or "stereo"
            )

    def handle_message(self, body):
        if str(body.get("type") or "") in shared._RETIRED_MEDIA_MESSAGES:
            return True
        return super().handle_message(body)

    def connected(self):
        # Restore pre-shared-runtime settings as well as preferences on upgrade.
        self._apply_settings(self.settings, persist=False)

    @staticmethod
    def _restart_sendspin():
        subprocess.Popen(
            ["/etc/init.d/S99tater-satellite", "sendspin", "restart"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    async def _reset_setup(self) -> None:
        self._send(
            "log",
            {
                "level": "warn",
                "message": "Setup reset requested by Tater; rebooting into setup mode.",
            },
        )
        await asyncio.sleep(0.25)
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/tater-provisioning", "reset"
        )
        await process.wait()

    async def _run_ota(self, payload: dict[str, Any]) -> None:
        url = str(payload.get("url") or "").strip()
        if not url:
            self._send(
                "ota.status",
                {"status": "error", "progress": 0, "message": "Update URL is missing."},
            )
            return
        try:
            expected_sha256 = str(payload.get("sha256") or "").strip().lower()
            if expected_sha256 and not _WAKE_SHA256.fullmatch(expected_sha256):
                raise ValueError("Update SHA-256 is invalid.")
            expected_size = int(payload.get("size_bytes") or 0)
            if expected_size < 0 or expected_size > _OTA_MAX_BYTES:
                raise ValueError("Update size is outside the supported S420 range.")
            self._send(
                "ota.status",
                {
                    "status": "downloading",
                    "progress": 0,
                    "message": "Downloading signed Tater firmware.",
                },
            )
            digest = await asyncio.to_thread(
                self._download_ota,
                url,
                expected_sha256=expected_sha256,
                expected_size=expected_size,
            )
            self._send(
                "ota.status",
                {
                    "status": "rebooting",
                    "progress": 92,
                    "message": f"Verified signed firmware ({digest[:12]}); rebooting into the recovery installer.",
                },
            )
            process = await asyncio.create_subprocess_exec(
                "/usr/bin/swupdate",
                "-G",
                "-k",
                str(_SWUPDATE_KEY),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output, _ = await process.communicate()
            if process.returncode != 0:
                message = output.decode("utf-8", errors="replace").strip()[-300:]
                raise RuntimeError(
                    message or f"swupdate exited with {process.returncode}"
                )
            # The vendor -G mode normally reboots before returning. If reboot
            # was delayed or rejected, explicitly request it after recovery was
            # armed. Recovery verifies the SWUpdate signature before writing.
            await asyncio.sleep(1.0)
            subprocess.Popen(
                ["/sbin/reboot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.exception("Tater OTA failed")
            self._send(
                "ota.status",
                {
                    "status": "error",
                    "progress": 0,
                    "message": str(exc) or type(exc).__name__,
                },
            )

    def _download_ota(
        self, url: str, *, expected_sha256: str = "", expected_size: int = 0
    ) -> str:
        url = _validated_web_url(url, label="firmware URL")
        _OTA_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = _OTA_PATH.with_suffix(".swu.part")
        digest = hashlib.sha256()
        request = Request(url, headers={"User-Agent": "Tater-S420/0.2.0"})
        received = 0
        try:
            with (
                urlopen(request, timeout=60) as response,
                temporary.open("wb") as output,
            ):
                content_length = int(response.headers.get("Content-Length") or 0)
                if content_length > _OTA_MAX_BYTES:
                    raise ValueError("Update is too large for the S420 data partition.")
                if expected_size and content_length and content_length != expected_size:
                    raise ValueError(
                        "Update Content-Length does not match the release manifest."
                    )
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > _OTA_MAX_BYTES:
                        raise ValueError(
                            "Update is too large for the S420 data partition."
                        )
                    output.write(chunk)
                    digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
            actual_sha256 = digest.hexdigest()
            if expected_size and received != expected_size:
                raise ValueError(
                    "Downloaded update size does not match the release manifest."
                )
            if expected_sha256 and actual_sha256 != expected_sha256:
                raise ValueError(
                    "Downloaded update SHA-256 does not match the release manifest."
                )
            os.replace(temporary, _OTA_PATH)
            return actual_sha256
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
