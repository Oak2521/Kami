"""Offline integration checks for the OFL recovery shell, no system font writes."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASH = os.environ.get("KAMI_TEST_BASH") or shutil.which("bash")


class FontRecoveryTests(unittest.TestCase):
    def prepare(self, directory, success):
        root = Path(directory)
        scripts = root / "skill/scripts"
        fonts = root / "skill/assets/fonts"
        scripts.mkdir(parents=True)
        fonts.mkdir(parents=True)
        shutil.copyfile(ROOT / "skills/kami/scripts/ensure-fonts.sh", scripts / "ensure-fonts.sh")
        shutil.copyfile(ROOT / "skills/kami/assets/fonts/SourceHanSerif-LICENSE.txt", fonts / "SourceHanSerif-LICENSE.txt")
        # Existing Korean fonts are reusable and should not trigger a download.
        for name in ("SourceHanSerifKR-Regular.otf", "SourceHanSerifKR-Medium.otf"):
            with (fonts / name).open("wb") as handle:
                handle.truncate(7_000_000)
        bins = root / "bin"
        bins.mkdir()
        curl = bins / "curl"
        curl.write_text("""#!/usr/bin/env bash
set -eu
output=''
for arg in "$@"; do
  case "$arg" in https://*) printf '%s\n' "$arg" >> "$FONT_TEST_REQUESTS" ;; esac
done
while [ "$#" -gt 0 ]; do
  if [ "$1" = '-o' ]; then output="$2"; shift; fi
  shift
done
""" + ("head -c 21000000 /dev/zero > \"$output\"\n" if success else "exit 1\n"), encoding="utf-8", newline="\n")
        curl.chmod(0o755)
        return root, scripts, bins

    def run_recovery(self, directory, success):
        root, scripts, bins = self.prepare(directory, success)
        env = os.environ.copy()
        env.update(KAMI_FONT_DIR=str(root / "recovered"), FONT_TEST_REQUESTS=str(root / "requests.txt"),
                   FONT_TEST_BIN=str(bins))
        result = subprocess.run([BASH, "-c", 'export PATH="$(cygpath -u "$FONT_TEST_BIN" 2>/dev/null || printf "%s" "$FONT_TEST_BIN"):$PATH"; exec bash "$1"',
                                 "font-test", str(scripts / "ensure-fonts.sh")], env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        return root, result

    def test_only_pinned_ofl_fonts_downloaded_and_license_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root, result = self.run_recovery(directory, True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            calls = (root / "requests.txt").read_text()
            self.assertNotIn("tsanger", calls.lower())
            self.assertIn("7889f11bf31170b5d092a083b357c8c8130f89e0", calls)
            for weight in ("Regular", "Medium"):
                self.assertGreater((root / "recovered" / f"SourceHanSerifSC-{weight}.otf").stat().st_size, 20_000_000)
            self.assertIn("SIL Open Font License", (root / "recovered/SourceHanSerif-LICENSE.txt").read_text())

    def test_failed_download_does_not_claim_ready_or_leave_partial_fonts(self):
        with tempfile.TemporaryDirectory() as directory:
            root, result = self.run_recovery(directory, False)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("OK: all fonts ready", result.stdout)
            self.assertFalse(list((root / "recovered").glob("*.otf")))
            self.assertFalse(list((root / "recovered").glob("*.tmp.*")))


if __name__ == "__main__":
    unittest.main()
