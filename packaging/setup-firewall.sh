#!/bin/sh
# Explicit setup only; package installation never changes firewall policy.
set -eu
command -v firewall-cmd >/dev/null || { echo 'firewalld is not installed; allow mDNS and TCP 8771 on awdl0 with your firewall.' >&2; exit 1; }
zone=$(firewall-cmd --permanent --get-zone-of-interface=awdl0 2>/dev/null || true)
case "$zone" in
  ''|'no zone'|aibitdrop) ;;
  *) echo "awdl0 is already assigned to zone $zone; keeping that configuration. Allow mdns and TCP 8771 there if needed."; exit 0 ;;
esac
if ! firewall-cmd --permanent --get-zones | tr ' ' '\n' | grep -qx aibitdrop; then
  firewall-cmd --permanent --new-zone=aibitdrop
fi
firewall-cmd --permanent --zone=aibitdrop --add-service=mdns
firewall-cmd --permanent --zone=aibitdrop --add-port=8771/tcp
firewall-cmd --permanent --zone=aibitdrop --add-interface=awdl0
firewall-cmd --reload
echo 'ai.BitDrop firewall configured on awdl0 only.'
