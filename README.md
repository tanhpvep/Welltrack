# 🛢️ PVEP WellTrack 3D - Multi-Well Trajectory & DDR Activity Monitor

Hệ thống theo dõi tiến độ thi công đồng thời **8 - 10 giếng khoan dầu khí** trên nền Web bằng **Python & Streamlit**:
- **Trực quan hóa Quỹ đạo Giếng 3D (Plan vs Survey)** theo phương pháp Minimum Curvature (SPE Standard) với 3 khung nhìn đồng thời (3D Trajectory, Top-Down Plan View, Profile View).
- **Màn hình song song (Side-by-Side)**: Xem Quỹ đạo Survey bên cạnh Báo cáo hoạt động giếng thời gian thực (Activity Last 24h Summary, 24h Forecast, NPT, ROP, BHA, Mud).
- **Trích xuất thông minh Báo cáo Khoan Hàng Ngày (DDR PDF)** bằng AI Gemini.
- **Tổng quan Toàn cụm Giàn (Field Multi-Well 3D)**: Đánh giá vị trí không gian ngầm và khoảng cách chống va chạm (Anti-Collision).

---

## 🚀 Hướng Dẫn Đưa Lên GitHub & Triển Khai Streamlit Cloud

### Bước 1: Khởi tạo Git Repo trên máy của bạn
```bash
git init
git add streamlit_app.py requirements.txt README.md
git commit -m "Initial commit: Multi-well 3D trajectory and DDR monitor"
```

### Bước 2: Đẩy lên GitHub
Tạo một repository mới trên GitHub (ví dụ: `https://github.com/tanhpvep/WellTrack3D_DDR`) và chạy:
```bash
git remote add origin https://github.com/tanhpvep/WellTrack3D_DDR.git
git branch -M main
git push -u origin main
```

### Bước 3: Triển khai lên Web miễn phí với Streamlit Cloud
1. Truy cập [share.streamlit.io](https://share.streamlit.io/) và đăng nhập bằng tài khoản GitHub của bạn.
2. Nhấn nút **"New app"**.
3. Chọn Repository: `tanhpvep/WellTrack3D_DDR`
4. Main file path: `streamlit_app.py`
5. Trong mục **Advanced settings > Secrets**, dán API Key của Gemini nếu muốn dùng tính năng AI trích xuất PDF tự động:
   ```toml
   GEMINI_API_KEY = "your_gemini_api_key_here"
   ```
6. Nhấn **"Deploy!"** - Ứng dụng sẽ hoạt động trên nền web chia sẻ cho toàn bộ phòng ban PVEP xem mọi lúc mọi nơi!
