#!/usr/bin/python3
"""Install this user-owned desktop app without changing the system Owly RPM."""
from pathlib import Path
import shutil
import os
import sys
import time

here = Path(__file__).resolve().parent
home = Path.home()
dest = home/".local/share/owly-tray"
state = home/".local/state/owly-tray"
applications = home/".local/share/applications"
autostart = home/".config/autostart"
binary_dir = home/".local/bin"
for p in (dest,state,applications,autostart,binary_dir,home/".config/OwlyTray"):
    p.mkdir(parents=True, exist_ok=True)
backup = state/"backups"/time.strftime("%Y%m%d-%H%M%S")
backup.mkdir(parents=True)
for p in [dest/"owly_tray.py",dest/"owly-desktop-helper",applications/"owly-receive.desktop",
    applications/"owly-tray.desktop",autostart/"owly-tray.desktop",binary_dir/"receive-airdrop"]:
    if p.exists(): shutil.copy2(p,backup/p.name)
for name in ("owly_tray.py","ai_panel.py","file_safety.py","owly-desktop-helper","LICENSE","LICENSE.owly","README.txt","USAGE.md"):
    shutil.copy2(here/name,dest/name)
shutil.copytree(here/"assets",dest/"assets",dirs_exist_ok=True)
shutil.copytree(here/"assets/icons",home/".local/share/icons/hicolor",dirs_exist_ok=True)
os.chmod(dest/"owly-desktop-helper",0o755)
wrapper = f'#!/usr/bin/bash\nexec /usr/bin/python3 "{dest}/owly_tray.py" "$@"\n'
for name in ("aibitdrop","owly-tray","receive-airdrop"):
    p=binary_dir/name;p.write_text(wrapper);p.chmod(0o755)
sys.path.insert(0,str(here))
import owly_tray
owly_tray.INSTALL = dest
desktop_entry = owly_tray.desktop_entry
(applications/"owly-tray.desktop").write_text(desktop_entry())
(autostart/"owly-tray.desktop").write_text(desktop_entry())
# Replace the previous terminal launcher, keeping its backup.
(applications/"owly-receive.desktop").unlink(missing_ok=True)
print(f"Installed in {dest}")
print(f"Previous launchers backed up to {backup}")
