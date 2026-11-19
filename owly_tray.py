#!/usr/bin/python3
"""KDE desktop frontend for Owly. Radio configuration remains owned by Owly."""
import argparse
import html
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
from pathlib import Path
import signal
import socket
import sys
import time

from PySide6.QtCore import QProcess, QSettings, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout,
    QLabel, QMenu, QMessageBox, QPushButton, QSystemTrayIcon, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QProgressBar, QFormLayout, QLineEdit,
    QComboBox, QDialogButtonBox, QCheckBox, QScrollArea, QWidget)

APP_NAME = "ai.BitDrop"
APP_ID = "owly-tray"
INSTALL = Path(__file__).resolve().parent
AUTOSTART = Path.home() / ".config/autostart/owly-tray.desktop"
LOG = logging.getLogger(APP_ID)


def clean(value, limit=180):
    """Keep remote text on one line; Qt widgets display it as plain text."""
    return " ".join(str(value or "").split())[:limit]


class Notifications:
    """Desktop notification actions, integrated with Qt's event loop."""
    def __init__(self):
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib
        DBusGMainLoop(set_as_default=True)
        self.dbus = dbus
        self.bus = dbus.SessionBus()
        self.api = dbus.Interface(self.bus.get_object(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications"),
            "org.freedesktop.Notifications")
        self.callbacks = {}
        self.bus.add_signal_receiver(self._action, signal_name="ActionInvoked",
            dbus_interface="org.freedesktop.Notifications",
            bus_name="org.freedesktop.Notifications")
        self.bus.add_signal_receiver(self._closed, signal_name="NotificationClosed",
            dbus_interface="org.freedesktop.Notifications",
            bus_name="org.freedesktop.Notifications")
        self.context = GLib.MainContext.default()
        self.timer = QTimer()
        self.timer.timeout.connect(self.pump)
        self.timer.start(50)

    def pump(self):
        for _ in range(30):
            if not self.context.pending(): break
            self.context.iteration(False)

    def notify(self, title, body, actions=None, timeout=10000):
        actions = actions or {}
        flat = [v for key, (label, _) in actions.items() for v in (key, label)]
        try:
            nid = int(self.api.Notify(APP_NAME, self.dbus.UInt32(0),
                str(INSTALL / "assets/aibitdrop.png"), clean(title), html.escape(clean(body, 800)),
                self.dbus.Array(flat, signature="s"),
                self.dbus.Dictionary({"desktop-entry": APP_ID}, signature="sv"),
                self.dbus.Int32(timeout), timeout=2))
            self.callbacks[nid] = {key: cb for key, (_, cb) in actions.items()}
            return nid
        except Exception:
            LOG.exception("Desktop notification unavailable")
            return None

    def close(self, nid):
        if nid is None: return
        self.callbacks.pop(nid, None)
        try: self.api.CloseNotification(self.dbus.UInt32(nid), timeout=1)
        except Exception: pass

    def _action(self, nid, action):
        cb = self.callbacks.pop(int(nid), {}).get(str(action))
        if cb: cb()

    def _closed(self, nid, reason):
        self.callbacks.pop(int(nid), None)


class SendDialog(QDialog):
    """One explicitly selected outbound transfer; receiving remains active."""
    def __init__(self, owner, files):
        super().__init__()
        self.owner = owner
        self.files = list(files)
        self.scan = None
        self.sender = None
        self.buffer = bytearray()
        self.peers = {}
        self.active = False
        self.delivered = False
        self.canceled = False
        self.error_text = ""
        self.setWindowTitle("Send with AirDrop")
        self.resize(570, 360)
        layout = QVBoxLayout(self)
        title = QLabel(f"Send {len(files)} file(s)")
        font = title.font(); font.setPointSize(17); font.setBold(True); title.setFont(font)
        layout.addWidget(title)
        names = QLabel(clean(", ".join(Path(f).name for f in files), 300))
        names.setTextFormat(Qt.TextFormat.PlainText); names.setWordWrap(True); layout.addWidget(names)
        guide = QLabel("On your iPhone: turn on Wi-Fi and Bluetooth, unlock it, then set AirDrop to Everyone for 10 Minutes.")
        guide.setWordWrap(True); layout.addWidget(guide)
        self.devices = QTreeWidget(); self.devices.setHeaderLabels(["Nearby device", "Device ID"])
        self.devices.setRootIsDecorated(False); self.devices.setColumnWidth(0, 300); layout.addWidget(self.devices)
        self.status = QLabel("Starting AirDrop…"); self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.progress = QProgressBar(); self.progress.setRange(0, 1000); self.progress.setValue(0)
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh devices"); self.refresh_button.clicked.connect(self.discover)
        self.send_button = QPushButton("Send to selected device"); self.send_button.clicked.connect(self.send_selected)
        self.send_button.setEnabled(False)
        self.cancel_button = QPushButton("Cancel send"); self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        buttons.addWidget(self.refresh_button); buttons.addStretch(); buttons.addWidget(self.send_button); buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        self.devices.itemSelectionChanged.connect(lambda: self.send_button.setEnabled(bool(self.devices.currentItem()) and not self.active))
        self.waiter = QTimer(self); self.waiter.setInterval(300); self.waiter.timeout.connect(self.wait_for_radio)
        self.wait_started = time.monotonic(); self.waiter.start()

    def wait_for_radio(self):
        if self.owner.state in ("Ready", "Receiving"):
            self.waiter.stop(); self.discover()
        elif time.monotonic()-self.wait_started > 30:
            self.waiter.stop(); self.status.setText("Radio is not ready. Check the AirDrop tray status, then Refresh devices.")

    def read_json(self, process, callback):
        self.buffer.extend(bytes(process.readAllStandardOutput()))
        if len(self.buffer) > 1024*1024:
            self.cancel(); self.status.setText("Unexpectedly large helper response."); return
        while b"\n" in self.buffer:
            line, _, remaining = self.buffer.partition(b"\n"); self.buffer = bytearray(remaining)
            try: callback(json.loads(line))
            except (ValueError, KeyError, TypeError): LOG.warning("Invalid sender helper event")

    @staticmethod
    def valid_peer_id(value):
        return isinstance(value, str) and bool(re.fullmatch(r"(?:[0-9a-fA-F]{12}|(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})", value))

    def peer_event(self, event):
        if event.get("event") == "peer":
            target = event.get("id")
            if not self.valid_peer_id(target) or target in self.peers: return
            row = QTreeWidgetItem([clean(event.get("name")) or "Apple device", target])
            row.setData(0, Qt.ItemDataRole.UserRole, target)
            self.peers[target] = row; self.devices.addTopLevelItem(row)
            self.status.setText("Choose your iPhone and press Send.")
        elif event.get("event") == "discovery_done": self.scan_finished()

    def read_error(self, process):
        self.error_text = clean(bytes(process.readAllStandardError()).decode("utf-8", "replace"), 400)

    def stop_scan(self):
        if self.scan:
            process = self.scan; self.scan = None
            process.finished.disconnect()
            if process.state() != QProcess.ProcessState.NotRunning:
                process.terminate()
                if not process.waitForFinished(700): process.kill(); process.waitForFinished(500)
            process.deleteLater()

    def discover(self):
        if self.active: return
        if self.owner.state not in ("Ready", "Receiving"):
            self.status.setText("Enable AirDrop in the tray and wait for Ready, then refresh."); return
        self.stop_scan(); self.buffer.clear(); self.peers.clear(); self.devices.clear()
        self.send_button.setEnabled(False); self.error_text = ""
        self.status.setText("Looking for nearby Apple devices… this can take 25 seconds.")
        process = QProcess(self); self.scan = process
        process.readyReadStandardOutput.connect(lambda: self.read_json(process, self.peer_event))
        process.readyReadStandardError.connect(lambda: self.read_error(process))
        process.finished.connect(lambda *_: self.scan_finished())
        process.errorOccurred.connect(lambda error: self.status.setText("Could not start device discovery.")
            if error == QProcess.ProcessError.FailedToStart else None)
        process.start(self.owner.helper, ["browse", "--json-events", "--seconds", "25", "--name", self.owner.name])

    def scan_finished(self):
        if self.active: return
        self.status.setText("Choose your iPhone and press Send." if self.peers else
            "No devices found. Unlock your iPhone, enable Everyone for 10 Minutes, and refresh.")

    def send_selected(self):
        item = self.devices.currentItem()
        if item is None or self.active: return
        target = item.data(0, Qt.ItemDataRole.UserRole)
        if not self.valid_peer_id(target): return
        if not all(Path(f).is_file() for f in self.files):
            self.status.setText("One of the selected files is no longer available."); return
        self.stop_scan(); self.buffer.clear(); self.error_text = ""
        self.active = True; self.delivered = False; self.canceled = False
        self.send_button.setEnabled(False); self.refresh_button.setEnabled(False); self.cancel_button.setEnabled(True)
        self.status.setText("Connecting to your iPhone. Accept the AirDrop request on the phone.")
        self.progress.setValue(0)
        process = QProcess(self); self.sender = process
        process.readyReadStandardOutput.connect(lambda: self.read_json(process, self.send_event))
        process.readyReadStandardError.connect(lambda: self.read_error(process))
        process.finished.connect(lambda code, *_: self.send_finished(code))
        process.errorOccurred.connect(lambda error: self.send_finished(-1)
            if error == QProcess.ProcessError.FailedToStart else None)
        process.start(self.owner.helper, ["send", "--json-events", "--to", target,
            "--name", self.owner.name, "--seconds", "30", "--", *self.files])

    def send_event(self, event):
        kind = event.get("event")
        if kind == "accepted": self.status.setText("Accepted by iPhone. Sending…")
        elif kind == "progress":
            sent, total = max(0,int(event["sent"])), max(1,int(event["total"]))
            self.progress.setValue(min(1000, sent*1000//total))
            self.status.setText(f"Sending: {sent/1_000_000:.1f} / {total/1_000_000:.1f} MB" if sent<total else
                "Upload finished. Waiting for the iPhone to confirm receipt…")
        elif kind == "delivered":
            self.delivered = True; self.progress.setValue(1000)
            self.status.setText("Delivered to your iPhone.")
        elif kind == "declined": self.error_text = "The iPhone declined the transfer."
        elif kind == "failed": self.error_text = clean(event.get("reason"), 350)

    def send_finished(self, code):
        if self.sender and self.sender.bytesAvailable():
            self.read_json(self.sender, self.send_event)
        was_active = self.active; self.active = False
        self.send_button.setEnabled(bool(self.devices.currentItem())); self.refresh_button.setEnabled(True); self.cancel_button.setEnabled(False)
        if not was_active or self.canceled: return
        if self.delivered and code == 0:
            self.owner.notify.notify("AirDrop sent", f"{len(self.files)} file(s) delivered to your iPhone.")
        else:
            self.status.setText(self.error_text or "Transfer did not complete. Unlock your iPhone and refresh devices to retry.")
            self.owner.notify.notify("AirDrop send failed", self.status.text())

    def cancel(self, silent=False):
        self.waiter.stop(); self.stop_scan(); self.canceled = True
        if self.sender and self.sender.state() != QProcess.ProcessState.NotRunning:
            self.sender.terminate()
            if not self.sender.waitForFinished(700): self.sender.kill(); self.sender.waitForFinished(500)
        self.active = False; self.cancel_button.setEnabled(False); self.refresh_button.setEnabled(True)
        self.send_button.setEnabled(bool(self.devices.currentItem()))
        if not silent: self.status.setText("Send canceled.")

    def closeEvent(self, event):
        if not self.active: self.waiter.stop(); self.stop_scan()
        event.accept() # An active send continues in the background.


class SettingsDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner.window)
        self.setWindowTitle("Device and security settings")
        self.resize(760, 700)
        outer = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); content.setMinimumWidth(640)
        layout = QVBoxLayout(content); scroll.setWidget(content); outer.addWidget(scroll)
        form = QFormLayout()
        self.device_name = QLineEdit(owner.name); self.device_name.setMaxLength(64)
        form.addRow("Visible as", self.device_name)
        self.policy = QComboBox()
        for text, value in [("Everyone — ask before receiving", "everyone"),
            ("Trusted devices only — ask before receiving", "trusted"),
            ("Block all incoming transfers", "blocked")]: self.policy.addItem(text, value)
        self.policy.setCurrentIndex(max(0, self.policy.findData(owner.policy)))
        form.addRow("Incoming transfers", self.policy)
        layout.addLayout(form)
        connect_ai = QPushButton("Connect AI…")
        connect_ai.clicked.connect(lambda: __import__("ai_panel").ConnectionDialog(self, owner.settings).exec())
        layout.addWidget(connect_ai)
        ai_rules = QPushButton("AI on receipt — file types and prompts…")
        ai_rules.clicked.connect(owner.open_ai_rules)
        layout.addWidget(ai_rules)
        self.scan_files = QCheckBox("Scan received files with ClamAV before opening or AI")
        self.scan_files.setChecked(owner.settings.value("clamav_enabled", False, type=bool))
        layout.addWidget(self.scan_files)
        from file_safety import scanner_status
        scanner_note = QLabel("ClamAV: " + scanner_status() + ". File-type and SHA-256 change checks are always on. Unsupported, mismatched, corrupt or unchecked files are blocked in this app. Type detection cannot prove authenticity. Detected threats are quarantined; nothing is auto-deleted.")
        scanner_note.setWordWrap(True); scanner_note.setMinimumHeight(85); layout.addWidget(scanner_note)
        quarantine = QPushButton("Show quarantine folder")
        def show_quarantine():
            from file_safety import STATE
            folder = STATE / "quarantine"; folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        quarantine.clicked.connect(show_quarantine); layout.addWidget(quarantine)
        note = QLabel("Trusted devices are matched by the certificate proven in their encrypted connection, not by their display name. Allowed transfers still need approval. An empty trusted list refuses everyone in trusted-device mode.")
        note.setWordWrap(True); note.setMinimumHeight(80); layout.addWidget(note)
        layout.addWidget(QLabel("Trusted devices"))
        self.devices = QTreeWidget(); self.devices.setHeaderLabels(["Label", "Certificate SHA-256"])
        self.devices.setMinimumHeight(120); self.devices.setRootIsDecorated(False); self.devices.setColumnWidth(0, 180)
        for fingerprint, label in sorted(owner.trusted_devices.items()):
            row = QTreeWidgetItem([label, fingerprint]); self.devices.addTopLevelItem(row)
        layout.addWidget(self.devices)
        remove = QPushButton("Remove selected trusted device")
        remove.clicked.connect(lambda: self.devices.takeTopLevelItem(self.devices.indexOfTopLevelItem(self.devices.currentItem())) if self.devices.currentItem() else None)
        layout.addWidget(remove)
        note = QLabel("To add a device, receive a transfer while in Everyone mode, select its row in the transfers window, and choose Trust device. Certificate changes require trusting the device again. This is not Apple Contacts Only: your computer may remain discoverable, and email/phone contact matching is not implemented.")
        note.setWordWrap(True); note.setMinimumHeight(80); layout.addWidget(note)
        self.error = QLabel(); self.error.setWordWrap(True); layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); outer.addWidget(buttons)
        self.owner = owner

    def save(self):
        name = self.device_name.text().strip()
        if not name or len(name.encode("utf-8")) > 128 or any(ord(c)<32 or ord(c)==127 for c in name):
            self.error.setText("Enter a name of 1–64 characters without control characters (up to 128 UTF-8 bytes).")
            return
        if self.owner.transfer_active():
            self.error.setText("Let the current transfer finish before changing device or security settings.")
            return
        trusted = {self.devices.topLevelItem(i).text(1):self.devices.topLevelItem(i).text(0)
            for i in range(self.devices.topLevelItemCount())}
        self.owner.settings.setValue("clamav_enabled", self.scan_files.isChecked())
        self.owner.apply_settings(name, self.policy.currentData(), trusted)
        self.accept()


