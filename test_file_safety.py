"""Synthetic file checks; antivirus responses mocked except separate manual EICAR test."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import file_safety as safety

class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.state=patch.object(safety,'STATE',self.root/'state');self.state.start()
    def tearDown(self):self.state.stop();self.temp.cleanup()
    def file(self,name,data):
        path=self.root/name;path.write_bytes(data);return path
    def test_text_baseline_then_changed_content_blocked(self):
        path=self.file('note.txt',b'original text')
        self.assertEqual(safety.check_file(path),hashlib.sha256(path.read_bytes()).hexdigest())
        path.write_bytes(b'modified text')
        with self.assertRaisesRegex(safety.SafetyError,'changed since'):safety.check_file(path)
    def test_disguised_executable_and_truncated_document_blocked(self):
        path=self.file('photo.jpg',b'#!/bin/sh\necho fake image\n')
        with self.assertRaisesRegex(safety.SafetyError,'mismatch'):safety.check_file(path)
        path=self.file('document.pdf',b'%PDF-1.7\ntruncated')
        with self.assertRaisesRegex(safety.SafetyError,'truncated'):safety.check_file(path)
    def test_unknown_type_symlink_and_named_pipe_blocked(self):
        import os
        source=self.file('file.unknown',b'sample')
        with self.assertRaises(safety.SafetyError):safety.check_file(source)
        link=self.root/'link.txt';link.symlink_to(source)
        with self.assertRaises(safety.SafetyError):safety.check_file(link)
        pipe=self.root/'pipe.txt';os.mkfifo(pipe)
        with self.assertRaisesRegex(safety.SafetyError,'regular'):safety.check_file(pipe)
    def test_archive_crc_and_document_identity(self):
        path=self.root/'valid.zip'
        with zipfile.ZipFile(path,'w') as archive:archive.writestr('hello.txt','hello')
        safety.check_file(path)
        renamed=self.root/'fake.docx';renamed.write_bytes(path.read_bytes())
        with self.assertRaisesRegex(safety.SafetyError,'structure'):safety.check_file(renamed)
        broken=self.file('broken.zip',b'PK\x03\x04'+b'broken'*20)
        with self.assertRaises(safety.SafetyError):safety.check_file(broken)
    def test_missing_scanner_and_scan_error_never_pass(self):
        path=self.file('sample.txt',b'clean')
        original=safety.shutil.which
        with patch.object(safety.shutil,'which',side_effect=lambda cmd: None if cmd=='clamscan' else original(cmd)):
            with self.assertRaisesRegex(safety.SafetyError,'unavailable'):safety.check_file(path,True)
        for code,output in [(2,b'database error'),(0,b'Skipped'),(1,b'no complete verdict'),(1,b'x: Heuristics.Limits.Exceeded FOUND')]:
            with patch.object(safety.shutil,'which',return_value='/fake/scanner'),patch.object(safety.subprocess,'run',return_value=subprocess.CompletedProcess([],code,output,b'')):
                with self.assertRaises(safety.SafetyError):safety.check_file(path,True)
            self.assertTrue(path.exists())
    def test_detection_quarantines_without_deleting_contents(self):
        path=self.file('sample.txt',b'harmless synthetic test')
        with patch.object(safety.shutil,'which',return_value='/fake/scanner'),patch.object(safety.subprocess,'run',return_value=subprocess.CompletedProcess([],1,b'file: Synthetic.Test FOUND\n',b'')):
            with self.assertRaisesRegex(safety.SafetyError,'quarantined'):safety.check_file(path,True)
        self.assertFalse(path.exists())
        dest=next((safety.STATE/'quarantine').glob('*.quarantine'))
        self.assertEqual(dest.read_bytes(),b'harmless synthetic test')
        self.assertEqual(dest.stat().st_mode & 0o777,0o600)
        self.assertEqual(json.loads(Path(str(dest)+'.json').read_text())['original_path'],str(path))
    def test_open_uses_readonly_verified_copy_and_rejects_changes(self):
        path=self.file('note.txt',b'original')
        digest=safety.check_file(path)
        snapshot=Path(safety.verified_snapshot(path,digest))
        self.assertNotEqual(snapshot,path);self.assertEqual(snapshot.read_bytes(),b'original')
        self.assertEqual(snapshot.stat().st_mode & 0o777,0o400)
        path.write_bytes(b'replaced')
        with self.assertRaisesRegex(safety.SafetyError,'changed'):safety.verified_snapshot(path,digest)
        self.assertEqual(snapshot.read_bytes(),b'original')

    def test_ai_never_posts_on_check_failure(self):
        from ai_panel import RequestWorker
        path=self.file('disguised.jpg',b'not an image')
        worker=RequestWorker([path],'Explain','model','fake-key')
        errors=[];worker.failed.connect(errors.append)
        with patch('urllib.request.build_opener') as opener:
            worker.run();opener.assert_not_called()
        self.assertTrue(errors)

if __name__=='__main__':unittest.main()
