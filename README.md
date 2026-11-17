# Mac Web Virtual Keyboard (Android APK + macOS Server)
Giải pháp lai biến Samsung Galaxy S24+ (`6.7"` xoay ngang tràn viền) thành bàn phím vật lý PC/Mac thời gian thực cho MacBook M3 Pro qua mạng LAN hoặc Tailscale với độ trễ `0ms`, không qua Bluetooth HID, không kẹt bộ đệm từ tiếng Việt, tự chạy ngầm trên macOS và tự động cập nhật `.apk` trực tiếp từ GitHub Releases.

## 1. Cấu trúc dự án
```text
mac-web-keyboard/
├── .github/workflows/
│   └── release.yml                     # GitHub Actions tự build & ký app-release.apk khi push tag v*
├── android/                            # Ứng dụng Android Native WebView (.apk xoay ngang tràn viền)
│   ├── app/build.gradle.kts            # Nhúng trực tiếp ../static vào APK assets + ký Keystore
│   └── app/src/main/
│       ├── AndroidManifest.xml         # Khóa cứng landscape, REQUEST_INSTALL_PACKAGES, FileProvider
│       ├── java/com/nguyenhieu/mackeyboard/MainActivity.kt
│       └── res/xml/file_paths.xml      # Cấp URI cài đặt bản cập nhật APK tự động
├── macos/
│   ├── com.nguyenhieu.macwebkeyboard.plist
│   ├── install_launchd.sh              # Cài đặt chạy ngầm tự khởi động cùng macOS (launchd)
│   └── uninstall_launchd.sh            # Gỡ dịch vụ chạy ngầm
├── static/
│   ├── index.html                      # Bố cục 6 hàng phím Mac/PC + thanh Macro 1 chạm
│   ├── style.css                       # Dark Mode tối giản tràn viền cho S24+
│   ├── app.js                          # Cảm ứng đa điểm, Sticky Modifiers, Auto-repeat Backspace
│   └── manifest.json                   # Cấu hình PWA dự phòng khi mở qua trình duyệt
├── server.py                           # FastAPI WebSocket (0.0.0.0:5050) + Quartz CGEvent / pynput
└── requirements.txt
```

## 2. Cài đặt chạy ngầm trên MacBook M3 Pro (`launchd`)
- Clone repo về MacBook và chạy duy nhất 1 lệnh cài đặt:
```bash
git clone https://github.com/NguyenHieu2711/mac-web-keyboard.git
cd mac-web-keyboard
chmod +x macos/install_launchd.sh macos/uninstall_launchd.sh
./macos/install_launchd.sh
```
- Cấp quyền Trợ năng (chỉ làm 1 lần duy nhất):
	- Mở **System Settings** -> **Privacy & Security** -> **Accessibility**.
	- Nhấn dấu `+`, chọn đường dẫn `.venv/bin/python` mà script vừa in ra trên Terminal (bấm `Cmd + Shift + G` để dán đường dẫn nhanh, nhấn `Cmd + Shift + .` nếu thư mục `.venv` đang ẩn) và gạt công tắc sang **ON**.
	- Khởi động lại dịch vụ 1 lần để nhận quyền ngay: `launchctl kickstart -k gui/$(id -u)/com.nguyenhieu.macwebkeyboard`.
- Tương thích tiếng Việt 100%:
	- `server.py` phát trực tiếp mã phím phần cứng Apple (`Quartz CGEvent` tại `kCGHIDEventTap`), nên EVKey / OpenKey / bộ gõ Telex mặc định trên macOS tự động bỏ dấu chuẩn xác, `Backspace` xóa xuyên mọi khoảng trắng và `⌘Z` hoạt động tức thì.

## 3. Thiết lập Keystore & Phát hành tự động trên GitHub Actions
> 💡 **Đúc kết:** Dùng 1 Keystore cố định lưu trong GitHub Secrets giúp mọi bản `.apk` mới luôn trùng chữ ký số để cài đè mượt mà lên bản cũ không cần gỡ app.
- Bước 1 — Tạo file Keystore cố định 1 lần trên máy tính (Mac hoặc Windows có cài JDK):
```bash
keytool -genkeypair -v \
  -keystore mac-keyboard-release.jks \
  -alias mackeyboard \
  -keyalg RSA -keysize 2048 -validity 10000
```
- Bước 2 — Chuyển file `.jks` sang chuỗi Base64:
	- Trên macOS: `base64 -i mac-keyboard-release.jks | pbcopy` (đã tự copy vào clipboard).
	- Trên Windows PowerShell: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("mac-keyboard-release.jks")) | Set-Clipboard`.
- Bước 3 — Vào repo GitHub -> **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**, tạo 4 biến:
	- `KEYSTORE_BASE64`: Chuỗi Base64 vừa copy ở Bước 2.
	- `KEYSTORE_PASSWORD`: Mật khẩu Keystore bạn đã đặt.
	- `KEY_ALIAS`: `mackeyboard`.
	- `KEY_PASSWORD`: Mật khẩu Key (thường trùng `KEYSTORE_PASSWORD`).
- Bước 4 — Bắn tag để GitHub Actions tự build `app-release.apk` và tạo Release:
```bash
git tag v1.0.0
git push origin v1.0.0
```

## 4. Sử dụng & Tự động cập nhật trên Samsung Galaxy S24+
- Lần đầu tiên: Tải `app-release.apk` từ mục **Releases** trên GitHub về S24+ và cài đặt.
- Chạm icon **Mac Keyboard** trên màn hình chính:
	- Ứng dụng lập tức khóa ngang toàn màn hình tràn viền 100% (Immersive Sticky ẩn sạch thanh pin và thanh điều hướng).
	- Nhập địa chỉ IP Tailscale hoặc IP Wi-Fi LAN của MacBook (hỗ trợ nhập đồng thời cả hai ngăn cách bởi dấu phẩy, ví dụ `192.168.1.25:5050, 100.88.1.5:5050` để tự động chuyển mạch giữa nhà và ngoài đường).
	- Bấm nút `⚙` góc trên bên phải bất kỳ lúc nào để đổi IP hoặc kiểm tra cập nhật thủ công; chấm tròn bên cạnh báo Xanh lá khi WebSocket đã thông suốt và Đỏ khi đang chờ kết nối lại.
- Cơ chế In-App Auto-Update tự động:
	- Mỗi lần mở app (khi bạn vừa push tag mới như `v1.0.1` lên GitHub), `MainActivity` tự gọi API `/releases/latest`, so sánh với `BuildConfig.VERSION_NAME`, tự tải `app-release.apk` qua `DownloadManager` và bật thẳng hộp thoại **Cập nhật** ngay trên màn hình S24+.
