import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReleaseNotesTests(unittest.TestCase):
    def test_renders_highlights_update_paths_and_artifact_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            manifest = temp / "manifest.json"
            output = temp / "RELEASE_NOTES.md"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.2.8",
                        "display_version": "0.2.8",
                        "devices": [
                            {
                                "artifacts": {
                                    "ota": {"size_bytes": 2048, "sha256": "a" * 64},
                                    "factory": {"size_bytes": 4096, "sha256": "b" * 64},
                                }
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "script/render_release_notes.py"),
                    str(manifest),
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            notes = output.read_text(encoding="utf-8")
            self.assertIn("# Tater ThirdReality S420 Firmware 0.2.8", notes)
            self.assertIn("## What's Changed", notes)
            self.assertIn("Adds Tater STT wake verification", notes)
            self.assertIn("signed `ota` artifact", notes)
            self.assertIn("**With Log**", notes)
            self.assertIn("| `ota` | 2.0 KB |", notes)
            self.assertIn(f"`{'a' * 64}`", notes)


if __name__ == "__main__":
    unittest.main()
