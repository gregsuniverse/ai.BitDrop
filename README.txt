ai.BitDrop for KDE

Run ai.BitDrop from the application menu. It stays in the system tray when
the transfers window is closed. Receive AirDrop toggles discoverability.
Incoming transfers require Accept in a desktop notification or the transfers
window. Unanswered requests expire after 15 seconds. Sender names are supplied
by nearby devices and are not verified identities.

The per-user installer enables login startup. Native packages leave it optional.
Toggle Start at login in the tray menu to change this.
Quit stops receiving and releases the radio; your saved receiving preference
is retained for the next launch. Receive for 10 minutes turns receiving off
after ten minutes. The default download folder is ~/Downloads/AirDrop.

To send to iPhone: choose Send files… in the tray menu or transfers window,
select files, choose your iPhone from the nearby-device list, and press Send.
On the iPhone enable AirDrop Everyone for 10 Minutes, keep it unlocked, and
accept the request. Upload reaching 100% is not delivery until the iPhone
confirms it. Cancel send stops only the outgoing transfer.

To receive on Fedora: on iPhone select photos/files, tap Share, then AirDrop,
then the computer name shown in the tray app.
No iPhone app is needed. Keep Wi-Fi and Bluetooth enabled on the phone.

This frontend does not change Owly radio settings or transfer performance.
It uses system /usr/bin/owly and the installed owlyd service for the radio.
The bundled helper is Owly 0.4.2 plus a JSON-event desktop interface. It does
not replace the system Owly package. Background receiving requires a logged-in
desktop session. Sleep recovery and radio retries are automatic; unsupported
router channels or authorization failures are shown in the tray window.

Python dependencies: PySide6, dbus-python, PyGObject (GLib).
User log: ~/.local/state/owly-tray/app.log (rotated).
Settings: ~/.config/OwlyTray/OwlyTray.conf.
Installed app: ~/.local/share/owly-tray/.

Run tests: QT_QPA_PLATFORM=offscreen python3 -m unittest -v test_tray.py
Local TLS integration test (radio must be active): python3 test_receiver_protocol.py
Install/update: python3 install.py

The file receiver and archive validation are provided by Owly's existing
Rust implementation. Shared links are saved as inert text files, never opened
automatically. Notification bodies escape remote markup. AI processing sends selected content to OpenAI only after a manual submission
or through an explicitly enabled AI-on-receipt rule.

Upstream: https://github.com/t4t5/owly
Source snapshot: 6f2e8ea99aed0687558d78a1dd49154ab3a5fa76.
Upstream license is included in LICENSE.owly.
Source changes are included in patches/desktop-events.patch.
Build with upstream sources plus that patch:
  cargo build --release --locked -p owly-cli
Copy target/release/owly to owly-desktop-helper alongside this file.

To uninstall: quit from the tray, remove ~/.config/autostart/owly-tray.desktop,
~/.local/share/applications/owly-tray.desktop, ~/.local/bin/owly-tray,
~/.local/bin/receive-airdrop, ~/.local/bin/aibitdrop, and ~/.local/share/owly-tray.
Received files, logs, and settings are retained.

Device/security settings: use the Settings gear in the transfers window or
Settings in the tray menu. Visible as changes the advertised computer name.
Everyone always asks for approval. Trusted devices only matches pinned TLS
certificate SHA-256 values; missing or unknown certificates are refused. To
enroll, receive a successful transfer in Everyone mode, select its row, and
choose Trust selected device. Verify the device before trusting it. The
computer can remain discoverable while requests are restricted. This is not
Apple Contacts Only; email/phone identity matching is not implemented.

AI: Settings → Connect AI, then Ask AI about files. Uploads require Send to OpenAI or an explicitly enabled AI-on-receipt rule. An OpenAI API key and API billing are required. Documents, spreadsheets and images are supported; audio/video are not yet supported.

Full usage guide: USAGE.md, or https://github.com/gregsuniverse/ai.BitDrop/blob/main/USAGE.md
