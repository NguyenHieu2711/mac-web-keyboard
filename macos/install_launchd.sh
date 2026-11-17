#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"
PLIST_LABEL="com.nguyenhieu.macwebkeyboard"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
PLIST_DEST="${LAUNCH_AGENTS_DIR}/${PLIST_LABEL}.plist"
LOG_DIR="${HOME}/Library/Logs/MacWebKeyboard"

echo "==> [1/4] Kiểm tra môi trường Python trên MacBook..."
if command -v /opt/homebrew/bin/python3 >/dev/null 2>&1; then
  SYS_PYTHON="/opt/homebrew/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  SYS_PYTHON="$(command -v python3)"
else
  echo "❌ Không tìm thấy python3. Hãy cài qua Homebrew: brew install python"
  exit 1
fi

echo "==> [2/4] Khởi tạo virtualenv & cài thư viện tại ${VENV_DIR}..."
"${SYS_PYTHON}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip >/dev/null
"${VENV_DIR}/bin/pip" install -r "${PROJECT_DIR}/requirements.txt"

echo "==> [3/4] Tạo cấu hình chạy ngầm LaunchAgent (${PLIST_DEST})..."
mkdir -p "${LAUNCH_AGENTS_DIR}" "${LOG_DIR}"

sed \
  -e "s|__VENV_PYTHON__|${VENV_DIR}/bin/python|g" \
  -e "s|__SERVER_PY__|${PROJECT_DIR}/server.py|g" \
  -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
  -e "s|__LOG_DIR__|${LOG_DIR}|g" \
  "${PROJECT_DIR}/macos/com.nguyenhieu.macwebkeyboard.plist" > "${PLIST_DEST}"

echo "==> [4/4] Kích hoạt dịch vụ launchd tự chạy cùng macOS..."
launchctl bootout "gui/$(id -u)" "${PLIST_DEST}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_DEST}"
launchctl kickstart -k "gui/$(id -u)/${PLIST_LABEL}"

REAL_PY_EXEC="$("${VENV_DIR}/bin/python" -c 'import os, sys; print(os.path.realpath(sys.executable))')"
PYTHON_APP_BUNDLE="$(echo "${REAL_PY_EXEC}" | sed -E 's|(/Python\.app)/.*|\1|')"

echo ""
echo "=================================================================="
echo "✅ ĐÃ CÀI ĐẶT CHẠY NGẦM THÀNH CÔNG TRÊN MACOS!"
echo "   Server luôn tự bật khi khởi động máy tại cổng 5050."
if command -v tailscale >/dev/null 2>&1; then
  TS_IP="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
  [[ -n "${TS_IP}" ]] && echo "   👉 IP Tailscale nhập vào S24+: ${TS_IP}:5050"
fi
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
[[ -n "${LAN_IP}" ]] && echo "   👉 IP Wi-Fi LAN nhập vào S24+: ${LAN_IP}:5050"
echo ""
echo "⚠️ BẮT BUỘC TRÊN MACOS (nếu gõ chưa ra chữ):"
echo "   Trên Apple Silicon, .venv/bin/python chỉ là symlink nên macOS kiểm tra quyền trên Python.app gốc!"
echo "   1) Hộp thoại cấp quyền Accessibility vừa tự bật trên màn hình Mac -> bấm 'Open System Settings' và gạt BẬT 'Python'."
echo "   2) Nếu không thấy 'Python' trong danh sách Accessibility, kéo thả file dưới đây (vừa mở sẵn trong Finder) vào ô Accessibility:"
echo "      ${PYTHON_APP_BUNDLE}"
echo "   3) Sau khi gạt BẬT xong, chạy lệnh sau để nhận quyền ngay:"
echo "      launchctl kickstart -k gui/$(id -u)/${PLIST_LABEL}"
echo "=================================================================="

IS_TRUSTED="$("${VENV_DIR}/bin/python" -c 'import ctypes, ctypes.util; s=ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices")); s.AXIsProcessTrusted.restype=ctypes.c_bool; print(int(bool(s.AXIsProcessTrusted())))' 2>/dev/null || echo 1)"
if [[ "${IS_TRUSTED}" == "0" ]]; then
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" >/dev/null 2>&1 || true
  if [[ -e "${PYTHON_APP_BUNDLE}" ]]; then
    open -R "${PYTHON_APP_BUNDLE}" >/dev/null 2>&1 || true
  fi
fi
