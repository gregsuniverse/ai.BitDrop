# ai.BitDrop

<img src="assets/icons/128x128/apps/aibitdrop.png" alt="ai.BitDrop Quantum Drop icon" width="128" height="128">

**MIT licensed · KDE desktop · Nearby file transfer · Optional AI workflows**

A personal KDE tray app for sending files to an iPhone and receiving files from
nearby Apple devices using the AirDrop protocol. Optional AI analysis is available after receiving files.

The Python/Qt frontend provides a tray menu, desktop notifications with
Accept/Decline actions, a device picker, outbound progress/cancellation,
completion notifications, editable device names, certificate-pinned trusted
devices, login startup, and recovery after sleep. The existing
Owly radio service handles AWDL; this app does not replace its system package.

## Install

Download the [v0.1.2 development release](https://github.com/gregsuniverse/ai.BitDrop/releases/tag/v0.1.2). Packages are unsigned and currently x86_64 only.

### Fedora KDE (dnf / rpm)

Download and extract [the Fedora bundle](https://github.com/gregsuniverse/ai.BitDrop/releases/download/v0.1.2/aibitdrop-fedora-x86_64.zip), then run this inside the extracted folder:

```sh
sudo dnf install ./owly-0.4.2-2.aibitdrop.x86_64.rpm ./aibitdrop-0.1.2-1.x86_64.rpm
```

DNF resolves dependencies. Direct `rpm -Uvh` also works if dependencies are already installed. This package pair passed a Fedora 45 dependency-resolution dry run; a fresh native installation has not been tested.

### Debian 13 / compatible systems (apt)

Download and extract [the Debian bundle](https://github.com/gregsuniverse/ai.BitDrop/releases/download/v0.1.2/aibitdrop-debian-x86_64.zip), then run:

```sh
sudo apt install ./owly_0.4.2-1+aibitdrop1_amd64.deb ./aibitdrop_0.1.2-1_amd64.deb
```

Debian package contents are validated, but installation has not been tested on Debian. These binaries need glibc 2.39 or newer and the declared PySide6 packages. This is not a hosted apt/dnf repository; use the downloaded files.

### First run

Open **ai.BitDrop** from the application menu, or run `aibitdrop`. On a fresh firewalld system, run `sudo aibitdrop-setup-firewall` to permit receiving on `awdl0`. Choose **Settings → Visible as**, enable receiving, and wait for **Ready**. Turn on **Start at login** in the tray menu if desired.

Use the migration notes below if you previously installed the per-user version. A supported Wi-Fi adapter, NetworkManager, and a logged-in desktop session are required. ai.BitDrop is experimental and is not affiliated with Apple.

## Usage

- **Receive:** iPhone Share → AirDrop → your computer; click Accept in the KDE notification.
- **Send:** tray menu → Send files… → select files → choose your unlocked iPhone → Send. Set the phone to Everyone for 10 Minutes.
- **AI:** Settings → Connect AI, then Ask AI about files. Automatic file-type rules are a separate, explicit opt-in.
- **Background:** closing the window keeps the tray app running; Quit stops it.

Read the [full usage guide](USAGE.md) for security modes, custom AI prompts, automatic processing, troubleshooting, data locations and removal.

## Requirements

- Fedora KDE with a supported Wi-Fi adapter, working Owly installation, and `owlyd`.
- Python 3 with PySide6, dbus-python, and PyGObject/GLib.
- Rust 1.88 or newer, Cargo, Git, and a C compiler to build the helper.
- TCP 8771 and mDNS permitted on `awdl0` for receiving. Existing machine firewall
  configuration is not changed by this installer.

On Fedora, runtime Python dependencies can be installed through DNF:

```bash
sudo dnf install python3-pyside6 python3-dbus python3-gobject
```

Owly's hardware support, radio requirements and installation instructions are at
[t4t5/owly](https://github.com/t4t5/owly). Shared-mode operation depends on the
adapter and access point channel. Installing this frontend alone does not make an
unsupported adapter compatible.

## Build and install

```bash
bash scripts/build-helper.sh
python3 install.py
```

The build fetches the exact Owly revision recorded in the script and applies
`patches/desktop-events.patch`. Cargo uses the upstream lockfile. The binary is
generated locally and excluded from Git.

The installer writes only to the current user's profile. It installs into
`~/.local/share/owly-tray`, adds application-menu/login entries, and backs up
existing launchers. It does not replace `/usr/bin/owly` or alter radio settings.
Internal install paths are retained for compatibility with existing settings and launchers.

Launch **ai.BitDrop** from the application menu. See [README.txt](README.txt)
for use, data locations, and uninstall instructions.

## Tests

Frontend tests use mock notifications/processes and need no iPhone or radio:

```bash
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -v -p 'test_*.py'
```

With an already-active `awdl0`, the following integration tests use generated
files and separate local TLS receivers. They do not send files to a phone:

```bash
python3 test_receiver_protocol.py
python3 test_send_protocol.py
```

An actual iPhone is still needed to validate over-the-air discovery and transfer
on a particular adapter. A full upload is not reported as delivered until the
receiver confirms completion. Transfer speed improvements are deferred.

## Release bundle

```bash
python3 scripts/package-release.py
```

This produces an x86_64 Linux ZIP under `dist/` containing source, the locally
built helper, tests, installer, and third-party notices. No settings, received
files, logs, credentials or compiled caches are included. Review a bundle before
publishing it. Build outputs and release archives are excluded from Git.

## Upstream and license

The helper is built from Owly commit
`6f2e8ea99aed0687558d78a1dd49154ab3a5fa76` with the included desktop-event patch.
Owly's MIT license is retained in [LICENSE.owly](LICENSE.owly); see
[THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt).

The app is an independent project and is not affiliated with Apple. ai.BitDrop is licensed under the [MIT License](LICENSE).

## Incoming-transfer security

Settings offers Everyone (manual approval), Trusted devices only (manual
approval), and Block all incoming transfers. A trusted device is identified by
the SHA-256 fingerprint of the client certificate proven during its TLS
handshake. Display names never authorize a transfer. Missing or unknown
certificates fail closed in trusted-device mode. Enrollment is an explicit
action after a successful manually approved transfer. Verify the physical
sender before enrolling; the pin identifies a key, not an Apple contact.
Certificate changes require reenrollment. Restrictions do not hide the receiver
from discovery. Apple-signed contact record validation and email/phone matching
are not implemented.

## Native packages (initial x86_64 release)

ai.BitDrop is MIT licensed. The RPM and Debian packages include LICENSE and
LICENSE.owly. The backend is packaged separately as `owly`; the desktop package
declares it and its Python/Qt dependencies so the package manager checks them.

Download the matching pair of packages into the same folder. On Fedora:

```sh
sudo dnf install ./owly-0.4.2-2.aibitdrop.x86_64.rpm ./aibitdrop-0.1.2-1.x86_64.rpm
```

On Debian 13 (trixie), or a compatible distribution with the listed PySide6
packages available:

```sh
sudo apt install ./owly_0.4.2-1+aibitdrop1_amd64.deb ./aibitdrop_0.1.2-1_amd64.deb
```

Direct RPM installation is also supported if dependencies are already installed:

```sh
sudo rpm -Uvh ./owly-0.4.2-2.aibitdrop.x86_64.rpm ./aibitdrop-0.1.2-1.x86_64.rpm
```

If migrating from the earlier per-user installer, its local launcher overrides
the system launcher. Back up or remove `~/.local/share/applications/owly-tray.desktop`
and `~/.local/bin/aibitdrop` after installing the native package. For existing
login startup, toggle **Start at login** off and on from the packaged app
(`/usr/bin/aibitdrop`). Settings and downloaded files are shared and preserved.

Launch **ai.BitDrop**, or run `aibitdrop`. Enable **Start at login** in its tray
menu if desired. Installation does not start a user app as root, copy API keys,
or change firewall policy. On a fresh firewalld system, explicitly run
`sudo aibitdrop-setup-firewall` to allow mDNS and TCP 8771 on awdl0 only.
Other firewalls need equivalent rules. A supported Wi-Fi adapter is still required.

These are local package files, not yet a hosted apt/dnf repository. They are
unsigned development builds. Current binaries require glibc 2.39 or newer;
RPM discovers native library dependencies, and the Debian builder reads the
ELF version requirements. Older systems need a native rebuild. Debian package
contents are checked here, but Debian installation and real hardware use have
not yet been tested. Fedora dependency resolution is checked without installing.

### Building packages

Install `rpm-build` for RPM, or `dpkg`/`binutils` for Debian packages. Build the
helper with `bash scripts/build-helper.sh`, then run:

```sh
python3 scripts/build-packages.py rpm
python3 scripts/build-packages.py deb
```

To also produce the companion backend packages, provide the same pinned Owly
source checkout used for the helper, with `owly` and `owlyd` compiled under
`target/release` (use `cargo build --release --locked -p owlyd -p owly-cli`):

```sh
python3 scripts/build-packages.py all --owly-source /absolute/path/to/owly
```

Build on the target distribution for release validation. Outputs land in `dist/`.
Package removal leaves user settings, downloads and API keys intact; use
**Disconnect** in AI settings first if you want the saved key deleted.

## Ask AI

Choose **Ask AI…** in a completion notification, or **Ask AI about files…** in the tray menu. Settings → Connect AI saves an OpenAI API key in `~/.config/aiBitDrop/openai-key` with owner-only permissions. No key is included in the repository or release bundle. Disconnect deletes the saved key. Connection saving does not validate credentials.

The panel lists the upload destination and exact file paths. **Send to OpenAI** submits manual requests; receiving uploads automatically only when you explicitly enable AI-on-receipt rules. API charges may apply. Supported inputs: PDF, common documents, spreadsheets, text and PNG/JPEG/WebP/GIF images, totaling at most 20 MB. Audio/video and local-model support are not yet implemented. Results are displayed as plain text and can be saved explicitly. Requests use the Responses API with `store: false`; this is not a claim of zero provider retention.

Implementation follows [OpenAI file-input documentation](https://developers.openai.com/api/docs/guides/file-inputs). Default model is configurable (`gpt-4.1-mini`).

Repository name: `gregsuniverse/ai.BitDrop`. Launch command: `aibitdrop`.

## AI on receipt

In Settings, choose **AI on receipt — file types and prompts…**. Add a file type, set its custom prompt, and enable the master automatic-processing option. Enabling requires an AI connection and confirmation that matching files from future accepted transfers are uploaded automatically to OpenAI; API charges may apply. Nothing is enabled by installation or upgrade.

Images, PDFs, office documents, spreadsheets and text each have their own rule. Only matching files from a completed transfer are sent, grouped by rule, with a 20 MB limit per request. Other types and shared URL events are skipped. There is no folder watcher or processing of old downloads. Duplicate completion events are suppressed. Jobs run one at a time, with up to 20 queued jobs and no automatic retries or replay after restart. Saving changed rules clears queued work; already-started uploads finish. Disconnecting disables automatic processing.

Answers are saved as private text files in **AI results** under the download folder, with an **Open answer** notification. Originals are preserved. HEIC, audio and video are not supported yet; use JPEG/PNG images for these rules.

App icon: Quantum Drop, selected by Greg; original artwork and desktop sizes are in `assets/`.
