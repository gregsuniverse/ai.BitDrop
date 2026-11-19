Name: aibitdrop
Version: %{aibitdrop_version}
Release: 1
Summary: KDE nearby file transfers with optional AI analysis
License: MIT
URL: https://github.com/gregsuniverse/ai.BitDrop
Requires: python3 python3-pyside6 python3-dbus python3-gobject owly >= 0.4.2
%global debug_package %{nil}
%global __os_install_post %{nil}
%description
ai.BitDrop runs in the desktop tray, receives and sends nearby files using
Owly, and offers optional, explicitly approved OpenAI file analysis.
%install
cp -a %{aibitdrop_stage}/. %{buildroot}/
%files
/usr/bin/aibitdrop
/usr/bin/aibitdrop-setup-firewall
/usr/libexec/aibitdrop
/usr/share/applications/owly-tray.desktop
/usr/share/doc/aibitdrop
%license /usr/share/licenses/aibitdrop

/usr/share/icons/hicolor/*/apps/aibitdrop.png
