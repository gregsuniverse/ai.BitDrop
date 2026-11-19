"""Local file checks. Type detection is heuristic, never proof of authenticity."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import zipfile

STATE = Path.home()/'.local/state/owly-tray/security'
LOCK = threading.RLock()
MAX_SIZE = 512*1024*1024
TYPES = {
 '.pdf': {'application/pdf'}, '.png': {'image/png'},
 '.jpg': {'image/jpeg'}, '.jpeg': {'image/jpeg'}, '.gif': {'image/gif'},
 '.webp': {'image/webp'}, '.heic': {'image/heic','image/heif'}, '.heif': {'image/heif','image/heic'},
 '.mp4': {'video/mp4','application/mp4'}, '.mov': {'video/quicktime'},
 '.mp3': {'audio/mpeg'}, '.wav': {'audio/x-wav','audio/wav'},
 '.zip': {'application/zip','application/x-zip'},
 '.docx': {'application/zip','application/vnd.openxmlformats-officedocument.wordprocessingml.document'},
 '.xlsx': {'application/zip','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},
 '.pptx': {'application/zip','application/vnd.openxmlformats-officedocument.presentationml.presentation'},
 '.odt': {'application/zip','application/vnd.oasis.opendocument.text'},
 '.rtf': {'text/rtf','application/rtf'}, '.txt': {'text/plain'},
 '.md': {'text/plain','text/markdown'}, '.csv': {'text/plain','text/csv'},
 '.json': {'application/json','text/plain'},
}
class SafetyError(ValueError): pass


def atomic_json(path, data):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd, temporary=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:json.dump(data,stream)
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def digest_fd(fd):
    os.lseek(fd,0,os.SEEK_SET);digest=hashlib.sha256()
    total=0
    while True:
        chunk=os.read(fd,1024*1024)
        if not chunk:break
        total+=len(chunk)
        if total>MAX_SIZE:raise SafetyError('File grew beyond the integrity-check size limit.')
        digest.update(chunk)
    os.lseek(fd,0,os.SEEK_SET)
    return digest.hexdigest()


def records():
    try:
        data=json.loads((STATE/'integrity.json').read_text())
        return data if isinstance(data,dict) else {}
    except FileNotFoundError:return {}
    except (OSError,ValueError):raise SafetyError('Integrity records could not be read; checks blocked.')


def quarantine(path, fd, digest, reason):
    folder=STATE/'quarantine';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    if folder.is_symlink():raise SafetyError('Quarantine directory must not be a symbolic link.')
    folder.chmod(0o700)
    out, name=tempfile.mkstemp(prefix='blocked-',suffix='.quarantine',dir=folder)
    try:
        os.lseek(fd,0,os.SEEK_SET)
        with os.fdopen(out,'wb') as stream:
            while True:
                chunk=os.read(fd,1024*1024)
                if not chunk:break
                stream.write(chunk)
            stream.flush();os.fsync(stream.fileno())
        with open(name,'rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=digest:raise SafetyError('File changed while quarantining; original kept.')
        atomic_json(Path(name+'.json'),{'original_path':str(path),'sha256':digest,'reason':reason,'time':time.time()})
        current=path.lstat();opened=os.fstat(fd)
        if (current.st_dev,current.st_ino)!=(opened.st_dev,opened.st_ino):raise SafetyError('File changed while quarantining; original kept.')
        path.unlink()
        return name
    except Exception:
        # Never delete original data when quarantining fails.
        raise


def validate_container(fd, suffix):
    if suffix not in {'.zip','.docx','.xlsx','.pptx','.odt'}:return
    try:
        with os.fdopen(os.dup(fd),'rb') as stream, zipfile.ZipFile(stream) as archive:
            entries=archive.infolist()
            if len(entries)>10000 or sum(i.file_size for i in entries)>MAX_SIZE:
                raise SafetyError('Archive exceeds integrity-check limits.')
            names={i.filename for i in entries}
            required={'.docx':'word/document.xml','.xlsx':'xl/workbook.xml','.pptx':'ppt/presentation.xml','.odt':'content.xml'}
            if suffix in required and required[suffix] not in names:raise SafetyError('Document structure does not match its extension.')
            total=0
            for entry in entries:
                if entry.flag_bits & 1:raise SafetyError('Encrypted archive cannot be fully checked.')
                with archive.open(entry) as member:
                    while True:
                        chunk=member.read(1024*1024)
                        if not chunk:break
                        total+=len(chunk)
                        if total>MAX_SIZE:raise SafetyError('Expanded archive exceeds integrity-check limits.')
    except (zipfile.BadZipFile,RuntimeError,NotImplementedError,OSError) as error:
        raise SafetyError('Archive is corrupt or cannot be checked.') from error
    finally:os.lseek(fd,0,os.SEEK_SET)


def check_file(raw, scan=False):
    """Check stable descriptor; return digest or raise. Detected threats are quarantined."""
    path=Path(raw).absolute()
    with LOCK:
        try:
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        except OSError as error:raise SafetyError('Cannot check file or symbolic link: '+path.name) from error
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):raise SafetyError('Only regular files can be checked.')
            if info.st_size>MAX_SIZE:raise SafetyError('File exceeds the 512 MB checking limit; opening and AI are blocked.')
            digest=digest_fd(fd); ledger=records(); identity=str(path)
            previous=ledger.get(identity)
            if previous and previous.get('sha256')!=digest:raise SafetyError('File changed since receipt/previous check: '+path.name)
            # Run antivirus first so even disguised threats are quarantined.
            if scan:
                scanner=shutil.which('clamscan')
                if not scanner:raise SafetyError('ClamAV is unavailable. Install clamav and update signatures with freshclam.')
                result=subprocess.run([scanner,'--stdout','--no-summary','--fail-if-cvd-older-than=7','--alert-exceeds-max=yes','--alert-encrypted=yes',
                    '--max-filesize=512M','--max-scansize=512M','--follow-file-symlinks=1','--',f'/proc/self/fd/{fd}'],
                    pass_fds=(fd,),capture_output=True,timeout=180,env={**os.environ,'LC_ALL':'C'})
                output=result.stdout.decode(errors='replace')
                if result.returncode==1:
                    if ' FOUND' not in output:raise SafetyError('ClamAV did not return a complete scan result; file blocked.')
                    if 'Heuristics.Limits.Exceeded' in output or 'Heuristics.Encrypted' in output:
                        raise SafetyError('ClamAV could not fully inspect this file (encrypted or scan limit exceeded).')
                    location=quarantine(path,fd,digest,'ClamAV detected a threat')
                    raise SafetyError('Threat detected and quarantined: '+location)
                if result.returncode!=0 or not any(line.endswith(': OK') for line in output.splitlines()):raise SafetyError('ClamAV scan failed or definitions are missing/outdated. Run freshclam; file blocked.')
            detector=shutil.which('file')
            if not detector:raise SafetyError('File-type detector is unavailable; install the file package.')
            result=subprocess.run([detector,'--brief','--mime-type','--',f'/proc/self/fd/{fd}'],pass_fds=(fd,),capture_output=True,timeout=20,env={**os.environ,'LC_ALL':'C'})
            # file needs -L for the proc descriptor symlink, never user-provided symlinks.
            mime=result.stdout.decode(errors='replace').strip()
            if mime=='inode/symlink':
                result=subprocess.run([detector,'-L','--brief','--mime-type','--',f'/proc/self/fd/{fd}'],pass_fds=(fd,),capture_output=True,timeout=20)
                mime=result.stdout.decode(errors='replace').strip()
            suffix=path.suffix.lower()
            if result.returncode or suffix not in TYPES:raise SafetyError('File type is unverified or unsupported; opening and AI are blocked: '+path.name)
            if mime not in TYPES[suffix] and not (info.st_size==0 and suffix in {'.txt','.md','.csv'}):
                raise SafetyError(f'Extension/content mismatch: {path.name} was detected as {mime}.')
            os.lseek(fd,0,os.SEEK_SET)
            head=os.read(fd,min(info.st_size,65536));os.lseek(fd,0,os.SEEK_SET)
            if suffix in {'.txt','.md','.csv','.json'} and b'\0' in head:raise SafetyError('Text file contains unexpected binary data.')
            if suffix=='.json':
                if info.st_size>20*1024*1024:raise SafetyError('JSON exceeds the structural-check limit.')
                try:json.loads(os.read(fd,20*1024*1024+1).decode('utf-8-sig'))
                except (ValueError,UnicodeError,RecursionError) as error:raise SafetyError('JSON is corrupt or invalid.') from error
                os.lseek(fd,0,os.SEEK_SET)
            if suffix=='.pdf':
                os.lseek(fd,max(0,info.st_size-2048),os.SEEK_SET)
                if b'%%EOF' not in os.read(fd,2048):raise SafetyError('PDF appears truncated (missing end marker).')
                os.lseek(fd,0,os.SEEK_SET)
            if suffix in {'.png','.jpg','.jpeg','.gif','.webp'}:
                from PySide6.QtGui import QImageReader
                reader=QImageReader(f'/proc/self/fd/{fd}')
                size=reader.size()
                if size.width()<=0 or size.height()<=0 or size.width()*size.height()>100000000:
                    raise SafetyError('Image dimensions are invalid or exceed decoding limits.')
                if reader.read().isNull():raise SafetyError('Image is corrupt or cannot be decoded.')
                os.lseek(fd,0,os.SEEK_SET)
            validate_container(fd,suffix)
            if digest_fd(fd)!=digest:raise SafetyError('File changed during checks.')
            current=path.lstat()
            if (current.st_dev,current.st_ino)!=(info.st_dev,info.st_ino):raise SafetyError('File was replaced during checks.')
            ledger[identity]={'sha256':digest,'mime':mime,'time':time.time(),'antivirus':bool(scan)}
            if len(ledger)>10000:ledger=dict(list(ledger.items())[-10000:])
            atomic_json(STATE/'integrity.json',ledger)
            return digest
        except subprocess.TimeoutExpired as error:raise SafetyError('File check timed out; opening and AI are blocked.') from error
        except OSError as error:raise SafetyError('File check failed; opening and AI are blocked.') from error
        finally:os.close(fd)


def verified_snapshot(raw, expected):
    """Open a private read-only copy, not a download path that can be replaced."""
    source=Path(raw)
    folder=STATE/'verified-open';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    if folder.is_symlink():raise SafetyError('Verified-copy directory must not be a symbolic link.')
    directory=Path(tempfile.mkdtemp(prefix='open-',dir=folder));target=directory/source.name
    try:
        fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):raise SafetyError('Only regular files can be opened.')
            digest=hashlib.sha256();total=0
            with target.open('xb') as stream:
                os.chmod(target,0o600)
                while True:
                    chunk=os.read(fd,1024*1024)
                    if not chunk:break
                    total+=len(chunk)
                    if total>MAX_SIZE:raise SafetyError('File exceeds checking limits.')
                    stream.write(chunk);digest.update(chunk)
            if digest.hexdigest()!=expected:raise SafetyError('File changed before opening; blocked.')
            target.chmod(0o400)
            return str(target)
        finally:os.close(fd)
    except Exception:
        shutil.rmtree(directory)
        raise


from PySide6.QtCore import QThread, Signal
class CheckWorker(QThread):
    checked=Signal(object)
    def __init__(self, paths, scan, prepare_open=False):super().__init__();self.paths=list(paths);self.scan=scan;self.prepare_open=prepare_open
    def run(self):
        results=[]
        for path in self.paths:
            try:
                digest=check_file(path,self.scan)
                ready=verified_snapshot(path,digest) if self.prepare_open else str(path)
                results.append((ready,True,'Type/hash checked; ClamAV: no threats detected' if self.scan else 'Type/hash checked; ClamAV is off'))
            except Exception as error:results.append((str(path),False,str(error) if isinstance(error,SafetyError) else 'File check failed.'))
        self.checked.emit(results)


def scanner_status():
    scanner=shutil.which('clamscan')
    if not scanner:return 'not installed'
    try:
        result=subprocess.run([scanner,'--version'],capture_output=True,text=True,timeout=3)
        version=result.stdout.strip()
        return version if '/' in version else version+' — definitions not available; run freshclam'
    except (OSError,subprocess.TimeoutExpired):return 'scanner status unavailable'

_OPEN_WORKERS = set()
def open_verified(path, scan, notifier):
    """Check generated answer before an app-controlled Open action, too."""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtCore import QUrl
    worker=CheckWorker([path],scan,prepare_open=True);_OPEN_WORKERS.add(worker)
    def ready(results):
        if results and results[0][1]:QDesktopServices.openUrl(QUrl.fromLocalFile(results[0][0]))
        else:notifier.notify('File blocked',results[0][2] if results else 'No file checked.')
    def finished():_OPEN_WORKERS.discard(worker);worker.deleteLater()
    worker.checked.connect(ready);worker.finished.connect(finished)
    QApplication.instance().aboutToQuit.connect(worker.wait);worker.start()
