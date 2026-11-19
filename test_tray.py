import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import unittest
from PySide6.QtCore import QProcess, QSettings
from PySide6.QtWidgets import QApplication
from owly_tray import TrayApp, SendDialog, SettingsDialog


class FakeNotifications:
    def __init__(self): self.sent = []; self.closed = []
    def notify(self, title, body, actions=None, timeout=10000):
        self.sent.append((title, body, actions or {})); return len(self.sent)
    def close(self, nid): self.closed.append(nid)


class FakeReceiver:
    def __init__(self): self.commands = []; self.running = True
    def state(self): return QProcess.ProcessState.Running if self.running else QProcess.ProcessState.NotRunning
    def write(self, data): self.commands.append(json.loads(data))
    def terminate(self): self.running = False
    def waitForFinished(self, timeout): return True
    def deleteLater(self): pass


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        settings = QSettings(str(Path(self.tmp.name)/"settings.ini"), QSettings.Format.IniFormat)
        settings.setValue("directory", self.tmp.name)
        self.n = FakeNotifications()
        self.tray = TrayApp(self.app, self.n, settings=settings, start=False)
        self.tray.epoch = 7
        self.tray.receiver = FakeReceiver()
    def tearDown(self):
        self.tray.stop(); self.tray.tray.hide(); self.tray.window.deleteLater()
        self.tmp.cleanup()
    def request(self, tid, name="photo.jpg"):
        self.tray.handle_event({"event":"request", "id":tid, "sender":"My iPhone",
            "files":[{"name":name,"size":100}], "urls":[]})
    def test_actions_are_bound_to_each_request(self):
        self.request(1); self.request(2)
        self.n.sent[0][2]["accept"][1]()
        self.assertEqual(self.tray.receiver.commands, [{"id":1,"accept":True}])
        self.assertIn((7,2), self.tray.pending)
        self.assertNotIn((7,1), self.tray.pending)
    def test_old_notification_cannot_accept_new_session(self):
        self.request(1)
        old_action = self.n.sent[0][2]["accept"][1]
        self.tray.clear_pending((7,1)); self.tray.epoch = 8
        self.request(1)
        old_action()
        self.assertEqual(self.tray.receiver.commands, [])
        self.assertIn((8,1), self.tray.pending)
    def test_expired_request_cannot_be_accepted(self):
        self.request(4)
        self.tray.expire((7,4))
        self.n.sent[0][2]["accept"][1]()
        self.assertEqual(self.tray.receiver.commands, [{"id":4,"accept":False}])
    def test_stop_closes_prompts_and_receiver(self):
        self.request(2); receiver = self.tray.receiver
        self.tray.stop()
        self.assertFalse(receiver.running)
        self.assertEqual(self.tray.pending, {})
        self.assertIn(1,self.n.closed)
    def test_urls_are_saved_as_inert_text(self):
        self.tray.handle_event({"event":"urls","id":1,"urls":["file:///etc/passwd", "https://example.org/"]})
        files = list(Path(self.tmp.name).glob("AirDrop-links-*.txt"))
        self.assertEqual(len(files),1)
        self.assertIn("file:///etc/passwd", files[0].read_text())
    def test_remote_text_is_plain_and_bounded(self):
        self.request(1, "<b>name</b>\n" + "X"*10000)
        row = self.tray.rows[(7,1)]
        self.assertLessEqual(len(row.text(1)),120)
        self.assertNotIn("\n",row.text(1))

    def send_dialog(self):
        d = SendDialog(self.tray, [str(Path(self.tmp.name)/"test.txt")])
        d.waiter.stop(); self.tray.outbound = d
        return d

    def test_discovery_rejects_invalid_target_ids(self):
        d = self.send_dialog()
        d.peer_event({"event":"peer","id":"--url","name":"Fake phone"})
        self.assertEqual(d.devices.topLevelItemCount(),0)
        d.peer_event({"event":"peer","id":"12:34:56:78:9a:bc","name":"iPhone"})
        self.assertEqual(d.devices.topLevelItemCount(),1)
        d.peer_event({"event":"peer","id":"12:34:56:78:9a:bc","name":"duplicate"})
        self.assertEqual(d.devices.topLevelItemCount(),1)

    def test_full_upload_does_not_claim_delivery(self):
        d = self.send_dialog(); d.active = True
        d.send_event({"event":"progress","sent":100,"total":100})
        self.assertFalse(d.delivered)
        self.assertIn("confirm",d.status.text())
        d.send_finished(1)
        self.assertEqual(self.n.sent[-1][0],"AirDrop send failed")

    def test_delivery_requires_confirmation_and_success_exit(self):
        d = self.send_dialog(); d.active = True
        d.send_event({"event":"delivered"}); d.send_finished(0)
        self.assertEqual(self.n.sent[-1][0],"AirDrop sent")

    def test_canceled_send_is_not_reported_as_failure(self):
        d = self.send_dialog(); d.active = True; d.canceled = True
        d.send_finished(1)
        self.assertEqual(self.n.sent,[])

    def test_trusted_policy_rejects_unknown_and_missing_certificates(self):
        self.tray.policy = "trusted"; self.tray.trusted_devices = {"a"*64:"My iPhone"}
        self.tray.handle_event({"event":"request","id":1,"sender":"My iPhone","files":[],"fingerprint":"b"*64})
        self.tray.handle_event({"event":"request","id":2,"sender":"My iPhone","files":[],"fingerprint":None})
        self.assertEqual(self.tray.receiver.commands,[{"id":1,"accept":False},{"id":2,"accept":False}])
        self.assertFalse(self.tray.pending); self.assertEqual(self.n.sent,[])

    def test_trusted_policy_still_requires_manual_approval(self):
        self.tray.policy = "trusted"; self.tray.trusted_devices = {"a"*64:"My iPhone"}
        self.tray.handle_event({"event":"request","id":3,"sender":"Renamed phone","files":[],"fingerprint":"a"*64})
        self.assertIn((7,3),self.tray.pending)
        self.assertEqual(self.tray.receiver.commands,[])
        self.n.sent[-1][2]["accept"][1]()
        self.assertEqual(self.tray.receiver.commands,[{"id":3,"accept":True}])

    def test_policy_is_checked_again_when_accept_is_clicked(self):
        self.request(4); self.tray.policy = "blocked"
        self.n.sent[-1][2]["accept"][1]()
        self.assertEqual(self.tray.receiver.commands,[{"id":4,"accept":False}])

    def test_settings_persist_name_and_restrictions(self):
        self.tray.wanted = False
        self.tray.apply_settings("My Linux", "trusted", {"a"*64:"Phone"})
        self.assertEqual(self.tray.settings.value("name"),"My Linux")
        self.assertEqual(self.tray.settings.value("incoming_policy"),"trusted")
        self.assertEqual(json.loads(self.tray.settings.value("trusted_devices")),{"a"*64:"Phone"})
        self.assertEqual(self.tray.subtitle.text(),"Visible as My Linux")

    def test_settings_dialog_shows_current_profile(self):
        dialog = SettingsDialog(self.tray)
        self.assertEqual(dialog.device_name.text(),self.tray.name)
        self.assertEqual(dialog.policy.currentData(),"everyone")
        dialog.deleteLater()


if __name__ == "__main__": unittest.main()
