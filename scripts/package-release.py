#!/usr/bin/env python3
"""Create a portable source + Linux x86_64 helper bundle, excluding local state."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent.parent
binary = root / "owly-desktop-helper"
if not binary.is_file():
    raise SystemExit("Build the helper first: bash scripts/build-helper.sh")
names = ["VERSION", "ai_panel.py", "test_ai.py", "owly_tray.py", "install.py", "README.md", "README.txt", "USAGE.md", "LICENSE", "LICENSE.owly",
         "THIRD_PARTY_NOTICES.txt", "owly-desktop-helper", "test_tray.py",
         "test_receiver_protocol.py", "test_send_protocol.py"]
files = [root / name for name in names]
files += [p for folder in ["scripts", "patches", "packaging", "assets"] for p in (root / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
output = root / "dist" / "aibitdrop-linux-x86_64.zip"
output.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in files:
        archive.write(path, Path("aibitdrop") / path.relative_to(root))
print(output)
