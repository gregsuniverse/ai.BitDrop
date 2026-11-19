# Using ai.BitDrop

See [README.md](README.md#install) for installation. ai.BitDrop runs in a logged-in
KDE desktop session; no companion iPhone app is required.

## First launch

1. Open **ai.BitDrop** from the application menu, or run `aibitdrop`.
2. Open **Settings** and set **Visible as** to the computer name you want on your phone.
3. Keep **Everyone — ask before receiving** for initial setup, or choose a more restrictive mode below.
4. Wait for **Ready**. If receiving is off, turn on **Receive AirDrop** in the tray menu.
5. Enable **Start at login** in the tray menu if desired. Closing the transfers window leaves the tray app running; **Quit** stops it and releases its radio lease.

Your phone needs Wi-Fi and Bluetooth enabled. Nearby discovery depends on the
Wi-Fi adapter and the Owly radio service. ai.BitDrop cannot make unsupported
hardware compatible. A notification permission prompt from the desktop must
be allowed for incoming-transfer notifications to appear.

## Receive from iPhone

1. Select a photo or file on your iPhone, then choose **Share → AirDrop**.
2. Select the computer name shown by ai.BitDrop.
3. Click **Accept** in the desktop notification, or select the transfer in the app and click **Accept selected**. Unanswered requests expire after 15 seconds.
4. Wait for completion. The notification offers **Open file**, **Show in folder**, and **Ask AI…**.

Files default to `~/Downloads/AirDrop`. Choose **Choose download folder…** in
the tray menu to change this. Shared URLs are saved as text rather than opened
automatically. **Receive for 10 minutes** turns receiving off after that period.

## Send to iPhone

1. On your iPhone, set AirDrop receiving to **Everyone for 10 Minutes**, and keep it unlocked.
2. Choose **Send files…** from the tray menu or transfers window and select files.
3. Pick your iPhone from the nearby-device list; use **Refresh** if needed.
4. Press **Send**, then accept on the phone.

Progress reaching 100% means the upload finished; success is shown only after
the receiver confirms delivery. **Cancel** stops the outgoing transfer while
background receiving remains available. Closing the send window during a
transfer lets it continue in the background.

## Device and security settings

| Setting | Behavior |
| --- | --- |
| Visible as | Changes the computer name advertised to nearby devices. |
| Everyone | Asks before accepting each incoming transfer. |
| Trusted devices only | Asks for approval only when the sender proves a pinned TLS certificate; unknown or missing certificates are refused. |
| Block all incoming transfers | Refuses incoming requests. |

To enroll a trusted device, receive a transfer in Everyone mode, select its
completed row, and click **Trust selected device…**. Confirm the physical device
before trusting its certificate. Remove devices from the trusted list in Settings.
An empty trusted list refuses all requests in trusted-device mode.

Display names are supplied by devices and are not verified identities. A trusted
certificate identifies a key, not an Apple contact. A changed certificate needs
to be trusted again. This is not Apple's Contacts Only mode, and restricting
requests does not necessarily hide the computer from discovery. Wait for an
active file transfer to finish before changing device/security settings.

## Connect AI

AI is optional; file transfers work without it.

1. Open **Settings → Connect AI…**.
2. Enter your OpenAI API key and a model name. The default is `gpt-4.1-mini`.
3. Choose **Save connection**. Saving does not validate the key; the first request reports connection, billing or access errors.

The key is stored locally with owner-only file permissions, outside the repository.
Never paste API keys into issues or commit them. OpenAI API usage may incur
charges. **Disconnect and delete saved key** removes it and disables automatic
processing. Local models and other providers are not implemented yet.

### Ask AI manually

Use **Ask AI…** in a received-file notification, or **Ask AI about files…** in
the tray menu/transfers window. Review the full file list and OpenAI upload
destination, type your prompt (or choose a suggestion), then click **Send to
OpenAI**. The answer appears as plain text; **Save answer…** saves it locally.

Supported inputs total at most 20 MB per request: PDF, TXT/Markdown/JSON,
CSV/XLSX, DOCX/PPTX/RTF/ODT, and PNG/JPEG/WebP/GIF. HEIC, audio and video are
not supported yet. Use JPEG/PNG exports for iPhone images when needed.

### Automatically process files on receipt

1. Open **Settings → AI on receipt — file types and prompts…**.
2. Choose a file type and click **Add file type**.
3. Enter its custom prompt and check **Enable selected rule**.
4. Repeat for other types if needed. Each type has its own prompt.
5. Enable **Automatically process matching files with AI on receipt**, save, and confirm automatic uploads to OpenAI.

For example, Images can use “Extract receipt totals and dates,” while PDF
documents use “Summarize the main findings and list action items.”

Automatic processing is off by default. When enabled, matching files from future
accepted, completed transfers are uploaded without another upload confirmation.
It does not accept incoming transfers for you, scan old downloads, or watch a
folder. Files are grouped by rule; unmatched files and shared-URL events are
skipped. Jobs run sequentially with a 20-job queue and no automatic retries or
replay after restart. Oversized requests report an error rather than uploading.

Answers are private text files under **AI results** in the chosen download folder;
completion notifications offer **Open answer**. Original files are preserved.
Saving rule changes clears queued jobs. Turning processing off stops queued
work; a request already sent finishes. Provider requests use `store: false`,
which is not a guarantee of zero provider retention.

## Troubleshooting

- **No computer on the phone:** confirm receiving is on and the app says Ready. Keep phone Wi-Fi/Bluetooth enabled and try discovery again. Run `owly doctor` to inspect radio support. Check [Owly's hardware guidance](https://github.com/t4t5/owly).
- **No iPhone in the sender list:** unlock the phone, enable Everyone for 10 Minutes, and Refresh. Discovery can take a little time.
- **Firewall blocks receiving:** firewalld users can explicitly run `sudo aibitdrop-setup-firewall`. It allows mDNS and TCP 8771 on `awdl0` only and preserves an existing zone assignment. Other firewalls need equivalent rules.
- **Requests are refused:** check incoming policy and trusted certificates. Trusted-only with no trusted entries refuses everyone.
- **No notification:** open the transfers window for Accept/Decline; check KDE notification settings and Do Not Disturb.
- **AI fails:** check the API key, provider billing, model access, supported types and the 20 MB limit. Failed jobs are not retried automatically. Use Ask AI to retry explicitly.
- **Slow transfers:** Wi-Fi/card/channel conditions affect throughput; performance work is ongoing. Do not confuse upload progress with confirmed delivery.

## Local data and removal

| Data | Location |
| --- | --- |
| Downloads | `~/Downloads/AirDrop` by default, or your chosen folder |
| Automatic AI answers | `AI results` inside the download folder |
| Settings and rules | `~/.config/OwlyTray/OwlyTray.conf` |
| OpenAI key | `~/.config/aiBitDrop/openai-key` |
| Rotating application log | `~/.local/state/owly-tray/app.log` |
| Per-user installation | `~/.local/share/owly-tray` |
| Native package application | `/usr/libexec/aibitdrop` |

Legacy internal names preserve compatibility. Logs may contain device/transfer
metadata; review and redact them before sharing in an issue.

To remove a native installation, quit the app, optionally disconnect AI to delete
the saved key, then run `sudo dnf remove aibitdrop` or `sudo apt remove aibitdrop`.
The separate Owly package can remain for other applications. Remove login startup
through the tray menu before uninstalling if it was enabled.

For a per-user installation, see [README.txt](README.txt) for the launcher/file
locations. Removing the app does not remove downloads, settings, or API keys.