class TrayApp:
    def __init__(self, app, notifier, settings=None, start=True, helper=None):
        self.app = app
        self.notify = notifier
        self.settings = settings or QSettings("OwlyTray", "OwlyTray")
        from ai_panel import ReceiptProcessor
        self.ai_receipts = ReceiptProcessor(self.settings, notifier, app)
        self.security_queue = []; self.security_worker = None
        self.helper = str(helper or INSTALL / "owly-desktop-helper")
        self.directory = Path(str(self.settings.value("directory",
            str(Path.home() / "Downloads/AirDrop"))))
        self.name = str(self.settings.value("name", socket.gethostname()))
        self.policy = str(self.settings.value("incoming_policy", "everyone"))
        try:
            trusted = json.loads(str(self.settings.value("trusted_devices", "{}")))
            self.trusted_devices = {fp:clean(label) for fp,label in trusted.items()
                if isinstance(fp,str) and re.fullmatch(r"[0-9a-f]{64}", fp)}
        except (ValueError, TypeError, AttributeError): self.trusted_devices = {}
        self.wanted = self.settings.value("receiving", True, type=bool)
        self.sleeping = False
        self.quitting = False
        self.stopping = False
        self.epoch = 0
        self.pending = {}
        self.rows = {}
        self.stdout = bytearray()
        self.last_error = ""
        self.state = "Off"
        self.failures = 0
        self.outbound = None
        self.radio = None
        self.receiver = None
        self.retry = QTimer()
        self.retry.setSingleShot(True)
        self.retry.timeout.connect(self.start)
        self.poll = QTimer()
        self.poll.setInterval(250)
        self.poll.timeout.connect(self.radio_ready)
        self.window_timer = QTimer()
        self.window_timer.setSingleShot(True)
        self.window_timer.timeout.connect(lambda: self.toggle(False))
        self._build_ui()
        self._watch_sleep()
        if start and self.wanted: QTimer.singleShot(500, self.start)

    def _build_ui(self):
        self.window = QDialog()
        self.window.setWindowTitle(APP_NAME)
        self.window.resize(680, 400)
        layout = QVBoxLayout(self.window)
        title = QLabel(APP_NAME)
        font = title.font(); font.setPointSize(23); font.setBold(True); title.setFont(font)
        header = QHBoxLayout(); header.addWidget(title); header.addStretch()
        gear = QPushButton("Settings")
        gear.setIcon(QIcon.fromTheme("configure")); gear.setToolTip("Device name and security settings")
        gear.clicked.connect(self.open_settings); header.addWidget(gear)
        layout.addLayout(header)
        self.subtitle = QLabel(f"Visible as {self.name}")
        self.subtitle.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.subtitle)
        self.status = QLabel("Off")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(["Sender", "Files", "Status"])
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnWidth(0, 150); self.table.setColumnWidth(1, 270)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        send = QPushButton("Send files…")
        send.clicked.connect(self.send_files)
        accept = QPushButton("Accept selected")
        accept.clicked.connect(lambda: self.answer_selected(True))
        decline = QPushButton("Decline selected")
        decline.clicked.connect(lambda: self.answer_selected(False))
        folder = QPushButton("Open download folder")
        folder.clicked.connect(self.open_folder)
        buttons.addWidget(send); buttons.addWidget(accept); buttons.addWidget(decline); buttons.addStretch(); buttons.addWidget(folder)
        layout.addLayout(buttons)
        trust = QPushButton("Trust selected device…"); trust.clicked.connect(self.trust_selected)
        layout.addWidget(trust)
        ask = QPushButton("Ask AI about files…"); ask.clicked.connect(self.ask_files)
        layout.addWidget(ask)
        self.destination = QLabel(str(self.directory))
        self.destination.setTextFormat(Qt.TextFormat.PlainText)
        self.destination.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.destination)
        note = QLabel("Incoming transfers need your approval. Closing this window keeps AirDrop in the tray.")
        note.setWordWrap(True); layout.addWidget(note)
        self.tray = QSystemTrayIcon(self.icon("Off"), self.app)
        menu = QMenu()
        self.menu_status = menu.addAction("AirDrop: Off"); self.menu_status.setEnabled(False)
        self.enabled = QAction("Receive AirDrop", menu)
        self.enabled.setCheckable(True); self.enabled.setChecked(self.wanted)
        self.enabled.triggered.connect(self.toggle); menu.addAction(self.enabled)
        menu.addAction("Receive for 10 minutes", self.ten_minutes)
        menu.addAction("Send files…", self.send_files)
        menu.addSeparator()
        menu.addAction("Ask AI about files…", self.ask_files)
        menu.addAction("Transfers…", self.show)
        menu.addAction("Settings…", self.open_settings)
        menu.addAction("Open download folder", self.open_folder)
        menu.addAction("Choose download folder…", self.choose_folder)
        self.login = QAction("Start at login", menu)
        self.login.setCheckable(True); self.login.setChecked(AUTOSTART.exists())
        self.login.triggered.connect(self.set_autostart); menu.addAction(self.login)
        menu.addSeparator(); menu.addAction("Quit", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda why: self.show() if why in (
            QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self.tray.show()
        self.set_state("Off")

    @staticmethod
    def icon(state):
        colors = {"Ready":"#38b87c", "Receiving":"#56a8ff", "Starting":"#e3ac48", "Error":"#ef6464"}
        image = QPixmap(str(INSTALL / "assets/aibitdrop.png")).scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        if image.isNull():
            image = QPixmap(48, 48); image.fill(Qt.GlobalColor.transparent)
        p = QPainter(image); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(colors.get(state, "#8b929a")))
        p.drawEllipse(35, 35, 12, 12); p.end()
        return QIcon(image)

    def set_state(self, state, detail=""):
        self.state = state
        text = f"AirDrop: {state}" + (f" — {clean(detail, 350)}" if detail else "")
        self.status.setText(text); self.menu_status.setText(f"AirDrop: {state}")
        self.tray.setToolTip(text); self.tray.setIcon(self.icon(state))
        LOG.info("%s", text)

    def show(self):
        self.window.show(); self.window.raise_(); self.window.activateWindow()

    def send_files(self):
        if self.outbound and self.outbound.active:
            self.outbound.show(); self.outbound.raise_(); return
        files, _ = QFileDialog.getOpenFileNames(self.window, "Send files to your iPhone", str(Path.home()))
        if not files: return
        if self.outbound: self.outbound.cancel(silent=True); self.outbound.deleteLater()
        if not self.wanted: self.toggle(True)
        self.outbound = SendDialog(self, files)
        self.outbound.show()

    def open_ai_rules(self):
        from ai_panel import ReceiptRulesDialog
        if ReceiptRulesDialog(self.window, self.settings).exec():
            self.ai_receipts.queue.clear()

    def ask_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self.window, "Choose files for AI", str(self.directory))
        if paths: self.ask_ai(paths)

    def ask_ai(self, paths):
        from ai_panel import AskDialog
        AskDialog(self.window, self.settings, paths).exec()

    def open_settings(self):
        SettingsDialog(self).exec()

    def transfer_active(self):
        return bool(self.outbound and self.outbound.active) or any(
            row.text(2) == "Receiving…" for row in self.rows.values())

    def allowed(self, fingerprint):
        if self.policy == "everyone": return True
        return self.policy == "trusted" and fingerprint in self.trusted_devices

    def save_trusted_devices(self):
        self.settings.setValue("trusted_devices", json.dumps(self.trusted_devices))
        self.settings.sync()

    def trust_selected(self):
        row = self.table.currentItem()
        if not row: return
        fingerprint = row.data(0, Qt.ItemDataRole.UserRole+1)
        if not fingerprint or row.text(2) != "Received":
            QMessageBox.information(self.window, APP_NAME,
                "Select a successfully received transfer from a device that supplied a TLS certificate. Unverified names cannot be added as trusted devices.")
            return
        box = QMessageBox(self.window)
        box.setWindowTitle("Trust this device?")
        box.setIcon(QMessageBox.Icon.Question)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(f"Trust the device from this received transfer?\n\nLabel: {row.text(0)}\nCertificate SHA-256:\n{fingerprint}\n\nConfirm this was your intended device. Its display name is not a verified contact identity. Future transfers will still require approval.")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        response = box.exec()
        if response == QMessageBox.StandardButton.Yes:
            self.trusted_devices[fingerprint] = clean(row.text(0))
            self.save_trusted_devices()
            self.notify.notify("Trusted device added", "You can enable Trusted devices only in Settings.")

    def apply_settings(self, name, policy, trusted):
        changed = name != self.name
        self.name = name
        self.policy = policy if policy in ("everyone", "trusted", "blocked") else "blocked"
        self.trusted_devices = {fp:clean(label) for fp,label in trusted.items()
            if isinstance(fp,str) and re.fullmatch(r"[0-9a-f]{64}", fp)}
        self.settings.setValue("name", name); self.settings.setValue("incoming_policy", self.policy)
        self.save_trusted_devices()
        self.subtitle.setText(f"Visible as {self.name}")
        for key, pending in list(self.pending.items()):
            if not self.allowed(pending.get("fingerprint")): self.answer(key, False)
        if changed and self.wanted:
            self.stop(); self.start()
        elif self.state == "Ready": self.set_state("Ready", f"Visible as {self.name}")

    def open_folder(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.directory)))

    def choose_folder(self):
        chosen = QFileDialog.getExistingDirectory(self.window, "Save incoming AirDrop files to", str(self.directory))
        if not chosen: return
        if any(row.text(2) == "Receiving…" for row in self.rows.values()):
            QMessageBox.information(self.window, APP_NAME, "Wait for the current transfer to finish before changing folders.")
            return
        self.directory = Path(chosen); self.settings.setValue("directory", chosen)
        self.destination.setText(chosen)
        if self.wanted: self.stop(); self.start()

    def set_autostart(self, enabled):
        try:
            if enabled:
                AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
                AUTOSTART.write_text(desktop_entry())
            else: AUTOSTART.unlink(missing_ok=True)
        except OSError as exc:
            self.login.setChecked(not enabled)
            self.notify.notify("Could not change login startup", str(exc))

    def ten_minutes(self):
        self.toggle(True); self.window_timer.start(600000)

    def toggle(self, enabled):
        self.wanted = bool(enabled)
        self.enabled.setChecked(self.wanted)
        self.settings.setValue("receiving", self.wanted); self.settings.sync()
        self.window_timer.stop()
        if self.wanted: self.start()
        else: self.stop(); self.set_state("Off")

    def start(self):
        if not self.wanted or self.sleeping or self.quitting: return
        if self.radio and self.radio.state() != QProcess.ProcessState.NotRunning: return
        self.retry.stop(); self.last_error = ""; self.stdout.clear()
        try: self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc: self.fail(str(exc), retry=False); return
        self.set_state("Starting")
        self.radio = QProcess(self.app)
        self.radio.readyReadStandardError.connect(lambda: self.read_error(self.radio))
        self.radio.readyReadStandardOutput.connect(lambda: self.radio.readAllStandardOutput())
        self.radio.finished.connect(lambda *_: self.process_ended("radio"))
        self.radio.errorOccurred.connect(lambda error: self.fail("Could not launch Owly radio", retry=False)
            if error == QProcess.ProcessError.FailedToStart else None)
        self.radio.start("/usr/bin/owly", ["radio", "up"])
        self.started_at = time.monotonic(); self.poll.start()

    def read_error(self, process):
        if process is None: return
        data = bytes(process.readAllStandardError()).decode("utf-8", "replace")
        if data.strip():
            self.last_error = clean(data, 500)
            LOG.info("Owly: %s", self.last_error)

    @staticmethod
    def link_ready():
        try:
            return any(line.split()[-1] == "awdl0" and line.startswith("fe80")
                for line in Path("/proc/net/if_inet6").read_text().splitlines())
        except OSError: return False

    def radio_ready(self):
        if not self.radio or self.radio.state() == QProcess.ProcessState.NotRunning: return
        if not self.link_ready():
            if time.monotonic() - self.started_at > 25:
                self.fail(self.last_error or "Radio startup timed out")
            return
        self.poll.stop()
        self.epoch += 1
        self.receiver = QProcess(self.app)
        self.receiver.readyReadStandardOutput.connect(self.read_events)
        self.receiver.readyReadStandardError.connect(lambda: self.read_error(self.receiver))
        self.receiver.finished.connect(lambda *_: self.process_ended("receiver"))
        self.receiver.errorOccurred.connect(lambda error: self.fail("Could not launch AirDrop receiver", retry=False)
            if error == QProcess.ProcessError.FailedToStart else None)
        self.receiver.start(self.helper, ["receive", "--json-events", "--name", self.name, "--dir", str(self.directory)])

    def read_events(self):
        self.stdout.extend(bytes(self.receiver.readAllStandardOutput()))
        if len(self.stdout) > 2 * 1024 * 1024:
            self.fail("Receiver event exceeded size limit", retry=False); return
        while b"\n" in self.stdout:
            line, _, rest = self.stdout.partition(b"\n"); self.stdout = bytearray(rest)
            try: self.handle_event(json.loads(line))
            except (ValueError, KeyError, TypeError): LOG.warning("Invalid receiver event")

    def handle_event(self, event):
        kind = event["event"]
        if kind == "ready":
            self.failures = 0; self.set_state("Ready", f"Visible as {self.name}"); return
        key = (self.epoch, int(event["id"]))
        if kind == "request":
            fingerprint = event.get("fingerprint")
            if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint): fingerprint = None
            if not self.allowed(fingerprint):
                if self.receiver and self.receiver.state() == QProcess.ProcessState.Running:
                    self.receiver.write((json.dumps({"id":key[1],"accept":False})+"\n").encode())
                LOG.info("Incoming request refused by policy")
                return
            sender = clean(event.get("sender")) or "Nearby device"
            names = [clean(f.get("name"), 120) for f in event.get("files", [])[:10]]
            description = ", ".join(names) if names else "Shared link"
            item = QTreeWidgetItem([sender, description, "Awaiting approval"])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            item.setData(0, Qt.ItemDataRole.UserRole+1, fingerprint)
            self.table.insertTopLevelItem(0, item); self.table.setCurrentItem(item)
            self.rows[key] = item
            timer = QTimer(self.app); timer.setSingleShot(True)
            timer.timeout.connect(lambda k=key: self.expire(k))
            self.pending[key] = {"timer":timer, "notification":None, "fingerprint":fingerprint}
            timer.start(15000)
            nid = self.notify.notify("Incoming AirDrop", f"{sender} wants to send {description}", {
                "accept":("Accept", lambda k=key: self.answer(k, True)),
                "decline":("Decline", lambda k=key: self.answer(k, False)),
                "default":("Show transfers", self.show)}, timeout=15000)
            self.pending[key]["notification"] = nid
            if nid is None: self.show()
            self.prune_rows()
        elif kind == "answered":
            self.clear_pending(key)
            if key in self.rows: self.rows[key].setText(2, "Receiving…" if event["accepted"] else "Declined")
            self.refresh_state()
        elif kind == "withdrawn": self.expire(key, "Expired or withdrawn")
        elif kind == "failed":
            self.clear_pending(key)
            if key in self.rows: self.rows[key].setText(2, "Failed")
            self.notify.notify("AirDrop transfer failed", clean(event.get("reason"), 350))
            self.refresh_state()
        elif kind in ("received", "urls"):
            self.clear_pending(key)
            if kind == "urls":
                # Shared URLs remain inert text until the user opens the file.
                urls = event.get("urls", [])
                path = self.directory / f"AirDrop-links-{time.time_ns()}.txt"
                path.write_text("\n".join(str(u) for u in urls)[:65536], encoding="utf-8")
                paths = [str(path)]
            else: paths = event.get("paths", [])
            if key in self.rows: self.rows[key].setText(2, "Checking files…")
            self.check_paths(paths, lambda results, k=key, t=kind: self.receipt_checked(k, t, results))
            self.refresh_state()

    def check_paths(self, paths, callback, prepare_open=False):
        if len(self.security_queue) >= 20:
            self.notify.notify("File checks busy", "Checks were not completed. Opening and AI are blocked; try again later.")
            return
        self.security_queue.append((list(paths), callback, prepare_open))
        self.next_check()

    def next_check(self):
        if self.security_worker or not self.security_queue: return
        from file_safety import CheckWorker
        paths, callback, prepare_open = self.security_queue.pop(0)
        worker = CheckWorker(paths, self.settings.value("clamav_enabled", False, type=bool), prepare_open)
        self.security_worker = worker
        self.app.aboutToQuit.connect(worker.wait)
        worker.checked.connect(callback)
        worker.finished.connect(self.check_finished)
        worker.start()

    def check_finished(self):
        old = self.security_worker; self.security_worker = None
        old.deleteLater(); QTimer.singleShot(0, self.next_check)

    def receipt_checked(self, key, kind, results):
        paths = [path for path, passed, _ in results if passed]
        blocked = [reason for _, passed, reason in results if not passed]
        if key in self.rows: self.rows[key].setText(2, "Received" if paths and not blocked else "Blocked / check failed" if not paths else "Partially blocked")
        if blocked: self.notify.notify("File blocked", clean("; ".join(blocked), 700))
        if paths:
            body = ", ".join(clean(Path(p).name, 120) for p in paths[:5]) + " — " + next(message for _, passed, message in results if passed)
            self.notify.notify("ai.BitDrop received — checks passed", body, {
                "open": ("Open file", lambda p=paths[0]: self.open_checked(p)),
                "folder": ("Show in folder", self.open_folder),
                "ai": ("Ask AI…", lambda p=list(paths): self.ask_ai(p))})
            if kind == "received": self.ai_receipts.receive(key, paths, self.directory)
        self.refresh_state()

    def open_checked(self, path):
        def ready(results):
            if results and results[0][1]: QDesktopServices.openUrl(QUrl.fromLocalFile(results[0][0]))
            else: self.notify.notify("File blocked", clean(results[0][2] if results else "No file checked", 700))
        self.check_paths([path], ready, prepare_open=True)

    def answer_selected(self, accepted):
        item = self.table.currentItem()
        if item: self.answer(tuple(item.data(0, Qt.ItemDataRole.UserRole)), accepted)

    def answer(self, key, accepted):
        if key not in self.pending or key[0] != self.epoch: return
        if self.receiver is None or self.receiver.state() != QProcess.ProcessState.Running: return
        if accepted and not self.allowed(self.pending[key].get("fingerprint")): accepted = False
        command = json.dumps({"id":key[1], "accept":bool(accepted)}) + "\n"
        self.receiver.write(command.encode())
        self.clear_pending(key)
        self.rows[key].setText(2, "Receiving…" if accepted else "Declined")
        self.refresh_state()

    def clear_pending(self, key):
        entry = self.pending.pop(key, None)
        if entry:
            entry["timer"].stop(); entry["timer"].deleteLater()
            self.notify.close(entry["notification"])

    def expire(self, key, status="Expired"):
        if key not in self.pending: return
        if self.receiver and self.receiver.state() == QProcess.ProcessState.Running:
            self.receiver.write((json.dumps({"id":key[1], "accept":False}) + "\n").encode())
        self.clear_pending(key)
        if key in self.rows: self.rows[key].setText(2, status)

    def refresh_state(self):
        if any(row.text(2) == "Receiving…" for row in self.rows.values()): self.set_state("Receiving")
        else: self.set_state("Ready", f"Visible as {self.name}")

    def prune_rows(self):
        # Keep at most 100 completed transfers in memory; never remove a live request.
        for index in range(self.table.topLevelItemCount()-1, 99, -1):
            item = self.table.topLevelItem(index); key = tuple(item.data(0, Qt.ItemDataRole.UserRole))
            if key not in self.pending and item.text(2) != "Receiving…":
                self.rows.pop(key, None); self.table.takeTopLevelItem(index)

    def process_ended(self, source):
        if self.stopping or self.quitting or self.sleeping or not self.wanted: return
        self.fail(self.last_error or f"AirDrop {source} stopped")

    def fail(self, reason, retry=True):
        self.stop()
        self.failures += 1
        self.set_state("Error", reason)
        if self.failures == 1: self.notify.notify("AirDrop needs attention", reason, {"default":("Details", self.show)})
        # Authorization failures need a deliberate retry, not repeated password prompts.
        auth_error = any(s in reason.lower() for s in ("denied", "authoriz", "authentication", "busy"))
        if retry and not auth_error and self.wanted and not self.sleeping:
            self.retry.start(min(60000, 3000 * 2**min(self.failures-1, 4)))

    def stop(self):
        self.stopping = True
        if self.outbound: self.outbound.cancel(silent=True)
        self.retry.stop(); self.poll.stop()
        for key in list(self.pending):
            self.clear_pending(key)
            self.rows[key].setText(2, "Stopped")
        for row in self.rows.values():
            if row.text(2) == "Receiving…": row.setText(2, "Interrupted")
        for process in (self.receiver, self.radio):
            if process and process.state() != QProcess.ProcessState.NotRunning:
                process.terminate()
                if not process.waitForFinished(1500): process.kill(); process.waitForFinished(500)
            if process: process.deleteLater()
        self.receiver = None; self.radio = None; self.stdout.clear()
        self.stopping = False

    def _watch_sleep(self):
        try:
            import dbus
            self.system_bus = dbus.SystemBus()
            self.system_bus.add_signal_receiver(self.prepare_sleep,
                signal_name="PrepareForSleep", dbus_interface="org.freedesktop.login1.Manager",
                bus_name="org.freedesktop.login1")
        except Exception: LOG.warning("Sleep notifications unavailable")

    def prepare_sleep(self, sleeping):
        self.sleeping = bool(sleeping)
        if self.sleeping: self.stop(); self.set_state("Paused", "Computer is sleeping")
        elif self.wanted: self.retry.start(3000)

    def quit(self):
        self.quitting = True; self.stop(); self.tray.hide(); self.app.quit()


