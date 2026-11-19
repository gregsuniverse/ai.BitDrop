import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
import ai_panel as ai

app = QApplication.instance() or QApplication([])
class AITests(unittest.TestCase):
    def setUp(self):
        import file_safety
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        patcher=patch.object(file_safety,'STATE',Path(temp.name)/'security');patcher.start();self.addCleanup(patcher.stop)
    def test_payload_and_response(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)/'example.txt'; p.write_text('Synthetic test only')
            result = ai.build_request([p], 'Summarize', 'gpt-4.1-mini')
            self.assertFalse(result['store'])
            self.assertEqual(result['input'][0]['content'][1]['filename'], p.name)
            self.assertEqual(ai.response_text({'output':[{'type':'message','content':[{'type':'output_text','text':'Done'}]}]}), 'Done')
    def test_reject_media_symlinks_limits_and_empty_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)/'video.mov'; p.write_text('test')
            with self.assertRaises(ValueError): ai.build_request([p], 'Explain', 'model')
            p = Path(directory)/'example.txt'; p.write_text('test')
            link=Path(directory)/'link.txt'; link.symlink_to(p)
            with self.assertRaises(ValueError): ai.build_request([link], 'Explain', 'model')
            with self.assertRaises(ValueError): ai.build_request([p], '', 'model')
            with patch.object(ai, 'LIMIT', 2):
                with self.assertRaises(ValueError): ai.build_request([p], 'Explain', 'model')
    def test_key_private_and_dialog_never_sends_on_open(self):
        with tempfile.TemporaryDirectory() as directory:
            key=Path(directory)/'key'; ai.save_key('synthetic-key', key)
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            settings=QSettings(str(Path(directory)/'test.ini'), QSettings.Format.IniFormat)
            with patch.object(ai.RequestWorker, 'start') as start:
                dialog=ai.AskDialog(None, settings, [])
                start.assert_not_called(); dialog.close()
    def test_worker_uses_fixed_destination_and_extracts_text(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'test.txt'; p.write_text('Synthetic')
            class Reply:
                def __enter__(self): return self
                def __exit__(self,*args): pass
                def read(self,*args): return json.dumps({'output':[{'type':'message','content':[{'type':'output_text','text':'Synthetic answer'}]}]}).encode()
            with patch('urllib.request.build_opener') as opener:
                opener.return_value.open.return_value=Reply()
                worker=ai.RequestWorker([p], 'Explain', 'model', 'fake-key'); answers=[]
                worker.result.connect(answers.append); worker.run()
                request=opener.return_value.open.call_args.args[0]
                self.assertEqual(request.full_url, 'https://api.openai.com/v1/responses')
                self.assertEqual(answers, ['Synthetic answer']); self.assertEqual(worker.key, '')


class ReceiptRuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = QSettings(str(self.root/'rules.ini'), QSettings.Format.IniFormat)
        import file_safety
        self.state_patch=patch.object(file_safety,'STATE',self.root/'security');self.state_patch.start()
        from PySide6.QtGui import QImage
        self.photo = self.root/'PHOTO.JPG'; image=QImage(8,8,QImage.Format.Format_RGB32);image.fill(0xff00ffff);image.save(str(self.photo))
        self.photo_bytes=self.photo.read_bytes()
        self.pdf = self.root/'notes.pdf'; self.pdf.write_bytes(b'synthetic')
        self.settings.setValue('ai_receipt_rules', json.dumps([
            {'type':'Images','enabled':True,'prompt':'Extract receipt details'},
            {'type':'PDF documents','enabled':True,'prompt':'Summarize PDF'}]))
    def tearDown(self): self.state_patch.stop();self.temp.cleanup()
    def test_default_off_and_type_linked_prompts(self):
        self.assertEqual(ai.receipt_jobs(self.settings,[self.photo,self.pdf],self.root), [])
        self.settings.setValue('ai_receipt_enabled', True)
        jobs=ai.receipt_jobs(self.settings,[self.photo,self.pdf,self.photo],self.root)
        self.assertEqual(jobs,[([str(self.photo)],'Extract receipt details'),([str(self.pdf)],'Summarize PDF')])
    def test_unmatched_outside_symlink_and_bad_rules(self):
        self.settings.setValue('ai_receipt_enabled', True)
        link=self.root/'linked.jpg';link.symlink_to(self.photo)
        with tempfile.TemporaryDirectory() as other:
            outside=Path(other)/'other.jpg';outside.write_bytes(b'synthetic')
            video=self.root/'video.mov';video.write_bytes(b'synthetic')
            self.assertEqual(ai.receipt_jobs(self.settings,[outside,link,video],self.root), [])
        self.settings.setValue('ai_receipt_rules', '{bad json')
        self.assertEqual(ai.load_rules(self.settings), [])
    def test_queued_work_cleared_on_disable_and_duplicate_events_ignored(self):
        class Notifier:
            def notify(self,*args): pass
        processor=ai.ReceiptProcessor(self.settings,Notifier())
        processor.queue=[('old',[], 'prompt',self.root)]
        processor.next_job();self.assertEqual(processor.queue, [])
        self.settings.setValue('ai_receipt_enabled', True)
        with patch.object(processor,'next_job'):
            processor.receive((1,1),[self.photo],self.root)
            processor.receive((1,1),[self.photo],self.root)
            self.assertEqual(len(processor.queue),1)
    def test_result_saved_privately_without_modifying_input(self):
        class Notifier:
            def __init__(self): self.calls=[]
            def notify(self,*args): self.calls.append(args)
        notify=Notifier();processor=ai.ReceiptProcessor(self.settings,notify)
        processor.save_answer('Synthetic analysis',[str(self.photo)],self.root)
        results=list((self.root/'AI results').glob('*.txt'))
        self.assertEqual(len(results),1)
        self.assertEqual(results[0].stat().st_mode & 0o777,0o600)
        self.assertIn('Synthetic analysis',results[0].read_text())
        self.assertEqual(self.photo.read_bytes(),self.photo_bytes)
        self.assertEqual(notify.calls[0][0],'AI analysis complete')
    def test_receipt_runs_worker_once_and_saves_mock_response(self):
        import time
        class Notifier:
            def notify(self,*args): pass
        class Reply:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,*args): return json.dumps({'output':[{'type':'message','content':[{'type':'output_text','text':'Automatic synthetic answer'}]}]}).encode()
        key=self.root/'key';key.write_text('fake-key')
        self.settings.setValue('ai_receipt_enabled', True)
        processor=ai.ReceiptProcessor(self.settings,Notifier())
        with patch.object(ai,'CREDENTIAL',key), patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=Reply()
            processor.receive((2,1),[self.photo],self.root)
            processor.receive((2,1),[self.photo],self.root)
            deadline=time.monotonic()+2
            while processor.worker and time.monotonic()<deadline:
                app.processEvents();time.sleep(.005)
            self.assertIsNone(processor.worker)
            self.assertEqual(opener.return_value.open.call_count,1)
            payload=json.loads(opener.return_value.open.call_args.args[0].data)
            self.assertEqual(payload['input'][0]['content'][0]['text'],'Extract receipt details')
            answer=next((self.root/'AI results').glob('*.txt')).read_text()
            self.assertIn('Automatic synthetic answer',answer)

    def test_dialog_open_does_not_enable_or_submit(self):
        with patch.object(ai.RequestWorker,'start') as start:
            dialog=ai.ReceiptRulesDialog(None,self.settings)
            self.assertFalse(dialog.master.isChecked()); start.assert_not_called()
            dialog.types.setCurrentText('Text files');dialog.add()
            self.assertEqual(dialog.rules[-1]['type'],'Text files')
            dialog.prompt.setPlainText('Custom text prompt');dialog.commit()
            self.assertEqual(dialog.rules[-1]['prompt'],'Custom text prompt')
            dialog.close()
if __name__=='__main__': unittest.main()
