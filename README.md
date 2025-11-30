Hệ thống Quản lý Sinh viên & Điểm thi (Student & Grade Management)
Một ứng dụng web Flask đầy đủ chức năng được xây dựng bằng Python, Flask và SQLAlchemy, cho phép quản lý thông tin sinh viên, môn học, điểm thi và gửi thông báo. Hệ thống phân quyền rõ ràng cho hai vai trò: Sinh viên và Giáo viên.

Dự án này được xây dựng dựa trên một bản đặc tả kỹ thuật chi tiết, bao gồm các yêu cầu về CSDL, bảo mật và logic nghiệp vụ.

🚀 Tính năng nổi bật
Hệ thống đáp ứng đầy đủ các yêu cầu nghiệp vụ của một trang quản lý học vụ cơ bản:

👤 Chức năng Chung
Xác thực Bảo mật: Hệ thống đăng nhập/đăng xuất an toàn sử dụng flask-login và bcrypt để băm mật khẩu.

Phân quyền (Middleware): Tách biệt hoàn toàn chức năng của Sinh viên (/student/*) và Giáo viên (/admin/*).

👨‍🎓 Chức năng Sinh viên
Xem Thông tin cá nhân: Xem thông tin (chỉ đọc) của bản thân.

Xem Bảng điểm: Tự động hiển thị bảng điểm cá nhân chi tiết.

Tính GPA: Tự động tính điểm trung bình (GPA) thang 10 dựa trên điểm thi và số tín chỉ.

Nhận Thông báo: Xem các thông báo mới nhất do giáo viên gửi cho lớp của mình.

👩‍🏫 Chức năng Giáo viên
Quản lý Sinh viên (CRUD):

Xem danh sách, Thêm, Sửa, Xóa sinh viên.

Logic Tự động: Khi thêm sinh viên mới, hệ thống tự động tạo một tài khoản đăng nhập tương ứng với mật khẩu mặc định đã băm.

Ràng buộc Dữ liệu: Xóa sinh viên sẽ tự động xóa tài khoản và điểm thi liên quan (sử dụng ON DELETE CASCADE).

Quản lý Môn học (CRUD): Thêm, Sửa, Xóa thông tin các môn học trong hệ thống.

Quản lý Điểm (Nhập hàng loạt):

Giao diện nhập điểm 2 bước: Chọn Lớp -> Chọn Môn học.

Hiển thị danh sách sinh viên của lớp và tự động tải điểm cũ (nếu có).

Logic INSERT (điểm mới) hoặc UPDATE (điểm cũ) thông minh khi lưu.

Báo cáo & Thống kê:

Truy vấn danh sách sinh viên có GPA cao (ví dụ: > 8.0).

Truy vấn sinh viên chưa thi một môn học cụ thể (sử dụng SUBQUERY).

Tính GPA trung bình chung của một lớp học.

Gửi Thông báo: Soạn và gửi thông báo cho một Lớp cụ thể.

🛠️ Công nghệ sử dụng
Backend: Python 3

Framework: Flask

ORM: Flask-SQLAlchemy (sử dụng SQLite)

Xác thực: Flask-Login (Quản lý phiên) & Flask-Bcrypt (Băm mật khẩu)

Frontend: HTML5 & CSS (sử dụng template Jinja2)

Database: SQLite (dễ dàng chuyển đổi sang MySQL/PostgreSQL)

📦 Hướng dẫn Cài đặt & Khởi chạy
Clone repository:

Bash

git clone https://[URL_GITHUB_CUA_BAN]/[TEN_REPO].git
cd [TEN_REPO]
Tạo môi trường ảo (Khuyến khích):

Bash

python -m venv venv
# Trên Windows
.\venv\Scripts\activate
# Trên macOS/Linux
source venv/bin/activate
Cài đặt các thư viện: (Bạn có thể tạo file requirements.txt bằng lệnh pip freeze > requirements.txt)

Bash

pip install Flask Flask-SQLAlchemy Flask-Login flask-bcrypt
Khởi chạy ứng dụng:

Bash

python app.py
Truy cập ứng dụng:

Mở trình duyệt và truy cập: http://127.0.0.1:5000

Ứng dụng sẽ tự động chuyển hướng đến trang Đăng nhập.

🔑 Tài khoản Mặc định
Khi khởi chạy ứng dụng lần đầu tiên, một tài khoản Giáo viên (Admin) mặc định sẽ được tạo:

Username: giaovien01

Password: admin@123
