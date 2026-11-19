"""Local TLS integration test. Requires an already-active awdl0, not an iPhone.

Uses a separate port, a temporary destination, and no mDNS advertising.
"""
import gzip
import hashlib
import http.client
import json
from pathlib import Path
import plistlib
import select
import socket
import ssl
import subprocess
import tempfile
import uuid


def entry(name, mode, data=b""):
    fields = (0,1,mode,501,20,1,0)
    header = "070707" + "".join(f"{v:06o}" for v in fields)
    header += f"{0:011o}{len(name.encode())+1:06o}{len(data):011o}"
    return header.encode() + name.encode() + b"\0" + data


def main():
    helper = Path(__file__).with_name("owly-desktop-helper")
    line = next(line for line in Path("/proc/net/if_inet6").read_text().splitlines()
                if line.split()[-1] == "awdl0" and line.startswith("fe80"))
    ip = socket.inet_ntop(socket.AF_INET6, bytes.fromhex(line.split()[0]))
    scope = socket.if_nametoindex("awdl0")
    with tempfile.TemporaryDirectory() as dest, tempfile.TemporaryDirectory() as certdir, tempfile.TemporaryFile() as err:
        cert, key = Path(certdir)/"cert.pem", Path(certdir)/"key.pem"
        subprocess.run(["openssl","req","-x509","-newkey","ec","-pkeyopt","ec_paramgen_curve:prime256v1",
            "-nodes","-keyout",str(key),"-out",str(cert),"-days","1","-subj","/CN=LocalTest"],
            check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        expected_fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
        proc = subprocess.Popen([str(helper),"receive","--json-events","--no-mdns",
            "--port","18771","--dir",dest],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err)
        def event(kind):
            for _ in range(20):
                if not select.select([proc.stdout],[],[],5)[0]:
                    err.seek(0); raise AssertionError(err.read().decode())
                value = json.loads(proc.stdout.readline())
                if value["event"] == kind: return value
            raise AssertionError("Missing event: "+kind)
        def answer(tid, accepted):
            proc.stdin.write((json.dumps({"id":tid,"accept":accepted})+"\n").encode());proc.stdin.flush()
        def connect(with_certificate=False):
            raw=socket.socket(socket.AF_INET6,socket.SOCK_STREAM);raw.settimeout(5)
            raw.connect((ip,18771,0,scope))
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
            if with_certificate: context.load_cert_chain(str(cert),str(key))
            return context.wrap_socket(raw,server_hostname="local-test")
        def send(sock,path,body,headers=None):
            hdr={"Host":"local-test","Content-Length":str(len(body)),**(headers or {})}
            sock.sendall((f"POST {path} HTTP/1.1\r\n"+"".join(f"{k}: {v}\r\n" for k,v in hdr.items())+"\r\n").encode()+body)
        def response(sock):
            result=http.client.HTTPResponse(sock);result.begin();result.read();return result.status
        def ask(sock,tid,name):
            body=plistlib.dumps({"SenderComputerName":"Local integration test","SenderModelName":"Test",
                "SenderID":"local-test","TransferID":{"id":tid},"TransferType":{"files":{}},
                "Files":[{"FileName":name,"FileBomPath":"./"+name,"FileType":"public.data","FileSize":22}]}, fmt=plistlib.FMT_BINARY)
            send(sock,"/Ask",body,{"Content-Type":"application/x-apple-binary-plist"})
            return event("request")
        try:
            assert event("ready")["event"]=="ready"
            with connect() as sock:
                req=ask(sock,str(uuid.uuid4()),"declined.txt")
                assert req["fingerprint"] is None
                answer(req["id"],False)
                assert response(sock)==403
                assert event("answered")["accepted"] is False
            with connect(with_certificate=True) as sock:
                tid=str(uuid.uuid4());payload=b"Owly tray integration\n"
                req=ask(sock,tid,"accepted.txt")
                assert req["fingerprint"] == expected_fingerprint
                answer(req["id"]+999,True) # stale/unknown IDs must have no effect
                sock.settimeout(0.2)
                try:
                    sock.recv(1)
                    raise AssertionError("Unknown ID accepted a transfer")
                except TimeoutError: pass
                sock.settimeout(5)
                answer(req["id"],True)
                assert response(sock)==200
                assert event("answered")["accepted"] is True
                raw=entry(".",0o40755)+entry("./accepted.txt",0o100644,payload)+entry("TRAILER!!!",0)
                send(sock,"/Upload",gzip.compress(raw),{"TransferID":tid,"TotalBytes":"0","Content-Type":"application/x-cpio"})
                assert response(sock)==200
                received=event("received")
                assert (Path(dest)/"accepted.txt").read_bytes()==payload
                assert not (Path(dest)/"declined.txt").exists()
                assert len(received["paths"])==1
            print("PASS: real TLS certificate fingerprint, missing certificate, decline, stale answer rejection, accept, upload, completion, and file contents")
        finally:
            proc.stdin.close()
            try:proc.wait(timeout=3)
            except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=3)


if __name__=="__main__":main()
