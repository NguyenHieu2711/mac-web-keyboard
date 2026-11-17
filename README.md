# Mac Web Virtual Keyboard (Android S24+ ➔ macOS)

Ứng dụng **Web Virtual Keyboard (PWA)** siêu nhẹ chạy qua mạng nội bộ (**LAN Wi-Fi** hoặc **Tailscale**) biến điện thoại **Samsung Galaxy S24+ (6.7 inch)** xoay ngang thành bàn phím vật lý đầy đủ (**Full Mac Layout**) điều khiển và gõ tiếng Việt thời gian thực trên **MacBook (macOS)** với độ trễ gần bằng `0ms`.

## Tính năng cốt lõi

- **Không qua bộ gõ điện thoại (Zero Word-Buffering):** Giao diện phím thuần HTML5/CSS3/JS, triệt tiêu hoàn toàn lỗi Gboard / Samsung Keyboard giữ bộ đệm từ làm kẹt phím `Backspace` khi xóa qua khoảng trắng.
- **Tương thích 100% Tiếng Việt trên macOS:** Backend `server.py` bắn trực tiếp mã phím vật lý chuẩn **Apple Virtual KeyCode (`Quartz CGEvent` / `kCGHIDEventTap`)**, giúp **EVKey / OpenKey / Bộ gõ Telex mặc định của macOS** tự động bỏ dấu tiếng Việt mượt như bàn phím cứng.
- **Đa điểm (Multi-touch) + Sticky Modifiers:** Vừa hỗ trợ giữ đồng thời `⌘ Cmd` / `⇧ Shift` bằng ngón cái trái rồi bấm phím chữ bằng ngón phải, vừa hỗ trợ chạm 1 cái để khóa sáng (**Sticky**) khi thao tác 1 tay.
- **Thanh Macro 1 chạm & Auto-Repeat:** Trang bị sẵn hàng phím nhanh `Esc`, `⌘Z` (Undo), `⌘C` (Copy), `⌘V` (Paste), `⌘A` (Select All), `⌘⌫` (Xóa cả dòng), `Del` và nhấn giữ liên tục cho `⌫ Backspace`, `Space`, cụm mũi tên `↑ ↓ ← →`.
- **Chuẩn PWA Fullscreen Landscape:** Tự động mở toàn màn hình, khóa xoay ngang, phản hồi rung nhẹ `10ms` và tự động kết nối lại WebSocket nếu mạng chập chờn.

## Cấu trúc thư mục

```text
mac-web-keyboard/
├── server.py           # WebSocket + HTTP server phục vụ static files và điều khiển phím macOS
├── requirements.txt    # fastapi, uvicorn, websockets, pynput, pyobjc-framework-Quartz
├── static/
│   ├── index.html      # Giao diện PWA bàn phím ngang full màn hình (6 hàng chuẩn Mac)
│   ├── style.css       # CSS Grid tối ưu cho màn hình ngang S24+ (6.7 inch + Safe Area)
│   ├── app.js          # Xử lý multi-touch, sticky modifiers, auto-repeat, WebSocket client
│   └── manifest.json   # Cấu hình PWA để Add to Home Screen không thanh địa chỉ
└── README.md           # Hướng dẫn cài đặt, cấp quyền Accessibility macOS và chạy ngầm
```

## 1. Cài đặt và Chạy trên MacBook (macOS)

```bash
git clone https://github.com/NguyenHieu2711/mac-web-keyboard.git
cd mac-web-keyboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

Khi khởi động, Terminal sẽ in sẵn địa chỉ **LAN Wi-Fi** và **Tailscale** (ví dụ `http://192.168.1.x:5050` hoặc `http://100.x.x.x:5050`).

## 2. Cấp quyền Accessibility (Trợ năng) trên macOS (Bắt buộc)

Để macOS cho phép Python giả lập tín hiệu bàn phím phần cứng:

1. Mở **System Settings (Cài đặt hệ thống)** ➔ **Privacy & Security (Quyền riêng tư & Bảo mật)** ➔ **Accessibility (Trợ năng)**.
2. Bấm dấu `+` (hoặc bật công tắc) cho ứng dụng bạn dùng để chạy lệnh: **Terminal** (hoặc **iTerm2** / **Visual Studio Code**).
3. Khởi động lại `python server.py` — dòng thông báo `✅ Quyền Accessibility macOS đã được cấp đầy đủ` sẽ hiện lên.

## 3. Mở trên Samsung Galaxy S24+ (Chế độ Không Thanh Địa Chỉ)

1. Mở **Chrome** trên điện thoại S24+, truy cập địa chỉ `http://<IP-MacBook>:5050`.
2. Bấm menu `⋮` góc phải Chrome ➔ chọn **Add to Home screen (Thêm vào màn hình chính)** ➔ chọn **Install / Add**.
3. Mở icon **MacKeys** ngoài màn hình chính: ứng dụng tự bung toàn màn hình ngang, chấm tròn góc trên bên phải chuyển sang **màu xanh lá** là sẵn sàng gõ!

## 4. Chạy ngầm tự động trên macOS (Tùy chọn)

Chạy ngầm không cần giữ cửa sổ Terminal:

```bash
nohup ./.venv/bin/python server.py > keyboard.log 2>&1 &
```
