#!/usr/bin/env python3
"""Local-only captive portal for first-boot Tater provisioning."""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs


WPA_CONFIG = Path(os.environ.get("TATER_WPA_CONFIG", "/etc/wpa_supplicant.conf"))
TATER_CONFIG = Path(os.environ.get("TATER_CONFIG", "/data/conf/tater.json"))
DEFAULT_TATER_CONFIG = Path(
    os.environ.get("TATER_DEFAULT_CONFIG", "/usr/share/tater/defaults/tater.json")
)
TOKEN_FILE = Path(os.environ.get("TATER_TOKEN_FILE", "/data/conf/tater-device-token"))
MAX_REQUEST_BYTES = 8192

CAPTIVE_PATHS = {
    "/",
    "/canonical.html",
    "/connecttest.txt",
    "/generate_204",
    "/gen_204",
    "/hotspot-detect.html",
    "/ncsi.txt",
    "/redirect",
    "/success.txt",
}

PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Tater Satellite Setup</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    body { margin: 0; background: radial-gradient(circle at 50% -10%, #3b2416, #0b0f10 44%); color: #f4f1e9; }
    main { max-width: 34rem; margin: auto; padding: 2rem 1.2rem 3rem; }
    h1 { margin-bottom: .25rem; color: #ffc07f; }
    p { color: #cbd7cb; line-height: 1.45; }
    form { display: grid; gap: 1rem; margin-top: 1.5rem; }
    label { display: grid; gap: .35rem; font-weight: 650; }
    small { color: #9cab9d; font-weight: 400; }
    input { box-sizing: border-box; width: 100%; padding: .8rem; border: 1px solid #38464b;
      border-radius: .55rem; background: #0f1416; color: white; font: inherit; }
    input:focus { outline: 2px solid #ffc07f; border-color: transparent; }
    button { padding: .9rem; border: 0; border-radius: .55rem;
      background: linear-gradient(135deg, #ff8a2a, #ffc07f);
      color: #1d0e03; font: inherit; font-weight: 800; cursor: pointer; }
    .notice { padding: .85rem; border-left: .25rem solid #ff8a2a; background: #192023; }
  </style>
</head>
<body><main>
  <small>TATER NATIVE</small><h1>Tater Satellite Setup</h1>
  <p>Connect this speaker to Wi-Fi and your Tater server. Everything entered here
     stays on the speaker; this setup hotspot has no internet route.</p>
  <p class="notice">The setup network is intentionally open and is available only
     during first setup or after a physical setup reset.</p>
  <form method="post" action="/save" autocomplete="off">
    <label>Wi-Fi network name
      <input name="ssid" maxlength="32" required autocapitalize="none">
    </label>
    <label>Wi-Fi password
      <input name="wifi_password" type="password" maxlength="63">
      <small>Leave blank only for an open Wi-Fi network.</small>
    </label>
    <label>Tater server
      <input name="tater_server" maxlength="255" required placeholder="http://tater.local:8080" autocapitalize="none">
    </label>
    <label>Pairing code or API token
      <input name="pairing_code" type="password" maxlength="512" required>
    </label>
    <label>Room <small>Optional</small>
      <input name="room" maxlength="80" placeholder="Kitchen">
    </label>
    <label>Speaker name <small>Optional</small>
      <input name="name" maxlength="80" placeholder="Kitchen Tater">
    </label>
    <button type="submit">Save and restart</button>
  </form>
</main></body></html>"""


def _reject_controls(value: str, label: str) -> None:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{label} contains unsupported control characters")


def validate_fields(fields: dict[str, str]) -> dict[str, str]:
    values = {
        "ssid": fields.get("ssid", "").strip(),
        "wifi_password": fields.get("wifi_password", ""),
        "tater_server": fields.get("tater_server", "").strip(),
        "pairing_code": fields.get("pairing_code", "").strip(),
        "room": fields.get("room", "").strip(),
        "name": fields.get("name", "").strip(),
    }

    for key, label in (
        ("ssid", "Wi-Fi network name"),
        ("wifi_password", "Wi-Fi password"),
        ("tater_server", "Tater server"),
        ("pairing_code", "Pairing code"),
        ("room", "Room"),
        ("name", "Speaker name"),
    ):
        _reject_controls(values[key], label)

    ssid_bytes = len(values["ssid"].encode("utf-8"))
    if not 1 <= ssid_bytes <= 32:
        raise ValueError("Wi-Fi network name must be 1 to 32 bytes")

    password_bytes = len(values["wifi_password"].encode("utf-8"))
    if password_bytes and not 8 <= password_bytes <= 63:
        raise ValueError("Wi-Fi password must be blank or 8 to 63 bytes")

    if not values["tater_server"] or len(values["tater_server"].encode("utf-8")) > 255:
        raise ValueError("Tater server is required and must be at most 255 bytes")
    if any(character.isspace() for character in values["tater_server"]):
        raise ValueError("Tater server must not contain spaces")
    if "://" in values["tater_server"] and not values["tater_server"].lower().startswith(
        ("http://", "https://", "ws://", "wss://")
    ):
        raise ValueError("Tater server must use HTTP(S), WS(S), or a host and port")
    if not values["pairing_code"] or len(values["pairing_code"].encode("utf-8")) > 512:
        raise ValueError("Pairing code or API token is required")
    if len(values["room"].encode("utf-8")) > 80:
        raise ValueError("Room must be at most 80 bytes")
    if len(values["name"].encode("utf-8")) > 80:
        raise ValueError("Speaker name must be at most 80 bytes")
    return values


def _wpa_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_wpa_config(ssid: str, password: str) -> str:
    lines = [
        "ctrl_interface=/var/run/wpa_supplicant",
        "ap_scan=1",
        "update_config=1",
        "",
        "network={",
        f'    ssid="{_wpa_quote(ssid)}"',
        "    scan_ssid=1",
    ]
    if password:
        lines.append(f'    psk="{_wpa_quote(password)}"')
    else:
        lines.append("    key_mgmt=NONE")
    lines.extend(["}", ""])
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def save_configuration(
    fields: dict[str, str],
    *,
    wpa_path: Path = WPA_CONFIG,
    tater_path: Path = TATER_CONFIG,
    default_tater_path: Path = DEFAULT_TATER_CONFIG,
    token_path: Path = TOKEN_FILE,
) -> dict[str, str]:
    values = validate_fields(fields)
    config = _read_json(default_tater_path)
    config.update(_read_json(tater_path))
    config.update(
        {
            "server_url": values["tater_server"],
            "pairing_code": values["pairing_code"],
            "room": values["room"],
            "name": values["name"],
        }
    )

    _atomic_write(wpa_path, render_wpa_config(values["ssid"], values["wifi_password"]))
    _atomic_write(tater_path, json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    try:
        token_path.unlink()
    except FileNotFoundError:
        pass
    os.sync()
    return values


def _reboot() -> None:
    time.sleep(2)
    subprocess.run(["/bin/sync"], check=False)
    subprocess.run(["/sbin/reboot"], check=False)


class ProvisioningHandler(BaseHTTPRequestHandler):
    server_version = "TaterSetup/1.0"

    def _send_html(self, status: HTTPStatus, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'",
        )
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.split("?", 1)[0] in CAPTIVE_PATHS:
            self._send_html(HTTPStatus.OK, PAGE)
            return
        self._send_html(HTTPStatus.OK, PAGE)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.split("?", 1)[0] != "/save":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return

        try:
            raw_fields = parse_qs(
                self.rfile.read(length).decode("utf-8"),
                keep_blank_values=True,
                strict_parsing=True,
            )
            fields = {key: values[-1] for key, values in raw_fields.items()}
            save_configuration(fields)
        except (UnicodeDecodeError, ValueError, OSError) as error:
            escaped = html.escape(str(error))
            self._send_html(
                HTTPStatus.BAD_REQUEST,
                f"<h1>Setup was not saved</h1><p>{escaped}</p><p><a href='/'>Try again</a></p>",
            )
            return

        self._send_html(
            HTTPStatus.OK,
            "<h1>Setup saved</h1><p>The speaker is restarting and will join your Wi-Fi network.</p>",
        )
        threading.Thread(target=_reboot, daemon=True).start()

    def log_message(self, message: str, *args: object) -> None:
        # Do not log request bodies or form values. Keep only standard request metadata.
        print(f"tater-provisioning: {self.address_string()} - {message % args}")


def main() -> None:
    bind_address = os.environ.get("TATER_PROVISIONING_BIND", "192.168.4.1")
    port = int(os.environ.get("TATER_PROVISIONING_PORT", "80"))
    server = ThreadingHTTPServer((bind_address, port), ProvisioningHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