def desktop_entry():
    return ("[Desktop Entry]\nType=Application\nName=ai.BitDrop\n"
        "Comment=Receive AirDrop files with desktop notifications\n"
        f"Exec=/usr/bin/python3 {INSTALL}/owly_tray.py\nIcon=aibitdrop\n"
        "Terminal=false\nCategories=Network;FileTransfer;\n"
        "Keywords=AirDrop;Owly;iPhone;Receive;\nX-KDE-autostart-after=panel\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1]); app.setApplicationName(APP_ID)
    app.setWindowIcon(QIcon(str(INSTALL / "assets/aibitdrop.png")))
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable() and not args.smoke_test:
        QMessageBox.critical(None, APP_NAME, "A desktop system tray is required."); return 1
    server_name = f"owly-tray-{os.getuid()}"
    socket = QLocalSocket(); socket.connectToServer(server_name)
    if socket.waitForConnected(300):
        socket.write(b"show\n"); socket.waitForBytesWritten(300); return 0
    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    if not server.listen(server_name): return 1
    state = Path.home() / ".local/state/owly-tray"; state.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(state/"app.log", maxBytes=512000, backupCount=2)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(handler); LOG.setLevel(logging.INFO)
    notifications = Notifications()
    tray = TrayApp(app, notifications, start=not args.smoke_test)
    def incoming():
        connection = server.nextPendingConnection()
        tray.show()
        if connection: connection.deleteLater()
    server.newConnection.connect(incoming)
    signal.signal(signal.SIGTERM, lambda *_: tray.quit())
    signal.signal(signal.SIGINT, lambda *_: tray.quit())
    tick = QTimer(); tick.timeout.connect(lambda: None); tick.start(250)
    if args.smoke_test:
        tray.show()
        notifications.notify("Owly AirDrop is ready", "The tray app and desktop notifications are working.")
        QTimer.singleShot(1500, tray.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
