#!/usr/bin/env python3
"""Build native desktop packages without installing anything. Requires built helper.
Pass --owly-source PATH to also package the pinned, compiled Owly backend.
Build on the target distro for compatible native libraries; generated Debian
packages compute their libc floor from ELF requirements rather than assuming one.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
VERSION = (ROOT/'VERSION').read_text().strip()

def run(*args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)

def copy(source, dest, mode=0o644):
    dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, dest); dest.chmod(mode)

def write(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(data); path.chmod(mode)

def libc_floor(files):
    versions=[]
    for path in files:
        output=subprocess.check_output(['readelf','--version-info',str(path)],text=True)
        versions += [tuple(map(int,v.split('.'))) for v in re.findall(r'Name: GLIBC_(\d+(?:\.\d+)+)',output)]
    return '.'.join(map(str,max(versions)))

def deb(stage, name, version, depends, output, tool):
    write(stage/'DEBIAN/control', f'''Package: {name}
Version: {version}
Architecture: amd64
Maintainer: Greg O'Rourke <gresphysics@gmail.com>
Section: net
Priority: optional
Depends: {depends}
Homepage: https://github.com/gregsuniverse/ai.BitDrop
Description: {'Nearby file transfer desktop app with optional AI analysis' if name=='aibitdrop' else 'Owly AWDL radio service and CLI'}
 Packaged for ai.BitDrop. Requires a supported Wi-Fi adapter and a desktop session.
''')
    run(tool,'--root-owner-group','-Zxz','--build',stage,output/f'{name}_{version}_amd64.deb')

def rpm(stage, spec, output, tool, work, defines=()):
    top=work/'rpmbuild'
    temporary=work/'tmp'; temporary.mkdir(parents=True, exist_ok=True)
    run(tool,'-bb','--quiet','--define',f'_topdir {top}','--define',f'_tmppath {temporary}',*defines,spec)
    for file in (top/'RPMS').rglob('*.rpm'): shutil.copy2(file,output/file.name)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('format', choices=['rpm','deb','all'])
    parser.add_argument('--rpmbuild', default='rpmbuild'); parser.add_argument('--dpkg-deb',default='dpkg-deb')
    parser.add_argument('--owly-source',type=Path)
    args=parser.parse_args()
    if os.uname().machine!='x86_64': raise SystemExit('This initial package recipe supports x86_64 only.')
    helper=ROOT/'owly-desktop-helper'
    if not helper.is_file(): raise SystemExit('Run scripts/build-helper.sh first.')
    output=ROOT/'dist'; output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='aibitdrop-package-') as temporary:
        work=Path(temporary); stage=work/'desktop'; lib=stage/'usr/libexec/aibitdrop'
        for name in ['owly_tray.py','ai_panel.py']: copy(ROOT/name,lib/name)
        copy(helper,lib/helper.name,0o755)
        shutil.copytree(ROOT/'assets',lib/'assets')
        shutil.copytree(ROOT/'assets/icons',stage/'usr/share/icons/hicolor')
        write(stage/'usr/bin/aibitdrop','#!/bin/sh\nexec /usr/bin/python3 /usr/libexec/aibitdrop/owly_tray.py "$@"\n',0o755)
        copy(ROOT/'packaging/setup-firewall.sh',stage/'usr/bin/aibitdrop-setup-firewall',0o755)
        write(stage/'usr/share/applications/owly-tray.desktop','''[Desktop Entry]
Type=Application
Name=ai.BitDrop
Comment=Nearby file transfers with optional AI analysis
Exec=aibitdrop
Icon=aibitdrop
Terminal=false
Categories=Network;FileTransfer;
Keywords=AirDrop;Owly;iPhone;AI;
''')
        for name in ['LICENSE','LICENSE.owly']: copy(ROOT/name,stage/'usr/share/licenses/aibitdrop'/name)
        for name in ['README.md','THIRD_PARTY_NOTICES.txt']: copy(ROOT/name,stage/'usr/share/doc/aibitdrop'/name)
        if args.format in ['rpm','all']:
            rpm(stage,ROOT/'packaging/aibitdrop.spec',output,args.rpmbuild,work/'app-rpm', ['--define',f'aibitdrop_stage {stage}','--define',f'aibitdrop_version {VERSION}'])
        if args.format in ['deb','all']:
            # Debian copyright convention, in addition to full license texts.
            copy(ROOT/'LICENSE',stage/'usr/share/doc/aibitdrop/copyright')
            depends=f'libc6 (>= {libc_floor([helper])}), libgcc-s1, python3, python3-pyside6.qtwidgets, python3-pyside6.qtnetwork, python3-dbus, python3-gi, gir1.2-glib-2.0, owly (>= 0.4.2)'
            deb(stage,'aibitdrop',VERSION+'-1',depends,output,args.dpkg_deb)
        if args.owly_source:
            source=args.owly_source.resolve()
            if not (source/'target/release/owlyd').is_file(): raise SystemExit('Compile owlyd in the provided source tree first.')
            for fmt in (['rpm','deb'] if args.format=='all' else [args.format]):
                backend=work/f'backend-{fmt}'
                env=os.environ.copy()
                for variable in ['PREFIX','BINDIR','LIBDIR','LIBEXECDIR','DATADIR','LICENSEDIR','DOCDIR','TARGET']: env.pop(variable,None)
                env.update(DESTDIR=str(backend),TARGET=str(source/'target'))
                if fmt=='rpm':env['LIBEXECDIR']='/usr/libexec'
                run(source/'packaging/install.sh','owly',env=env)
                if fmt=='rpm':
                    paths=subprocess.check_output([str(source/'packaging/install.sh'),'--list','owly'],env=env,text=True).splitlines()
                    dirs=sorted({str(Path(p).parent) for p in paths if Path(p).parent.name=='owly'})
                    filelist=work/'backend-files';filelist.write_text('\n'.join(['%dir '+p for p in dirs]+paths)+'\n')
                    rpm(backend,source/'packaging/rpm/owly.spec',output,args.rpmbuild,work/'backend-build-rpm', ['--define','owly_version 0.4.2','--define','owly_release 2.aibitdrop','--define',f'owly_stage {backend}','--define',f'owly_files {filelist}'])
                else:
                    for name in ['postinst','prerm','postrm']: copy(source/'packaging/deb'/name,backend/'DEBIAN'/name,0o755)
                    binaries=[source/'target/release/owlyd',source/'target/release/owly']
                    floor=libc_floor(binaries)
                    deb(backend,'owly','0.4.2-1+aibitdrop1',f'libc6 (>= {floor}), libgcc-s1, dbus, systemd, polkitd, network-manager, iproute2, iputils-ping, mount',output,args.dpkg_deb)
    print(f'Packages written to {output}')
if __name__=='__main__':main()
