#!/usr/bin/env bash
set -euo pipefail

PLIST_LABEL="com.nguyenhieu.macwebkeyboard"
PLIST_DEST="${HOME}/Library/LaunchAgents/${PLIST_LABEL}.plist"

launchctl bootout "gui/$(id -u)" "${PLIST_DEST}" >/dev/null 2>&1 || true
rm -f "${PLIST_DEST}"
echo "✅ Đã gỡ dịch vụ chạy ngầm ${PLIST_LABEL}."
