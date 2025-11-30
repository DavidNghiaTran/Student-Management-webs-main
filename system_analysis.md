# TÀI LIỆU PHÂN TÍCH HỆ THỐNG QUẢN LÝ SINH VIÊN

## 1. Tổng quan dự án
Hệ thống Quản lý Sinh viên là một ứng dụng web được xây dựng nhằm mục đích hỗ trợ nhà trường, giáo viên và sinh viên trong việc quản lý thông tin học tập, giảng dạy và điểm số. Hệ thống cung cấp các chức năng phân quyền rõ ràng, giúp tối ưu hóa quy trình quản lý đào tạo.

## 2. Công nghệ sử dụng
- **Ngôn ngữ lập trình**: Python 3.12
- **Web Framework**: Flask (Microframework)
- **Cơ sở dữ liệu**: SQLite (Môi trường Dev), có hỗ trợ PostgreSQL (Môi trường Prod/Vercel)
- **ORM**: SQLAlchemy
- **Giao diện (Frontend)**: HTML5, CSS3, Bootstrap 5, Jinja2 Templating
- **Thư viện hỗ trợ**: Pandas (xử lý Excel), OpenPyXL, Flask-Login (xác thực), Flask-Bcrypt (mã hóa mật khẩu).

## 3. Cơ sở dữ liệu (Database Schema)

Hệ thống sử dụng cơ sở dữ liệu quan hệ với các bảng chính sau:

### 3.1. Bảng Người dùng & Phân quyền
*   **`TaiKhoan` (`tai_khoan`)**: Lưu trữ thông tin đăng nhập.
    *   `username` (PK): Tên đăng nhập.
    *   `password`: Mật khẩu đã mã hóa.
    *   `vai_tro`: Enum (`ADMIN`, `GIAOVIEN`, `SINHVIEN`).

*   **`NhanVien` (`nhan_vien`)**: Thông tin chi tiết của Admin/Nhân viên.
    *   `ma_nv` (PK, FK `TaiKhoan`): Mã nhân viên.
    *   `ho_ten`, `email`, `so_dien_thoai`, `phong_ban`, `chuc_vu`.

*   **`GiaoVien` (`giao_vien`)**: Thông tin chi tiết của Giáo viên.
    *   `ma_gv` (PK, FK `TaiKhoan`): Mã giáo viên.
    *   `ho_ten`, `ngay_sinh`, `email`, `so_dien_thoai`.
    *   `khoa_bo_mon`, `hoc_vi`, `van_phong`, `avatar_url`.

*   **`SinhVien` (`sinh_vien`)**: Thông tin chi tiết của Sinh viên.
    *   `ma_sv` (PK, FK `TaiKhoan`): Mã sinh viên.
    *   `ho_ten`, `ngay_sinh`, `lop`, `khoa`, `email`, `he_dao_tao`.

### 3.2. Bảng Học tập & Đào tạo
*   **`MonHoc` (`mon_hoc`)**: Danh sách môn học.
    *   `ma_mh` (PK): Mã môn học.
    *   `ten_mh`: Tên môn học.
    *   `so_tin_chi`: Số tín chỉ.
    *   `hoc_ky`: Học kỳ mặc định.
    *   `percent_cc`, `percent_bt`, `percent_kt`, `percent_th`, `percent_thi`: Cấu hình trọng số điểm.

*   **`LichHoc` (`lich_hoc`)**: Thời khóa biểu.
    *   `id` (PK): ID tự tăng.
    *   `tieu_de`, `lop`, `phong`, `thu_trong_tuan`, `gio_bat_dau`, `gio_ket_thuc`.
    *   `ma_mh` (FK `MonHoc`), `ma_gv` (FK `TaiKhoan`).

*   **`PhanCong` (`phan_cong`)**: Phân công giảng dạy.
    *   `ma_gv` (FK), `ma_mh` (FK), `lop`.

### 3.3. Bảng Điểm & Kết quả
*   **`KetQua` (`ket_qua`)**: Bảng điểm chi tiết.
    *   `ma_sv` (PK, FK), `ma_mh` (PK, FK).
    *   `diem_chuyen_can`, `diem_bai_tap`, `diem_kiem_tra`, `diem_thuc_hanh`, `diem_thi`.
    *   `diem_tong_ket` (hệ 10), `diem_tong_ket_4` (hệ 4), `diem_chu` (A, B, C...).
    *   *Lưu ý*: Điểm tổng kết được tính tự động dựa trên trọng số cấu hình trong bảng `MonHoc`.

