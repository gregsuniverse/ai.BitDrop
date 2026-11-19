#!/usr/bin/env python3
"""Bundle each native desktop package with its Owly dependency and instructions."""
import hashlib
from pathlib import Path
import zipfile
root=Path(__file__).resolve().parent.parent
out=root/'dist'; version=(root/'VERSION').read_text().strip()
families=[('fedora',[f'aibitdrop-{version}-1.x86_64.rpm','owly-0.4.2-2.aibitdrop.x86_64.rpm'],'sudo dnf install'),('debian',[f'aibitdrop_{version}-1_amd64.deb','owly_0.4.2-1+aibitdrop1_amd64.deb'],'sudo apt install')]
for _,names,_ in families:
    for name in names:
        if not (out/name).is_file(): raise SystemExit(f'Build {name} first.')
checksums=''.join(hashlib.sha256((out/name).read_bytes()).hexdigest()+'  '+name+'\n' for _,names,_ in families for name in names)
(out/'SHA256SUMS').write_text(checksums)
for family,names,command in families:
    destination=out/f'aibitdrop-{family}-x86_64.zip'
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_STORED) as archive:
        for name in names: archive.write(out/name,name)
        archive.writestr('SHA256SUMS',''.join(line+'\n' for line in checksums.splitlines() if line.split('  ',1)[1] in names))
        for name in ['LICENSE','LICENSE.owly','README.md','USAGE.md']:archive.write(root/name,name)
        archive.writestr('INSTALL.txt',f'ai.BitDrop {version} — MIT licensed\n\nExtract this archive, then run from the extracted folder:\n{command} '+' '.join('./'+n for n in reversed(names))+'\n\nLaunch: aibitdrop\n\nRead README.md for hardware requirements, firewall setup, migration notes and testing limits. These development packages are unsigned.\n')
    print(destination)
