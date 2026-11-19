"""Test sender against a separate local receiver on awdl0; no iPhone data."""
from pathlib import Path
import json
import os
import selectors
import subprocess
import tempfile
import time


def main():
    helper = str(Path(__file__).with_name('owly-desktop-helper'))
    mac = Path('/sys/class/net/awdl0/address').read_text().strip()
    with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryFile() as log:
        root = Path(temp); source = root/'sample.txt'; destination = root/'received'
        source.write_bytes(b'Owly structured sender integration test\n'*1000)
        destination.mkdir()
        receiver = subprocess.Popen([helper,'receive','--json-events','--no-mdns',
            '--port','8770','--dir',str(destination)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,bufsize=0)
        sender = None
        events = []
        try:
            ready=json.loads(receiver.stdout.readline());assert ready['event']=='ready'
            sender=subprocess.Popen([helper,'send','--json-events','--no-ble',
                '--mac',mac,'--seconds','5','--',str(source)],stdout=subprocess.PIPE,stderr=log,bufsize=0)
            selector=selectors.DefaultSelector()
            selector.register(receiver.stdout,selectors.EVENT_READ,'receiver')
            selector.register(sender.stdout,selectors.EVENT_READ,'sender')
            buffers={'receiver':b'','sender':b''}
            deadline=time.monotonic()+15
            while time.monotonic()<deadline and not {'received','delivered'}.issubset(events):
                for key,_ in selector.select(1):
                    data=os.read(key.fileobj.fileno(),65536)
                    if not data:selector.unregister(key.fileobj);continue
                    kind=key.data;buffers[kind]+=data
                    while b'\n' in buffers[kind]:
                        line,buffers[kind]=buffers[kind].split(b'\n',1)
                        event=json.loads(line);events.append(event['event'])
                        if kind=='receiver' and event['event']=='request':
                            receiver.stdin.write((json.dumps({'id':event['id'],'accept':True})+'\n').encode())
            assert sender.wait(timeout=3)==0, events
            assert {'accepted','progress','received','delivered'}.issubset(events),events
            assert (destination/source.name).read_bytes()==source.read_bytes()
            print('PASS: JSON sender acceptance, progress, confirmed delivery and file contents')
        finally:
            for process in [sender,receiver]:
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':main()