### 3.4. Bảng Bài tập & Hoạt động
*   **`BaiTap` (`bai_tap`)**: Bài tập giáo viên giao.
    *   `tieu_de`, `noi_dung`, `han_nop`, `tep_dinh_kem`.
    *   `ma_mh` (FK), `ma_gv` (FK), `lop_nhan`.

*   **`BaiLam` (`bai_lam`)**: Bài làm sinh viên nộp.
    *   `bai_tap_id` (FK), `ma_sv` (FK).
    *   `file_path`, `diem`, `nhan_xet`.

*   **`LichSuHoatDong` (`lich_su_hoat_dong`)**: Audit log ghi lại các thay đổi quan trọng (ví dụ: sửa điểm).

## 4. Các phân hệ chức năng

### 4.1. Phân hệ Admin (Quản trị viên)
*   **Dashboard**: Thống kê tổng quan số lượng sinh viên, giáo viên, môn học.
*   **Quản lý Sinh viên**: Thêm, sửa, xóa, import danh sách từ Excel.
*   **Quản lý Giáo viên**: Thêm, sửa, xóa, cập nhật thông tin chuyên môn.
*   **Quản lý Môn học**: Tạo môn học mới, cấu hình trọng số điểm (CC, BT, KT, TH, Thi).
*   **Quản lý Điểm**: Nhập điểm trực tiếp, Import/Export điểm qua Excel, tính toán GPA tự động.
*   **Báo cáo & Thống kê**:
    *   Báo cáo sinh viên có GPA cao (Khen thưởng).
    *   Báo cáo sinh viên bị cảnh báo học vụ.
    *   Phổ điểm theo môn học.

### 4.2. Phân hệ Giáo viên
*   **Lịch giảng dạy**: Xem thời khóa biểu cá nhân.
*   **Quản lý Bài tập**: Giao bài tập cho lớp, chấm điểm bài làm của sinh viên.
*   **Nhập điểm**: (Tùy chọn cấu hình) Giáo viên có thể được cấp quyền nhập điểm thành phần.

### 4.3. Phân hệ Sinh viên
*   **Dashboard**: Xem thông tin cá nhân, GPA tích lũy, số tín chỉ đạt được.
*   **Tra cứu điểm**: Xem bảng điểm chi tiết từng môn, điểm chữ, điểm hệ 4.
*   **Lịch học**: Xem thời khóa biểu hàng tuần.
*   **Bài tập**: Xem danh sách bài tập, nộp bài trực tuyến, xem điểm và nhận xét.

## 5. Cấu trúc thư mục dự án

```
Student-Management-webs-main/
├── api/
│   ├── index.py            # File chính chứa logic backend (Flask App, Models, Routes)
│   ├── create_admin.py     # Script tạo tài khoản admin ban đầu
│   └── ...
├── templates/              # Chứa các file giao diện HTML (Jinja2)
│   ├── _layout.html        # Layout chung cho toàn trang
│   ├── admin_*.html        # Các trang chức năng của Admin
│   ├── student_*.html      # Các trang chức năng của Sinh viên
│   └── ...
├── static/
│   ├── css/                # File CSS tùy chỉnh
│   ├── js/                 # File JavaScript
│   └── uploads/            # Thư mục chứa file nộp bài, avatar
├── data/                   # Chứa dữ liệu mẫu hoặc file db SQLite
├── requirements.txt        # Danh sách thư viện Python cần thiết
└── qlsv.db                 # File cơ sở dữ liệu SQLite (khi chạy local)
```

## 6. Hướng dẫn cài đặt & Chạy dự án

1.  **Cài đặt Python**: Đảm bảo máy đã cài Python 3.8 trở lên.
2.  **Cài đặt thư viện**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Khởi tạo Database**:
    Hệ thống sẽ tự động tạo file `qlsv.db` và các bảng khi chạy lần đầu.
4.  **Chạy ứng dụng**:
    ```bash
    python api/index.py
    ```
5.  **Truy cập**: Mở trình duyệt và vào địa chỉ `http://localhost:5000`.

---
*Tài liệu được cập nhật lần cuối vào: 29/11/2025*
