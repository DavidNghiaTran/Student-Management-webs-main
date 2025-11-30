import sys, os, shutil
# Bảo đảm thư mục gốc có trong PYTHONPATH để import module nội bộ khi deploy (Vercel/Unix)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)

from data.thongbao import notifications as ptit_notifications

# -*- coding: utf-8 -*-
# === Đặt hàm helper classify_gpa_10 ra ngoài ===
def classify_gpa_10(gpa):
    if gpa >= 9.0:
        return "Xuất sắc"
    elif gpa >= 8.0:
        return "Giỏi"
    elif gpa >= 6.5:
        return "Khá"
    elif gpa >= 5.0:
        return "Trung bình"
    # Kiểm tra None trước khi so sánh
    elif gpa is None or gpa < 5.0:
        return "Yếu"
    else:
        return "Yếu" # Mặc định
# ===============================================

def convert_10_to_4_scale(diem_10):
    """
    Hàm trợ giúp đề xuất: Chuyển điểm 10 sang điểm 4.
    (Dựa trên thang điểm tín chỉ thông thường)
    """
    # Kiểm tra None trước khi so sánh
    if diem_10 is None:
        return 0.0 # Hoặc giá trị mặc định khác
    if diem_10 >= 8.5:
        return 4.0  # A
    elif diem_10 >= 8.0:
        return 3.5  # B+
    elif diem_10 >= 7.0:
        return 3.0  # B
    elif diem_10 >= 6.5:
        return 2.5  # C+
    elif diem_10 >= 5.5:
        return 2.0  # C
    elif diem_10 >= 5.0:
        return 1.5  # D+
    elif diem_10 >= 4.0:
        return 1.0  # D
    else:
        return 0.0  # F

import enum
import math
import pandas as pd
import io
import unicodedata
from flask import send_file
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from datetime import datetime, date, timedelta
from sqlalchemy.sql import func, case, literal_column
from sqlalchemy import select, and_, text, inspect as sa_inspect, event
from sqlalchemy.orm.attributes import get_history
from sqlalchemy.exc import NoSuchTableError
from functools import wraps
import uuid
from werkzeug.utils import secure_filename

# --- 1. CẤU HÌNH ỨNG DỤNG ---

basedir = os.path.abspath(os.path.dirname(__file__))
template_dir = os.path.join(project_root, 'templates')
static_dir = os.path.join(project_root, 'static')

def resolve_database_uri():
    """
    Build a database URI that works locally and on Vercel.
    - Prefer DATABASE_URL when provided (for hosted DBs).
    - For SQLite on Vercel, copy qlsv.db into /tmp so it is writable.
    """
    env_db_url = os.getenv('DATABASE_URL')
    if env_db_url:
        if env_db_url.startswith('postgres://'):
            env_db_url = env_db_url.replace('postgres://', 'postgresql://', 1)
        return env_db_url

    sqlite_path = os.path.join(project_root, 'qlsv.db')
    running_on_vercel = os.getenv('VERCEL') or os.getenv('VERCEL_URL')
    if running_on_vercel:
        tmp_sqlite_path = os.path.join('/tmp', 'qlsv.db')
        if not os.path.exists(tmp_sqlite_path):
            try:
                os.makedirs(os.path.dirname(tmp_sqlite_path), exist_ok=True)
                if os.path.exists(sqlite_path):
                    shutil.copy(sqlite_path, tmp_sqlite_path)
                else:
                    open(tmp_sqlite_path, 'a').close()
            except OSError as exc:
                print(f"[Database setup] Could not prepare writable SQLite copy: {exc}")
            else:
                sqlite_path = tmp_sqlite_path
        else:
            sqlite_path = tmp_sqlite_path

    return 'sqlite:///' + sqlite_path

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.config['SECRET_KEY'] = 'mot-khoa-bi-mat-rat-manh-theo-yeu-cau-bao-mat'
# Cấu hình đường dẫn CSDL tùy theo môi trường (local/VERCEL/heroku)
app.config['SQLALCHEMY_DATABASE_URI'] = resolve_database_uri()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True}

# Cấu hình Upload
UPLOAD_FOLDER = os.path.join(project_root, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'zip', 'rar', 'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Tạo thư mục upload nếu chưa tồn tại
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# =====================

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)

login_manager.login_view = 'login'


def ensure_teacher_profile_columns():
    """Ensure new optional teacher columns exist for older SQLite databases."""
    try:
        inspector = sa_inspect(db.engine)
        existing_columns = {col['name'] for col in inspector.get_columns('giao_vien')}
    except NoSuchTableError:
        return

    statements = []

    def add_if_missing(column_name, ddl):
        if column_name not in existing_columns:
            statements.append(ddl)

    add_if_missing('van_phong', "ALTER TABLE giao_vien ADD COLUMN van_phong VARCHAR(120)")
    add_if_missing('avatar_url', "ALTER TABLE giao_vien ADD COLUMN avatar_url VARCHAR(255)")
    add_if_missing('khoa_bo_mon', "ALTER TABLE giao_vien ADD COLUMN khoa_bo_mon VARCHAR(120)")
    add_if_missing('hoc_vi', "ALTER TABLE giao_vien ADD COLUMN hoc_vi VARCHAR(100)")

    if not statements:
        return

    for ddl in statements:
        try:
            db.session.execute(text(ddl))
        except Exception as exc:
            db.session.rollback()
            print(f"[Schema update] Could not apply '{ddl}': {exc}")
            return

    db.session.commit()

def ensure_student_columns():
    """Ensure new optional student columns exist for older SQLite databases."""
    try:
        inspector = sa_inspect(db.engine)
        existing_columns = {col['name'] for col in inspector.get_columns('sinh_vien')}
    except NoSuchTableError:
        return

    statements = []

    def add_if_missing(column_name, ddl):
        if column_name not in existing_columns:
            statements.append(ddl)

    add_if_missing('he_dao_tao', "ALTER TABLE sinh_vien ADD COLUMN he_dao_tao VARCHAR(50) DEFAULT 'CU_NHAN'")

    if not statements:
        return

    for ddl in statements:
        try:
            db.session.execute(text(ddl))
        except Exception as exc:
            db.session.rollback()
            print(f"[Schema update] Could not apply '{ddl}': {exc}")
            return

    db.session.commit()

def update_grading_schema():
    """Add new grading columns to MonHoc and KetQua if they don't exist."""
    try:
        inspector = sa_inspect(db.engine)
        
        # 1. Update MonHoc (Weights)
        mh_cols = {col['name'] for col in inspector.get_columns('mon_hoc')}
        statements_mh = []
        if 'percent_cc' not in mh_cols: statements_mh.append("ALTER TABLE mon_hoc ADD COLUMN percent_cc INTEGER DEFAULT 10")
        if 'percent_bt' not in mh_cols: statements_mh.append("ALTER TABLE mon_hoc ADD COLUMN percent_bt INTEGER DEFAULT 0")
        if 'percent_kt' not in mh_cols: statements_mh.append("ALTER TABLE mon_hoc ADD COLUMN percent_kt INTEGER DEFAULT 0")
        if 'percent_th' not in mh_cols: statements_mh.append("ALTER TABLE mon_hoc ADD COLUMN percent_th INTEGER DEFAULT 0")
        if 'percent_thi' not in mh_cols: statements_mh.append("ALTER TABLE mon_hoc ADD COLUMN percent_thi INTEGER DEFAULT 90")
        
        for ddl in statements_mh:
            db.session.execute(text(ddl))

        # 2. Update KetQua (Scores)
        kq_cols = {col['name'] for col in inspector.get_columns('ket_qua')}
        statements_kq = []
        if 'diem_bai_tap' not in kq_cols: statements_kq.append("ALTER TABLE ket_qua ADD COLUMN diem_bai_tap FLOAT")
        if 'diem_kiem_tra' not in kq_cols: statements_kq.append("ALTER TABLE ket_qua ADD COLUMN diem_kiem_tra FLOAT")
        if 'diem_thuc_hanh' not in kq_cols: statements_kq.append("ALTER TABLE ket_qua ADD COLUMN diem_thuc_hanh FLOAT")
        if 'diem_thi' not in kq_cols: statements_kq.append("ALTER TABLE ket_qua ADD COLUMN diem_thi FLOAT")
        if 'diem_tong_ket_4' not in kq_cols: statements_kq.append("ALTER TABLE ket_qua ADD COLUMN diem_tong_ket_4 FLOAT")

        for ddl in statements_kq:
            db.session.execute(text(ddl))

        db.session.commit()
    except Exception as e:
        print(f"[Schema Update Error] {e}")
        db.session.rollback()


def initialize_database():
    """Ensure tables exist on cold start (needed for serverless/Vercel)."""
    with app.app_context():
        db.create_all()
        ensure_teacher_profile_columns()
        ensure_student_columns()
        update_grading_schema()


initialize_database()
login_manager.login_message = 'Vui lòng đăng nhập để truy cập trang này.'
login_manager.login_message_category = 'info'


# --- 2. ĐỊNH NGHĨA MODEL (CSDL) ---
# (Giữ nguyên các Model: VaiTroEnum, TaiKhoan, SinhVien, MonHoc, KetQua, ThongBao)
class VaiTroEnum(enum.Enum):
    SINHVIEN = 'SINHVIEN'
    GIAOVIEN = 'GIAOVIEN'
    ADMIN = 'ADMIN'

# (Tìm và thay thế 3 class này trong api/index.py)

class TaiKhoan(UserMixin, db.Model):
    # Tên bảng trong CSDL
    __tablename__ = 'tai_khoan'
    
    # Khóa chính (Primary Key) - Tên đăng nhập
    username = db.Column(db.String(50), primary_key=True)
    
    # Mật khẩu đã mã hóa (Hashed Password)
    password = db.Column(db.String(255), nullable=False)
    
    # Vai trò (Enum): SINHVIEN hoặc GIAOVIEN
    vai_tro = db.Column(db.Enum(VaiTroEnum), nullable=False)

    # LƯU Ý: Chúng ta KHÔNG định nghĩa relationship ở đây.
    # backref từ SinhVien (tên 'sinh_vien') và GiaoVien (tên 'giao_vien')
    # sẽ tự động được thêm vào đây.

    def get_id(self):
        return self.username

    def set_password(self, password):
        self.password = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password, password)

    def has_role(self, role_name):
        # Normalize self.vai_tro to string
        current_role = self.vai_tro
        if hasattr(current_role, 'value'):
            current_role = current_role.value
        else:
            current_role = str(current_role)
        
        return current_role == role_name


class SinhVien(db.Model):
    # Tên bảng trong CSDL
    __tablename__ = 'sinh_vien'
    
    # Khóa chính (Primary Key) & Khóa ngoại (Foreign Key)
    # Liên kết 1-1 với bảng TaiKhoan (username)
    # ondelete='CASCADE': Xóa tài khoản sẽ xóa luôn thông tin sinh viên
    ma_sv = db.Column(db.String(50), db.ForeignKey('tai_khoan.username', ondelete='CASCADE'), primary_key=True)
    
    ho_ten = db.Column(db.String(100), nullable=False)
    ngay_sinh = db.Column(db.Date)
    lop = db.Column(db.String(50))
    khoa = db.Column(db.String(100))
    email = db.Column(db.String(150), unique=True, nullable=True)
    location = db.Column(db.String(200), nullable=True)
    he_dao_tao = db.Column(db.String(50), default='CU_NHAN') # CU_NHAN (4 năm) hoặc KY_SU (4.5 năm)

    # Quan hệ (Relationship) ngược lại với bảng TaiKhoan
    # backref='sinh_vien': Truy cập từ object TaiKhoan -> TaiKhoan.sinh_vien
    tai_khoan = db.relationship('TaiKhoan', 
                                backref=db.backref('sinh_vien', uselist=False, cascade='all, delete-orphan'), 
                                foreign_keys=[ma_sv])
    # ====================================

    ket_qua_list = db.relationship('KetQua', backref='sinh_vien', lazy=True, cascade='all, delete-orphan', foreign_keys='KetQua.ma_sv')


# === MODEL MỚI: GIAO_VIEN (ĐÃ SỬA) ===
class GiaoVien(db.Model):
    # Tên bảng trong CSDL
    __tablename__ = 'giao_vien'
    
    # Khóa chính (Primary Key) & Khóa ngoại (Foreign Key)
    # Liên kết 1-1 với bảng TaiKhoan (username)
    ma_gv = db.Column(db.String(50), db.ForeignKey('tai_khoan.username', ondelete='CASCADE'), primary_key=True)
    
    # 1. Thông tin cá nhân cơ bản
    ho_ten = db.Column(db.String(100), nullable=False, default='Giáo viên')
    # gioi_tinh, ngay_sinh, dia_chi removed as per request
    so_dien_thoai = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(150), unique=True, nullable=True)
    van_phong = db.Column(db.String(120), nullable=True)
    avatar_url = db.Column(db.String(255), nullable=True)

    # 2. Thông tin chuyên môn
    khoa_bo_mon = db.Column(db.String(120), nullable=True)
    hoc_vi = db.Column(db.String(100), nullable=True)
    # chuc_vu removed (only for NhanVien)
    linh_vuc = db.Column(db.Text, nullable=True)
    # mon_hoc_phu_trach, so_nam_kinh_nghiem removed

    # === THÊM QUAN HỆ (Tương tự SinhVien) ===
    # 'backref' sẽ tự động thêm thuộc tính 'giao_vien' vào TaiKhoan
    tai_khoan = db.relationship('TaiKhoan', 
                                backref=db.backref('giao_vien', uselist=False, cascade='all, delete-orphan'), 
                                foreign_keys=[ma_gv])
    # =====================================

# === Bang moi: Nhan Vien (Admin/Staff) ===
class NhanVien(db.Model):
    __tablename__ = 'nhan_vien'
    
    # Khóa chính (Primary Key) & Khóa ngoại (Foreign Key)
    # Liên kết 1-1 với bảng TaiKhoan (username)
    ma_nv = db.Column(db.String(50), db.ForeignKey('tai_khoan.username', ondelete='CASCADE'), primary_key=True)
    
    # Thông tin cá nhân
    ho_ten = db.Column(db.String(100), nullable=False, default='Quản trị viên')
    email = db.Column(db.String(150), unique=True, nullable=True)
    so_dien_thoai = db.Column(db.String(20), nullable=True)
    
    # Thông tin công việc
    phong_ban = db.Column(db.String(100), nullable=True, default='Phòng Giáo vụ')
    chuc_vu = db.Column(db.String(100), nullable=True, default='Nhân viên')
    
    # Quan hệ với TaiKhoan
    tai_khoan = db.relationship('TaiKhoan', 
                                backref=db.backref('nhan_vien', uselist=False, cascade='all, delete-orphan'), 
                                foreign_keys=[ma_nv])
class MonHoc(db.Model):
    # Tên bảng trong CSDL
    __tablename__ = 'mon_hoc'
    
    # Khóa chính (Primary Key) - Mã môn học
    ma_mh = db.Column(db.String(50), primary_key=True)
    
    ten_mh = db.Column(db.String(100), nullable=False)
    so_tin_chi = db.Column(db.Integer, nullable=False)
    
    # === THÊM CỘT MỚI ===
    # Thêm cột học kỳ. 
    # default=1 để các môn cũ (nếu dùng migration) sẽ tự động được gán vào kỳ 1
    hoc_ky = db.Column(db.Integer, nullable=False, default=1) 
    
    # === CẤU HÌNH ĐIỂM (% TRỌNG SỐ) ===
    percent_cc = db.Column(db.Integer, default=10) # Chuyên cần
    percent_bt = db.Column(db.Integer, default=0)  # Bài tập
    percent_kt = db.Column(db.Integer, default=0)  # Kiểm tra
    percent_th = db.Column(db.Integer, default=0)  # Thực hành
    percent_thi = db.Column(db.Integer, default=90) # Thi (Cuối kỳ)
    # Tổng phải là 100%
    # =====================

    ket_qua_list = db.relationship('KetQua', backref='mon_hoc', lazy=True, cascade='all, delete-orphan', foreign_keys='KetQua.ma_mh')

class KetQua(db.Model):
    # Tên bảng trong CSDL
    __tablename__ = 'ket_qua'
    
    # Khóa chính tổ hợp (Composite Primary Key)
    # Một sinh viên học nhiều môn, một môn có nhiều sinh viên
    ma_sv = db.Column(db.String(50), db.ForeignKey('sinh_vien.ma_sv', ondelete='CASCADE'), primary_key=True)
    ma_mh = db.Column(db.String(50), db.ForeignKey('mon_hoc.ma_mh', ondelete='CASCADE'), primary_key=True)

    # Điểm thành phần (nullable=True cho phép nhập từ từ)
    diem_chuyen_can = db.Column(db.Float, nullable=True) 
    diem_bai_tap = db.Column(db.Float, nullable=True)
    diem_kiem_tra = db.Column(db.Float, nullable=True)
    diem_thuc_hanh = db.Column(db.Float, nullable=True)
    
    # Cũ: diem_giua_ky (Giữ lại để tránh lỗi migration nếu cần, nhưng logic mới sẽ ko dùng)
    diem_giua_ky = db.Column(db.Float, nullable=True)    

    # Cũ: diem_cuoi_ky -> Mới: diem_thi
    # diem_cuoi_ky removed
    diem_thi = db.Column(db.Float, nullable=True)     

    # Điểm tổng kết (tính toán)
    diem_tong_ket = db.Column(db.Float, nullable=True) # Hệ 10
    diem_tong_ket_4 = db.Column(db.Float, nullable=True) # Hệ 4
    diem_chu = db.Column(db.String(2), nullable=True)   # A, B+, ...

    # Hàm tính điểm tổng kết và điểm chữ (có thể gọi khi lưu)
    def calculate_final_score(self):
        # Lấy trọng số từ môn học
        mh = MonHoc.query.get(self.ma_mh)
        if not mh: return

        # Helper để lấy giá trị điểm (coi None là 0 để tính toán tạm, hoặc bắt buộc nhập đủ?)
        # Ở đây ta giả sử: Nếu trọng số > 0 thì bắt buộc phải có điểm mới tính TK.
        
        def get_score(val): return val if val is not None else 0.0
        def has_score(val): return val is not None

        # Kiểm tra xem đã đủ điểm cho các cột có trọng số > 0 chưa
        missing_data = False
        if mh.percent_cc > 0 and not has_score(self.diem_chuyen_can): missing_data = True
        if mh.percent_bt > 0 and not has_score(self.diem_bai_tap): missing_data = True
        if mh.percent_kt > 0 and not has_score(self.diem_kiem_tra): missing_data = True
        if mh.percent_th > 0 and not has_score(self.diem_thuc_hanh): missing_data = True
        if mh.percent_thi > 0 and not has_score(self.diem_thi): missing_data = True

        if not missing_data:
            # Tính tổng
            total = (
                (get_score(self.diem_chuyen_can) * mh.percent_cc) +
                (get_score(self.diem_bai_tap) * mh.percent_bt) +
                (get_score(self.diem_kiem_tra) * mh.percent_kt) +
                (get_score(self.diem_thuc_hanh) * mh.percent_th) +
                (get_score(self.diem_thi) * mh.percent_thi)
            ) / 100.0
            
            self.diem_tong_ket = round(total, 2)
            self.diem_tong_ket_4 = convert_10_to_4_scale(self.diem_tong_ket)
            self.diem_chu = convert_10_to_letter(self.diem_tong_ket)
        else:
            # Nếu chưa đủ điểm, đặt là None (hoặc giữ nguyên nếu muốn partial update)
            # Ở đây ta set None để chỉ ra chưa hoàn thành
            self.diem_tong_ket = None
            self.diem_tong_ket_4 = None
            self.diem_chu = None

# === THÊM HÀM HELPER CHUYỂN ĐIỂM CHỮ ===
# Đặt gần các hàm helper khác ở đầu file index.py
def convert_10_to_letter(diem_10):
    """Chuyển điểm 10 sang điểm chữ."""
    if diem_10 is None:
        return None # Hoặc F tùy quy định
    if diem_10 >= 8.5: return "A"
    elif diem_10 >= 8.0: return "B+"
    elif diem_10 >= 7.0: return "B"
    elif diem_10 >= 6.5: return "C+"
    elif diem_10 >= 5.5: return "C"
    elif diem_10 >= 5.0: return "D+"
    elif diem_10 >= 4.0: return "D"
    else: return "F"
# ======================================



# === Bang moi: Lich hoc / giang day ===
# === Bang moi: Lich hoc / giang day ===
class LichHoc(db.Model):
    # Tên bảng trong CSDL
    __tablename__ = 'lich_hoc'
    
    # Khóa chính tự tăng (Auto Increment)
    id = db.Column(db.Integer, primary_key=True)
    
    tieu_de = db.Column(db.String(200), nullable=False)
    lop = db.Column(db.String(50), nullable=False)
    
    # Khóa ngoại (Foreign Key) liên kết với MonHoc và TaiKhoan (Giáo viên)
    ma_mh = db.Column(db.String(50), db.ForeignKey('mon_hoc.ma_mh'), nullable=True)
    ma_gv = db.Column(db.String(50), db.ForeignKey('tai_khoan.username'), nullable=True)
    thu_trong_tuan = db.Column(db.String(20), nullable=True)
    ngay_hoc = db.Column(db.Date, nullable=True)
    gio_bat_dau = db.Column(db.String(20), nullable=True)
    gio_ket_thuc = db.Column(db.String(20), nullable=True)
    phong = db.Column(db.String(50), nullable=True)
    ghi_chu = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    mon_hoc = db.relationship('MonHoc', backref='lich_hoc', lazy=True)
    giao_vien = db.relationship('TaiKhoan', backref='lich_giang_day', foreign_keys=[ma_gv])

class PhanCong(db.Model):
    __tablename__ = 'phan_cong'
    id = db.Column(db.Integer, primary_key=True)
    ma_gv = db.Column(db.String(50), db.ForeignKey('tai_khoan.username'), nullable=False)
    ma_mh = db.Column(db.String(50), db.ForeignKey('mon_hoc.ma_mh'), nullable=False)
    lop = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    giao_vien = db.relationship('TaiKhoan', backref='phan_cong_giang_day')
    mon_hoc = db.relationship('MonHoc', backref='phan_cong')


# === Bang moi: Bai tap giao cho sinh vien ===
# === Bang moi: Bai tap giao cho sinh vien ===
class BaiTap(db.Model):
    # Tên bảng trong CSDL
    __tablename__ = 'bai_tap'
    
    # Khóa chính tự tăng (Auto Increment)
    id = db.Column(db.Integer, primary_key=True)
    
    tieu_de = db.Column(db.String(200), nullable=False)
    noi_dung = db.Column(db.Text, nullable=False)
    lop_nhan = db.Column(db.String(50), nullable=False)
    
    # Khóa ngoại (Foreign Key)
    ma_mh = db.Column(db.String(50), db.ForeignKey('mon_hoc.ma_mh'), nullable=True)
    ma_gv = db.Column(db.String(50), db.ForeignKey('tai_khoan.username'), nullable=False)
    han_nop = db.Column(db.Date, nullable=True)
    tep_dinh_kem = db.Column(db.String(255), nullable=True) # File đề bài
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

    bai_lam_list = db.relationship('BaiLam', backref='bai_tap', lazy=True, cascade='all, delete-orphan')

# === Bang moi: Bai lam cua sinh vien ===
class BaiLam(db.Model):
    __tablename__ = 'bai_lam'
    id = db.Column(db.Integer, primary_key=True)
    bai_tap_id = db.Column(db.Integer, db.ForeignKey('bai_tap.id'), nullable=False)
    ma_sv = db.Column(db.String(50), db.ForeignKey('sinh_vien.ma_sv'), nullable=False)
    
    file_path = db.Column(db.String(255), nullable=False) # Đường dẫn file nộp
    ngay_nop = db.Column(db.DateTime, default=datetime.now)
    diem = db.Column(db.Float, nullable=True)
    nhan_xet = db.Column(db.Text, nullable=True)

    sinh_vien = db.relationship('SinhVien', backref='bai_lam_list')
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

# === Bang moi: Lich su hoat dong (Audit Log) ===
class LichSuHoatDong(db.Model):
    __tablename__ = 'lich_su_hoat_dong'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), db.ForeignKey('tai_khoan.username'), nullable=True)
    action = db.Column(db.String(50), nullable=False) # e.g., UPDATE_GRADE
    timestamp = db.Column(db.DateTime(timezone=True), server_default=func.now())
    details = db.Column(db.Text, nullable=True) # JSON or text description

    user = db.relationship('TaiKhoan', backref='activities')

# === Event Listener cho Audit Log ===
@event.listens_for(KetQua, 'before_update')
def receive_before_update(mapper, connection, target):
    # Kiểm tra các trường điểm quan trọng xem có thay đổi không
    monitored_fields = ['diem_chuyen_can', 'diem_bai_tap', 'diem_kiem_tra', 'diem_thuc_hanh', 'diem_thi', 'diem_tong_ket']
    changes = []
    
    for field in monitored_fields:
        hist = get_history(target, field)
        if hist.has_changes():
            old_val = hist.deleted[0] if hist.deleted else None
            new_val = hist.added[0] if hist.added else None
            if old_val != new_val:
                changes.append(f"{field}: {old_val} -> {new_val}")
    
    if changes:
        # Lấy user hiện tại (cần xử lý khéo léo vì event listener chạy ở level thấp)
        # Tuy nhiên, trong context request của Flask, ta có thể access current_user nếu import
        # Lưu ý: current_user chỉ available trong request context.
        # Nếu update xảy ra ngoài request (vd: background job), có thể lỗi.
        # Ở đây ta giả định luôn chạy trong request.
        try:
            user_id = current_user.username if current_user.is_authenticated else 'SYSTEM'
        except:
            user_id = 'UNKNOWN'
            
        details = f"Updated grades for SV {target.ma_sv} in Subject {target.ma_mh}: " + ", ".join(changes)
        
        # Insert trực tiếp bằng connection để tránh session mess
        connection.execute(
            LichSuHoatDong.__table__.insert().values(
                user_id=user_id,
                action='UPDATE_GRADE',
                details=details,
                timestamp=datetime.now()
            )
        )

# --- 3. LOGIC XÁC THỰC VÀ PHÂN QUYỀN ---
@login_manager.user_loader
def load_user(user_id):
    return TaiKhoan.query.get(user_id)


_TEACHER_SCHEMA_PATCHED = False


@app.before_request
def apply_schema_patches():
    global _TEACHER_SCHEMA_PATCHED
    if _TEACHER_SCHEMA_PATCHED:
        return
    # Đảm bảo các bảng mới (lịch học, bài tập, ...) được tạo khi khởi động
    db.create_all()
    ensure_teacher_profile_columns()
    _TEACHER_SCHEMA_PATCHED = True

def strip_accents(value):
    """Remove Vietnamese accents to make weekday parsing more tolerant."""
    if not value:
        return ''
    return ''.join(
        ch for ch in unicodedata.normalize('NFD', value)
        if unicodedata.category(ch) != 'Mn'
    )

def parse_time_to_minutes(time_str):
    """Convert HH:MM string (or variants) to minutes from 00:00."""
    if not time_str:
        return None
    try:
        cleaned = time_str.lower().replace('h', ':').replace('.', ':')
        parts = cleaned.split(':')
        hour = int(parts[0].strip()) if parts[0].strip() else 0
        minute = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else 0
        return hour * 60 + minute
    except (ValueError, AttributeError, IndexError):
        return None

def format_minutes(total_minutes):
    hours = int(total_minutes // 60)
    minutes = int(total_minutes % 60)
    return f"{hours:02d}:{minutes:02d}"

def resolve_day_for_item(item, day_defs, day_lookup):
    """Return (day_index, label) for a LichHoc item based on ngay_hoc or thu_trong_tuan."""
    if item.ngay_hoc:
        idx = min(item.ngay_hoc.weekday(), 6)
        label = f"{day_defs[idx]['label']} ({item.ngay_hoc.strftime('%d/%m')})"
        return idx, label

    raw_day = (item.thu_trong_tuan or '').strip()
    if not raw_day:
        return None, 'Chưa rõ'

    normalized = strip_accents(raw_day).lower()
    normalized = normalized.replace('thu', 'thu ')
    normalized = ' '.join(normalized.split())

    for key, idx in day_lookup.items():
        if key in normalized:
            return idx, day_defs[idx]['label']

    digits = ''.join(ch for ch in normalized if ch.isdigit())
    if digits:
        try:
            num = int(digits)
            if num == 8:
                return 6, day_defs[6]['label']
            if 2 <= num <= 7:
                idx = num - 2
                return idx, day_defs[idx]['label']
        except ValueError:
            pass

    return None, raw_day

def build_week_view(schedule_items, start_date=None):
    """Prepare week-view friendly data (by weekday, with time offsets) for templates."""
    day_defs = [
        {"key": "mon", "label": "Thứ 2", "short": "T2"},
        {"key": "tue", "label": "Thứ 3", "short": "T3"},
        {"key": "wed", "label": "Thứ 4", "short": "T4"},
        {"key": "thu", "label": "Thứ 5", "short": "T5"},
        {"key": "fri", "label": "Thứ 6", "short": "T6"},
        {"key": "sat", "label": "Thứ 7", "short": "T7"},
        {"key": "sun", "label": "Chủ nhật", "short": "CN"},
    ]
    day_lookup = {
        'thu 2': 0, 'thu2': 0, 't2': 0, 'thu hai': 0,
        'thu 3': 1, 'thu3': 1, 't3': 1, 'thu ba': 1,
        'thu 4': 2, 'thu4': 2, 't4': 2, 'thu tu': 2,
        'thu 5': 3, 'thu5': 3, 't5': 3, 'thu nam': 3,
        'thu 6': 4, 'thu6': 4, 't6': 4, 'thu sau': 4,
        'thu 7': 5, 'thu7': 5, 't7': 5, 'thu bay': 5,
        'chu nhat': 6, 'chunhat': 6, 'cn': 6,
    }

    events_by_day = {d['key']: [] for d in day_defs}
    
    # Tính toán ngày cụ thể cho từng thứ trong tuần
    day_dates = {d['key']: None for d in day_defs}
    if start_date:
        for i, d in enumerate(day_defs):
            current_day_date = start_date + timedelta(days=i)
            day_dates[d['key']] = current_day_date.strftime('%d/%m')

    extras = []
    min_start = 7 * 60
    max_end = 17 * 60

    for item in schedule_items:
        start_min = parse_time_to_minutes(item.gio_bat_dau) or min_start
        end_min = parse_time_to_minutes(item.gio_ket_thuc)
        if end_min is None or end_min <= start_min:
            end_min = start_min + 90

        min_start = min(min_start, start_min)
        max_end = max(max_end, end_min)

        day_idx, day_label = resolve_day_for_item(item, day_defs, day_lookup)

        teacher_account = getattr(item, 'giao_vien', None)
        teacher_profile = getattr(teacher_account, 'giao_vien', None) if teacher_account else None
        teacher_name = None
        if teacher_profile and getattr(teacher_profile, 'ho_ten', None):
            teacher_name = teacher_profile.ho_ten
        elif teacher_account and getattr(teacher_account, 'username', None):
            teacher_name = teacher_account.username
        else:
            teacher_name = item.ma_gv

        event_data = {
            'id': item.id,
            'title': item.tieu_de,
            'class': item.lop,
            'group': getattr(item, 'nhom', None),
            'subject': item.mon_hoc.ten_mh if getattr(item, 'mon_hoc', None) else item.ma_mh,
            'room': item.phong,
            'teacher': teacher_name,
            'note': item.ghi_chu,
            'start_time': item.gio_bat_dau,
            'end_time': item.gio_ket_thuc,
            'start_min': start_min,
            'end_min': end_min,
            'time_label': f"{item.gio_bat_dau or '?'} - {item.gio_ket_thuc or '?'}",
        }

        if day_idx is None:
            extras.append(event_data)
            continue

        day_key = day_defs[day_idx]['key']
        if item.ngay_hoc and not day_dates[day_key]:
            day_dates[day_key] = item.ngay_hoc.strftime('%d/%m')

        event_data['day_label'] = day_label or day_defs[day_idx]['label']
        events_by_day[day_key].append(event_data)

    scale_start = 7 * 60  # 07:00
    scale_end = 18 * 60   # 18:00
    if min_start < scale_start:
        scale_start = int(math.floor(min_start / 60) * 60)
    if max_end > scale_end:
        scale_end = int(math.ceil(max_end / 60) * 60)
    range_minutes = max(scale_end - scale_start, 60)
    time_slots = list(range(scale_start, scale_end + 1, 60))

    for day_key, events in events_by_day.items():
        events.sort(key=lambda ev: (ev['start_min'], ev['end_min']))
        for ev in events:
            duration = max(ev['end_min'] - ev['start_min'], 45)
            offset = max(ev['start_min'] - scale_start, 0)
            ev['top_pct'] = round(offset / range_minutes * 100, 3)
            ev['height_pct'] = round(duration / range_minutes * 100, 3)
            ev['time_label'] = f"{ev['start_time'] or '?'} - {ev['end_time'] or '?'}"

    weekly_data = {
        'days': day_defs,
        'events_by_day': events_by_day,
        'time_slots': [{'label': format_minutes(slot), 'value': slot} for slot in time_slots],
        'scale_start': scale_start,
        'scale_end': scale_end,
        'extra_events': extras,
        'day_dates': day_dates,
    }
    weekly_data['has_events'] = any(events_by_day[d['key']] for d in day_defs) or bool(extras)
    return weekly_data

class VaiTroEnum(enum.Enum):
    SINHVIEN = 'SINHVIEN'
    GIAOVIEN = 'GIAOVIEN'
    ADMIN = 'ADMIN'

# ... (skip to role_required)

def role_required(*vai_tros):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            
            # Normalize user role to string
            user_role = current_user.vai_tro
            if hasattr(user_role, 'value'):
                user_role = user_role.value
            else:
                user_role = str(user_role)
            
            # Normalize allowed roles to strings
            allowed_roles = []
            for r in vai_tros:
                if hasattr(r, 'value'):
                    allowed_roles.append(r.value)
                else:
                    allowed_roles.append(str(r))
            
            # Debug logging
            print(f"DEBUG: User={current_user.username}, Role={user_role}, Allowed={allowed_roles}")
            print(f"DEBUG: Raw vai_tros={vai_tros}")

            if user_role not in allowed_roles:
                print("DEBUG: Access Denied")
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.errorhandler(403)
def forbidden_page(e):
    return render_template('403.html'), 403

# --- 4. CÁC ROUTE (CHỨC NĂNG) ---
# (Giữ nguyên các route: home, login, logout, student_dashboard, student_profile, student_grades,
#  admin_dashboard, admin_manage_students, admin_add_student, admin_edit_student, admin_delete_student,
#  admin_manage_courses, admin_add_course, admin_edit_course, admin_delete_course,
#  admin_manage_grades, admin_enter_grades, admin_save_grades,
#  calculate_gpa_expression, calculate_gpa_4_expression, admin_reports_index)
@app.route('/')
def home():
    return redirect(url_for('login'))

# 4.1. Chức năng Chung
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.has_role('SINHVIEN'):
            return redirect(url_for('student_dashboard'))
        else:
            return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = TaiKhoan.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash('Đăng nhập thành công!', 'success')
            if user.has_role('SINHVIEN'):
                return redirect(url_for('student_dashboard'))
            else:
                # GIAOVIEN and ADMIN go to admin_dashboard
                return redirect(url_for('admin_dashboard'))
        else:
            flash('Sai tên đăng nhập hoặc mật khẩu.', 'danger')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Bạn đã đăng xuất.', 'success')
    return redirect(url_for('login'))

# 4.2. Chức năng của Sinh viên
@app.route('/student/dashboard')
@login_required
@role_required(VaiTroEnum.SINHVIEN)
def student_dashboard():
    sinh_vien = SinhVien.query.get(current_user.username)
    ma_sv = current_user.username

    # Lấy điểm và tạo dữ liệu biểu đồ
    results = db.session.query(
        MonHoc.ma_mh,
        KetQua.diem_tong_ket,
        KetQua.diem_chu
    ).join(
        KetQua, MonHoc.ma_mh == KetQua.ma_mh
    ).filter(
        KetQua.ma_sv == ma_sv
    ).order_by(MonHoc.ma_mh).all()

    chart_points = [
        (row.ma_mh, float(row.diem_tong_ket))
        for row in results
        if row.diem_tong_ket is not None
    ]
    chart_labels = [label for label, _ in chart_points]
    chart_data = [score for _, score in chart_points]

    return render_template(
        'student_dashboard.html',
        sinh_vien=sinh_vien,
        chart_labels=chart_labels,
        chart_data=chart_data
    )

@app.route('/student/profile', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.SINHVIEN)
def student_profile():
    sinh_vien = SinhVien.query.get_or_404(current_user.username)

    if request.method == 'POST':
        try:
            sinh_vien.ho_ten = request.form.get('ho_ten')
            sinh_vien.ngay_sinh = db.func.date(request.form.get('ngay_sinh')) if request.form.get('ngay_sinh') else None # Xử lý ngày trống
            sinh_vien.email = request.form.get('email')
            sinh_vien.location = request.form.get('location')

            new_password = request.form.get('new_password')
            if new_password:
                current_user.password_hash = generate_password_hash(new_password)
                flash('Cập nhật mật khẩu thành công!', 'success')

            db.session.commit()
            flash('Cập nhật thông tin cá nhân thành công!', 'success')
            return redirect(url_for('student_profile'))

        except Exception as e:
            db.session.rollback()
            if 'UNIQUE constraint failed: sinh_vien.email' in str(e):
                 flash('Lỗi: Email này đã được sử dụng bởi một tài khoản khác.', 'danger')
            else:
                flash(f'Lỗi khi cập nhật thông tin: {e}', 'danger')

    return render_template('student_profile.html', sv=sinh_vien)

@app.route('/student/grades')
@login_required
@role_required(VaiTroEnum.SINHVIEN)
def student_grades():
    ma_sv = current_user.username
    
    # Lấy tất cả thông tin điểm và môn học, sắp xếp theo HỌC KỲ
    results_raw = db.session.query(
        MonHoc.ma_mh,
        MonHoc.ten_mh,
        MonHoc.so_tin_chi,
        MonHoc.hoc_ky,
        MonHoc.percent_cc,
        MonHoc.percent_bt,
        MonHoc.percent_kt,
        MonHoc.percent_th,
        MonHoc.percent_thi,
        KetQua.diem_chuyen_can,
        KetQua.diem_bai_tap,
        KetQua.diem_kiem_tra,
        KetQua.diem_thuc_hanh,
        KetQua.diem_thi,
        KetQua.diem_tong_ket,
        KetQua.diem_chu
    ).select_from(MonHoc).join(
        KetQua, and_(MonHoc.ma_mh == KetQua.ma_mh, KetQua.ma_sv == ma_sv), isouter=True
    ).order_by(MonHoc.hoc_ky, MonHoc.ma_mh).all()

    # Khởi tạo biến cho GPA tích lũy
    total_points_10_cumulative = 0
    total_points_4_cumulative = 0
    total_credits_cumulative = 0
    
    # Cấu trúc dữ liệu mới để nhóm theo học kỳ
    semesters_data = {} 

    chart_labels = [] 
    chart_data = []

    for row in results_raw:
        hoc_ky = row.hoc_ky
        
        if hoc_ky not in semesters_data:
            semesters_data[hoc_ky] = {
                'grades': [],
                'total_points_10': 0,
                'total_points_4': 0,
                'total_credits': 0,
                'gpa_10': 0.0,
                'gpa_4': 0.0
            }

        diem_tk = row.diem_tong_ket
        diem_chu = row.diem_chu

        if diem_tk is not None:
            diem_he_4 = convert_10_to_4_scale(diem_tk)
            
            semesters_data[hoc_ky]['total_points_10'] += diem_tk * row.so_tin_chi
            semesters_data[hoc_ky]['total_points_4'] += diem_he_4 * row.so_tin_chi
            semesters_data[hoc_ky]['total_credits'] += row.so_tin_chi
            
            total_points_10_cumulative += diem_tk * row.so_tin_chi
            total_points_4_cumulative += diem_he_4 * row.so_tin_chi
            total_credits_cumulative += row.so_tin_chi

            chart_labels.append(f"HK{hoc_ky}-{row.ma_mh}")
            chart_data.append(diem_tk)

        semesters_data[hoc_ky]['grades'].append({
            'ma_mh': row.ma_mh,
            'ten_mh': row.ten_mh,
            'so_tin_chi': row.so_tin_chi,
            'percent_cc': row.percent_cc,
            'percent_bt': row.percent_bt,
            'percent_kt': row.percent_kt,
            'percent_th': row.percent_th,
            'percent_thi': row.percent_thi,
            'diem_cc': row.diem_chuyen_can,
            'diem_bt': row.diem_bai_tap,
            'diem_kt': row.diem_kiem_tra,
            'diem_th': row.diem_thuc_hanh,
            'diem_thi': row.diem_thi,
            'diem_tk': diem_tk,
            'diem_chu': diem_chu
        })

    # Tính toán GPA (Hệ 10 và Hệ 4) cho TỪNG học kỳ
    for ky in semesters_data:
        credits_ky = semesters_data[ky]['total_credits']
        if credits_ky > 0:
            semesters_data[ky]['gpa_10'] = semesters_data[ky]['total_points_10'] / credits_ky
            semesters_data[ky]['gpa_4'] = semesters_data[ky]['total_points_4'] / credits_ky

    # Tính GPA TÍCH LŨY (toàn bộ)
    gpa_10_cumulative = (total_points_10_cumulative / total_credits_cumulative) if total_credits_cumulative > 0 else 0.0
    gpa_4_cumulative = (total_points_4_cumulative / total_credits_cumulative) if total_credits_cumulative > 0 else 0.0

    # Xác định tổng số kỳ dựa trên hệ đào tạo
    sinh_vien = SinhVien.query.get(ma_sv)
    total_semesters = 9 if sinh_vien.he_dao_tao == 'KY_SU' else 8
    program_name = "Kỹ sư" if sinh_vien.he_dao_tao == 'KY_SU' else "Cử nhân"

    return render_template(
        'student_grades.html',
        semesters_data=semesters_data, # Gửi cấu trúc dữ liệu mới
        gpa_10_cumulative=gpa_10_cumulative,
        gpa_4_cumulative=gpa_4_cumulative,
        chart_labels=chart_labels,
        chart_data=chart_data,
        total_semesters=total_semesters,
        program_name=program_name
    )


@app.route('/student/schedule')
@login_required
@role_required(VaiTroEnum.SINHVIEN)
def student_schedule():
    sv = SinhVien.query.get(current_user.username)
    lop_hoc = sv.lop if sv else None

    # --- Xử lý tuần ---
    week_start_str = request.args.get('week_start')
    today = date.today()
    
    if week_start_str:
        try:
            current_week_start = datetime.strptime(week_start_str, '%Y-%m-%d').date()
        except ValueError:
            current_week_start = today - timedelta(days=today.weekday())
    else:
        current_week_start = today - timedelta(days=today.weekday()) # Thứ 2 của tuần hiện tại

    current_week_end = current_week_start + timedelta(days=6) # Chủ nhật

    schedule_items = []
    if lop_hoc:
        # Query lịch học của lớp trong tuần đã chọn
        # Hoặc lịch học cố định (ngay_hoc is None)
        schedule_items = LichHoc.query.filter(
            LichHoc.lop == lop_hoc,
            (LichHoc.ngay_hoc == None) | 
            (LichHoc.ngay_hoc.between(current_week_start, current_week_end))
        ).order_by(
            LichHoc.ngay_hoc.asc(),
            LichHoc.thu_trong_tuan.asc(),
            LichHoc.gio_bat_dau.asc(),
            LichHoc.id.desc()
        ).all()

    week_view = build_week_view(schedule_items, current_week_start)
    
    prev_week_start = current_week_start - timedelta(days=7)
    next_week_start = current_week_start + timedelta(days=7)

    return render_template(
        'student_schedule.html',
        sv=sv,
        week_view=week_view,
        current_week_start=current_week_start,
        current_week_end=current_week_end,
        prev_week_start=prev_week_start,
        next_week_start=next_week_start
    )


@app.route('/student/assignments')
@login_required
@role_required(VaiTroEnum.SINHVIEN)
def student_assignments():
    sv = SinhVien.query.get(current_user.username)
    lop_hoc = sv.lop if sv else None

    assignments_data = []
    if lop_hoc:
        assignments = BaiTap.query.filter_by(lop_nhan=lop_hoc).order_by(
            case((BaiTap.han_nop == None, 1), else_=0),
            BaiTap.han_nop.asc(),
            BaiTap.created_at.desc()
        ).all()
        
        # Lấy danh sách bài làm của SV
        submissions = {bl.bai_tap_id: bl for bl in BaiLam.query.filter_by(ma_sv=current_user.username).all()}

        for asm in assignments:
            submission = submissions.get(asm.id)
            assignments_data.append({
                'assignment': asm,
                'submission': submission,
                'status': 'Đã nộp' if submission else 'Chưa nộp'
            })

    return render_template(
        'student_assignments.html',
        sv=sv,
        assignments_data=assignments_data, # Thay assignments bằng assignments_data
        today=date.today()
    )

@app.route('/student/assignments/submit/<int:assignment_id>', methods=['POST'])
@login_required
@role_required(VaiTroEnum.SINHVIEN)
def student_submit_homework(assignment_id):
    assignment = BaiTap.query.get_or_404(assignment_id)
    
    # Kiểm tra hạn nộp (nếu cần chặt chẽ)
    # if assignment.han_nop and assignment.han_nop < date.today():
    #     flash('Đã quá hạn nộp bài!', 'danger')
    #     return redirect(url_for('student_assignments'))

    file = request.files.get('file_nop')
    if file and allowed_file(file.filename):
        original_filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{original_filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
        
        # Kiểm tra xem đã nộp chưa để update hay create
        submission = BaiLam.query.filter_by(bai_tap_id=assignment_id, ma_sv=current_user.username).first()
        
        if submission:
            submission.file_path = unique_filename
            submission.ngay_nop = datetime.now()
            flash('Cập nhật bài nộp thành công!', 'success')
        else:
            new_submission = BaiLam(
                bai_tap_id=assignment_id,
                ma_sv=current_user.username,
                file_path=unique_filename
            )
            db.session.add(new_submission)
            flash('Nộp bài thành công!', 'success')
            
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi nộp bài: {e}', 'danger')
    else:
        flash('File không hợp lệ hoặc chưa chọn file.', 'warning')
        
    return redirect(url_for('student_assignments'))




# 4.3. Chức năng của Giáo viên
@app.route('/admin/dashboard')
@login_required
@role_required(VaiTroEnum.GIAOVIEN, VaiTroEnum.ADMIN) 
def admin_dashboard():
    """Trang mặc định cho giáo viên - luôn hiển thị danh sách Thông báo chung."""
    # ptit_notifications is defined globally or imported
    notifications = []
    for n in ptit_notifications:
        notifications.append(
            {
                "title": n["title"],
                "date": n["date"],
                "link": None
            }
        )

    return render_template(
        'admin_dashboard.html',
        notifications=notifications,
        has_real_announcements=False
    )

@app.route('/admin/schedule', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN, VaiTroEnum.ADMIN)
def admin_schedule():
    danh_sach_mon_hoc = MonHoc.query.order_by(MonHoc.ten_mh).all()
    lop_hoc_tuples = db.session.query(SinhVien.lop).distinct().order_by(SinhVien.lop).all()
    danh_sach_lop = [lop[0] for lop in lop_hoc_tuples if lop[0]]

    selected_lop = request.args.get('lop')

    if request.method == 'POST':
        lop = request.form.get('lop')
        tieu_de = (request.form.get('tieu_de') or '').strip()
        ma_mh = request.form.get('ma_mh') or None
        thu_trong_tuan = (request.form.get('thu_trong_tuan') or '').strip() or None
        ngay_hoc_raw = request.form.get('ngay_hoc')
        gio_bat_dau = (request.form.get('gio_bat_dau') or '').strip() or None
        gio_ket_thuc = (request.form.get('gio_ket_thuc') or '').strip() or None
        phong = (request.form.get('phong') or '').strip() or None
        ghi_chu = (request.form.get('ghi_chu') or '').strip() or None

        if not lop:
            flash('Vui lòng chọn hoặc nhập Lớp cho lịch học.', 'danger')
            return redirect(url_for('admin_schedule', lop=selected_lop))

        if not tieu_de:
            tieu_de = f'Lịch học {lop}' if not ma_mh else f'{ma_mh} - {lop}'

        ngay_hoc = None
        if ngay_hoc_raw:
            try:
                ngay_hoc = datetime.strptime(ngay_hoc_raw, '%Y-%m-%d').date()
            except ValueError:
                flash('Ngày học không hợp lệ. Định dạng chuẩn: YYYY-MM-DD', 'danger')
                return redirect(url_for('admin_schedule', lop=lop))

        try:
            new_item = LichHoc(
                tieu_de=tieu_de,
                lop=lop,
                ma_mh=ma_mh,
                ma_gv=current_user.username,
                thu_trong_tuan=thu_trong_tuan,
                ngay_hoc=ngay_hoc,
                gio_bat_dau=gio_bat_dau,
                gio_ket_thuc=gio_ket_thuc,
                phong=phong,
                ghi_chu=ghi_chu
            )
            db.session.add(new_item)
            db.session.commit()
            flash('Đã thêm lịch học/giảng dạy.', 'success')
            return redirect(url_for('admin_schedule', lop=lop))
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi lưu lịch học: {e}', 'danger')
            return redirect(url_for('admin_schedule'))

    schedule_query = LichHoc.query
    if selected_lop:
        schedule_query = schedule_query.filter_by(lop=selected_lop)

    # --- Xử lý tuần ---
    week_start_str = request.args.get('week_start')
    today = date.today()
    
    if week_start_str:
        try:
            current_week_start = datetime.strptime(week_start_str, '%Y-%m-%d').date()
        except ValueError:
            current_week_start = today - timedelta(days=today.weekday())
    else:
        current_week_start = today - timedelta(days=today.weekday()) # Thứ 2 của tuần hiện tại

    current_week_end = current_week_start + timedelta(days=6) # Chủ nhật

    # Lọc lịch:
    # 1. Lịch có ngày cụ thể nằm trong tuần này
    # 2. Lịch lặp lại (ngay_hoc is NULL) -> Hiển thị mọi tuần (hoặc có thể thêm logic ngày bắt đầu/kết thúc cho lịch lặp sau này)
    
    # Lấy tất cả rồi lọc bằng Python cho đơn giản với logic lặp lại, 
    # hoặc query phức tạp hơn. Với số lượng ít, lọc Python ok.
    # Tuy nhiên, để tối ưu, ta query: (ngay_hoc IS NULL) OR (ngay_hoc BETWEEN start AND end)
    
    schedule_items_all = schedule_query.filter(
        (LichHoc.ngay_hoc == None) | 
        (LichHoc.ngay_hoc.between(current_week_start, current_week_end))
    ).order_by(
        LichHoc.ngay_hoc.asc(),
        LichHoc.thu_trong_tuan.asc(),
        LichHoc.gio_bat_dau.asc(),
        LichHoc.id.desc()
    ).all()

    week_view = build_week_view(schedule_items_all, current_week_start)
    
    prev_week_start = current_week_start - timedelta(days=7)
    next_week_start = current_week_start + timedelta(days=7)

    return render_template(
        'admin_schedule.html',
        danh_sach_mon_hoc=danh_sach_mon_hoc,
        danh_sach_lop=danh_sach_lop,
        schedule_items=schedule_items_all,
        selected_lop=selected_lop,
        week_view=week_view,
        current_week_start=current_week_start,
        current_week_end=current_week_end,
        prev_week_start=prev_week_start,
        next_week_start=next_week_start
    )


@app.route('/teacher/myschedule')
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def teacher_schedule():
    # Lấy lịch giảng dạy của chính giáo viên này
    ma_gv = current_user.username
    
    # --- Xử lý tuần ---
    week_start_str = request.args.get('week_start')
    today = date.today()
    
    if week_start_str:
        try:
            current_week_start = datetime.strptime(week_start_str, '%Y-%m-%d').date()
        except ValueError:
            current_week_start = today - timedelta(days=today.weekday())
    else:
        current_week_start = today - timedelta(days=today.weekday()) # Thứ 2 của tuần hiện tại

    current_week_end = current_week_start + timedelta(days=6) # Chủ nhật

    # Lấy danh sách lớp để lọc
    filter_lop = request.args.get('lop', '')
    assigned_classes = db.session.query(LichHoc.lop).filter(LichHoc.ma_gv == ma_gv).distinct().order_by(LichHoc.lop).all()
    danh_sach_lop = [c[0] for c in assigned_classes if c[0]]

    # Query lịch của giáo viên
    query = LichHoc.query.filter(
        LichHoc.ma_gv == ma_gv,
        (LichHoc.ngay_hoc == None) | 
        (LichHoc.ngay_hoc.between(current_week_start, current_week_end))
    )
    
    if filter_lop:
        query = query.filter(LichHoc.lop == filter_lop)
        
    schedule_items = query.order_by(
        LichHoc.ngay_hoc.asc(),
        LichHoc.thu_trong_tuan.asc(),
        LichHoc.gio_bat_dau.asc(),
        LichHoc.id.desc()
    ).all()

    week_view = build_week_view(schedule_items, current_week_start)
    
    prev_week_start = current_week_start - timedelta(days=7)
    next_week_start = current_week_start + timedelta(days=7)

    return render_template(
        'teacher_schedule.html',
        week_view=week_view,
        current_week_start=current_week_start,
        current_week_end=current_week_end,
        prev_week_start=prev_week_start,
        next_week_start=next_week_start,
        danh_sach_lop=danh_sach_lop,
        filter_lop=filter_lop
    )


@app.route('/admin/schedule/<int:schedule_id>/delete', methods=['POST'])
@login_required
@role_required(VaiTroEnum.ADMIN)
def admin_delete_schedule(schedule_id):
    schedule = LichHoc.query.get_or_404(schedule_id)
    if schedule.ma_gv and schedule.ma_gv != current_user.username:
        abort(403)
    try:
        db.session.delete(schedule)
        db.session.commit()
        flash('Đã xóa lịch học/giảng dạy.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa lịch: {e}', 'danger')
    return redirect(request.referrer or url_for('admin_schedule'))


@app.route('/admin/assignments', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN, VaiTroEnum.ADMIN)
def admin_assignments():
    # Lấy danh sách lớp và môn học để điền vào form
    if current_user.has_role('ADMIN'):
        lop_hoc_tuples = db.session.query(SinhVien.lop).distinct().order_by(SinhVien.lop).all()
        danh_sach_lop = [lop[0] for lop in lop_hoc_tuples if lop[0]]
        danh_sach_mon_hoc = MonHoc.query.order_by(MonHoc.ten_mh).all()
    else:
        # Teacher: Filter based on PhanCong
        assigned_classes = db.session.query(PhanCong.lop).filter(PhanCong.ma_gv == current_user.username).distinct().all()
        danh_sach_lop = [lop[0] for lop in assigned_classes if lop[0]]
        assigned_subjects = db.session.query(MonHoc).join(PhanCong, MonHoc.ma_mh == PhanCong.ma_mh).filter(PhanCong.ma_gv == current_user.username).distinct().all()
        danh_sach_mon_hoc = assigned_subjects

    if request.method == 'POST':
        # Admin cannot create assignments (View Only)
        if current_user.has_role('ADMIN'):
            flash('Quản trị viên chỉ có quyền xem danh sách bài tập.', 'warning')
            return redirect(url_for('admin_assignments'))

        tieu_de = (request.form.get('tieu_de') or '').strip()
        noi_dung = (request.form.get('noi_dung') or '').strip()
        lop_nhan = request.form.get('lop_nhan')
        ma_mh = request.form.get('ma_mh') or None
        han_nop_str = request.form.get('han_nop')
        
        # Security Check: Ensure teacher is assigned to this class/subject
        assignment = PhanCong.query.filter_by(lop=lop_nhan, ma_mh=ma_mh, ma_gv=current_user.username).first()
        if not assignment:
             flash('Bạn không được phân công giảng dạy lớp/môn này.', 'danger')
             return redirect(url_for('admin_assignments'))

        han_nop = None
        if han_nop_str:
            try:
                han_nop = datetime.strptime(han_nop_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        # Xử lý file upload
        file = request.files.get('file_dinh_kem')
        filename_saved = None
        if file and allowed_file(file.filename):
            original_filename = secure_filename(file.filename)
            # Tạo tên file unique để tránh trùng
            unique_filename = f"{uuid.uuid4()}_{original_filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
            filename_saved = unique_filename

        new_homework = BaiTap(
            tieu_de=tieu_de,
            noi_dung=noi_dung,
            lop_nhan=lop_nhan,
            ma_mh=ma_mh,
            ma_gv=current_user.username,
            han_nop=han_nop,
            tep_dinh_kem=filename_saved
        )
        
        try:
            db.session.add(new_homework)
            db.session.commit()
            flash('Đã giao bài tập thành công!', 'success')
            return redirect(url_for('admin_assignments'))
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi giao bài tập: {e}', 'danger')

    # GET: Hiển thị form và danh sách
    if current_user.has_role('ADMIN'):
        # Admin sees ALL assignments
        bai_tap_list = BaiTap.query.order_by(BaiTap.created_at.desc()).all()
    else:
        # Teacher sees ONLY their assignments
        bai_tap_list = BaiTap.query.filter_by(ma_gv=current_user.username).order_by(BaiTap.created_at.desc()).all()

    return render_template('admin_assign_homework.html', 
                           danh_sach_lop=danh_sach_lop, 
                           danh_sach_mon_hoc=danh_sach_mon_hoc,
                           bai_tap_list=bai_tap_list)

@app.route('/uploads/<filename>')
@login_required
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/admin/assignments/<int:assignment_id>/delete', methods=['POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_delete_assignment(assignment_id):
    assignment = BaiTap.query.get_or_404(assignment_id)
    if assignment.ma_gv and assignment.ma_gv != current_user.username:
        abort(403)
    try:
        db.session.delete(assignment)
        db.session.commit()
        flash('Đã xóa bài tập.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa bài tập: {e}', 'danger')
    return redirect(request.referrer or url_for('admin_assignments'))








@app.route('/admin/students')
@login_required
@role_required(VaiTroEnum.ADMIN)
def admin_manage_students():
    search_ma_sv = request.args.get('ma_sv', '')
    search_ho_ten = request.args.get('ho_ten', '')
    filter_lop = request.args.get('lop', '')
    filter_khoa = request.args.get('khoa', '')

    query = SinhVien.query
    
    if search_ma_sv:
        query = query.filter(SinhVien.ma_sv.ilike(f'%{search_ma_sv}%'))
    if search_ho_ten:
        query = query.filter(SinhVien.ho_ten.ilike(f'%{search_ho_ten}%'))
    if filter_lop:
        query = query.filter(SinhVien.lop == filter_lop)
    if filter_khoa:
        query = query.filter(SinhVien.khoa == filter_khoa)

    students = query.order_by(SinhVien.ma_sv).all()

    # Filter Class Dropdown
    lop_hoc_tuples = db.session.query(SinhVien.lop).distinct().order_by(SinhVien.lop).all()
    danh_sach_lop = [lop[0] for lop in lop_hoc_tuples if lop[0]]

    khoa_tuples = db.session.query(SinhVien.khoa).distinct().order_by(SinhVien.khoa).all()
    danh_sach_khoa = [khoa[0] for khoa in khoa_tuples if khoa[0]]

    return render_template(
        'admin_manage_students.html',
        students=students,
        danh_sach_lop=danh_sach_lop,
        danh_sach_khoa=danh_sach_khoa,
        search_params={
            'ma_sv': search_ma_sv,
            'ho_ten': search_ho_ten,
            'lop': filter_lop,
            'khoa': filter_khoa
        }
    )

# === QUẢN LÝ GIÁO VIÊN ===
@app.route('/admin/teachers', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.ADMIN)
def admin_manage_teachers():
    if request.method == 'POST':
        # Thêm giáo viên mới
        username = request.form.get('username')
        password = request.form.get('password')
        ho_ten = request.form.get('ho_ten')
        email = request.form.get('email')
        khoa_bo_mon = request.form.get('khoa_bo_mon')
        hoc_vi = request.form.get('hoc_vi')
        so_dien_thoai = request.form.get('so_dien_thoai')

        if not username or not password or not ho_ten:
            flash('Vui lòng nhập đầy đủ Username, Password và Họ tên.', 'danger')
            return redirect(url_for('admin_manage_teachers'))

        existing_user = TaiKhoan.query.get(username)
        if existing_user:
            flash('Tên đăng nhập đã tồn tại.', 'danger')
            return redirect(url_for('admin_manage_teachers'))

        try:
            # 1. Tạo tài khoản
            new_account = TaiKhoan(username=username, vai_tro=VaiTroEnum.GIAOVIEN)
            new_account.set_password(password)
            db.session.add(new_account)
            
            # 2. Tạo thông tin giáo viên
            new_teacher = GiaoVien(
                ma_gv=username,
                ho_ten=ho_ten,
                email=email,
                khoa_bo_mon=khoa_bo_mon,
                hoc_vi=hoc_vi,
                so_dien_thoai=so_dien_thoai
            )
            db.session.add(new_teacher)
            
            db.session.commit()
            flash('Đã thêm giáo viên mới thành công.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi thêm giáo viên: {e}', 'danger')

        return redirect(url_for('admin_manage_teachers'))

    # GET: List teachers
    teachers = GiaoVien.query.order_by(GiaoVien.ma_gv).all()
    return render_template('admin_manage_teachers.html', teachers=teachers)

# === PHÂN CÔNG GIẢNG DẠY ===
@app.route('/admin/teaching-assignments', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.ADMIN)
def admin_teaching_assignments():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            ma_gv = request.form.get('ma_gv')
            ma_mh = request.form.get('ma_mh')
            lop = request.form.get('lop')
            
            if not ma_gv or not ma_mh or not lop:
                flash('Vui lòng chọn đầy đủ thông tin.', 'danger')
            else:
                # Check duplicate
                exists = PhanCong.query.filter_by(ma_gv=ma_gv, ma_mh=ma_mh, lop=lop).first()
                if exists:
                    flash('Phân công này đã tồn tại.', 'warning')
                else:
                    new_assignment = PhanCong(ma_gv=ma_gv, ma_mh=ma_mh, lop=lop)
                    db.session.add(new_assignment)
                    db.session.commit()
                    flash('Đã phân công thành công.', 'success')
                    
        elif action == 'delete':
            assignment_id = request.form.get('assignment_id')
            assignment = PhanCong.query.get(assignment_id)
            if assignment:
                db.session.delete(assignment)
                db.session.commit()
                flash('Đã xóa phân công.', 'success')
            else:
                flash('Phân công không tồn tại.', 'danger')
                
        return redirect(url_for('admin_teaching_assignments'))

    # GET
    assignments = PhanCong.query.order_by(PhanCong.created_at.desc()).all()
    teachers = GiaoVien.query.order_by(GiaoVien.ho_ten).all()
    subjects = MonHoc.query.order_by(MonHoc.ten_mh).all()
    classes = db.session.query(SinhVien.lop).distinct().order_by(SinhVien.lop).all()
    classes = [c[0] for c in classes if c[0]]
    
    return render_template('admin_teaching_assignments.html', 
                           assignments=assignments,
                           teachers=teachers,
                           subjects=subjects,
                           classes=classes)

@app.route('/admin/teachers/edit/<ma_gv>', methods=['POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_edit_teacher(ma_gv):
    teacher = GiaoVien.query.get_or_404(ma_gv)
    
    teacher.ho_ten = request.form.get('ho_ten')
    teacher.email = request.form.get('email')
    teacher.so_dien_thoai = request.form.get('so_dien_thoai')
    teacher.khoa_bo_mon = request.form.get('khoa_bo_mon')
    teacher.hoc_vi = request.form.get('hoc_vi')
    
    # Optional: Change password if provided
    new_password = request.form.get('new_password')
    if new_password and new_password.strip():
        account = TaiKhoan.query.get(ma_gv)
        if account:
            account.set_password(new_password)

    try:
        db.session.commit()
        flash(f'Đã cập nhật thông tin giáo viên {ma_gv}.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi cập nhật: {e}', 'danger')
        
    return redirect(url_for('admin_manage_teachers'))

@app.route('/admin/teachers/delete/<ma_gv>', methods=['POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_delete_teacher(ma_gv):
    # Không cho phép tự xóa chính mình
    if ma_gv == current_user.username:
        flash('Bạn không thể xóa tài khoản của chính mình.', 'danger')
        return redirect(url_for('admin_manage_teachers'))

    account = TaiKhoan.query.get_or_404(ma_gv)
    try:
        db.session.delete(account) # Cascade delete will remove GiaoVien entry
        db.session.commit()
        flash(f'Đã xóa giáo viên {ma_gv}.', 'success')
    except Exception as e:
        db.session.rollback()
    return redirect(url_for('admin_manage_teachers'))

@app.route('/admin/profile', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN, VaiTroEnum.ADMIN)
def admin_profile():
    user_role = current_user.vai_tro
    if hasattr(user_role, 'value'):
        user_role = user_role.value
    else:
        user_role = str(user_role)

    profile = None
    is_admin = (user_role == 'ADMIN')

    if is_admin:
        profile = NhanVien.query.get(current_user.username)
        if not profile:
            # Lazy creation for Admin profile
            profile = NhanVien(ma_nv=current_user.username, ho_ten='Quản trị viên')
            db.session.add(profile)
            db.session.commit()
    else:
        profile = GiaoVien.query.get(current_user.username)
    
    if not profile:
        flash('Không tìm thấy thông tin người dùng.', 'danger')
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        profile.ho_ten = request.form.get('ho_ten')
        profile.email = request.form.get('email')
        profile.so_dien_thoai = request.form.get('so_dien_thoai')
        
        if is_admin:
            profile.phong_ban = request.form.get('phong_ban')
            profile.chuc_vu = request.form.get('chuc_vu')
        else:
            profile.khoa_bo_mon = request.form.get('khoa_bo_mon')
            profile.hoc_vi = request.form.get('hoc_vi')
            profile.van_phong = request.form.get('van_phong')
            profile.linh_vuc = request.form.get('linh_vuc')
        
        # Change password
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if new_password:
            if new_password != confirm_password:
                flash('Mật khẩu xác nhận không khớp.', 'danger')
            else:
                current_user.set_password(new_password)
                flash('Đã cập nhật mật khẩu.', 'success')

        try:
            db.session.commit()
            flash('Cập nhật thông tin thành công.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi cập nhật: {e}', 'danger')
            
        return redirect(url_for('admin_profile'))

    return render_template('admin_profile.html', teacher=profile, is_admin=is_admin)

@app.route('/admin/students/add', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.ADMIN)
def admin_add_student():
    if request.method == 'POST':
        ma_sv = request.form.get('ma_sv')
        ho_ten = request.form.get('ho_ten')
        ngay_sinh = request.form.get('ngay_sinh')
        lop = request.form.get('lop')
        khoa = request.form.get('khoa')
        he_dao_tao = request.form.get('he_dao_tao', 'CU_NHAN')
        email = request.form.get('email')
        location = request.form.get('location')

        existing_user = TaiKhoan.query.get(ma_sv)
        if existing_user:
            flash('Lỗi: Mã sinh viên đã tồn tại.', 'danger')
            return redirect(url_for('admin_add_student'))

        try:
            default_password = f"{ma_sv}@123"
            new_account = TaiKhoan(
                username=ma_sv,
                vai_tro=VaiTroEnum.SINHVIEN.value
            )
            new_account.set_password(default_password)

            new_student = SinhVien(
                ma_sv=ma_sv,
                ho_ten=ho_ten,
                ngay_sinh=db.func.date(ngay_sinh) if ngay_sinh else None, # Xử lý ngày trống
                lop=lop,
                khoa=khoa,
                he_dao_tao=he_dao_tao,
                email=email,
                location=location
            )

            db.session.add(new_account)
            db.session.add(new_student)
            db.session.commit()

            flash('Thêm sinh viên và tài khoản thành công!', 'success')
            return redirect(url_for('admin_manage_students'))

        except Exception as e:
            db.session.rollback()
            flash(f'Đã xảy ra lỗi: {e}', 'danger')
            return redirect(url_for('admin_add_student'))

    return render_template('admin_add_student.html')

@app.route('/admin/students/edit/<ma_sv>', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.ADMIN)
def admin_edit_student(ma_sv):
    sv = SinhVien.query.get_or_404(ma_sv)

    if request.method == 'POST':
        try:
            sv.ho_ten = request.form.get('ho_ten')
            sv.ngay_sinh = db.func.date(request.form.get('ngay_sinh')) if request.form.get('ngay_sinh') else None # Xử lý ngày trống
            sv.lop = request.form.get('lop')
            sv.khoa = request.form.get('khoa')
            sv.he_dao_tao = request.form.get('he_dao_tao')
            # Thêm cập nhật email và location nếu có form
            sv.email = request.form.get('email')
            sv.location = request.form.get('location')


            db.session.commit()
            flash('Cập nhật thông tin sinh viên thành công!', 'success')
            return redirect(url_for('admin_manage_students'))

        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi cập nhật: {e}', 'danger')

    # Cần tạo template admin_edit_student.html với form đầy đủ
    return render_template('admin_edit_student.html', sv=sv)


@app.route('/admin/students/delete/<ma_sv>', methods=['POST'])
@login_required
@role_required(VaiTroEnum.ADMIN)
def admin_delete_student(ma_sv):
    sv = SinhVien.query.get_or_404(ma_sv)
    try:
        db.session.delete(sv) # Cascade delete sẽ xóa TaiKhoan và KetQua
        db.session.commit()
        flash('Đã xóa sinh viên và tài khoản liên quan thành công!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa sinh viên: {e}', 'danger')
    return redirect(url_for('admin_manage_students'))

# 4.4. Quản lý Môn học
@app.route('/admin/courses')
@login_required
@role_required(VaiTroEnum.GIAOVIEN, VaiTroEnum.ADMIN)
def admin_manage_courses():
    if current_user.has_role('ADMIN'):
        # Admin thấy tất cả môn học
        courses = MonHoc.query.order_by(MonHoc.hoc_ky, MonHoc.ma_mh).all()
        return render_template('admin_manage_courses.html', courses=courses)
    else:
        # Giáo viên chỉ thấy môn được phân công
        # Query lấy thông tin môn học, lớp và số lượng sinh viên
        # Result tuple: (MonHoc, lop, student_count)
        results = db.session.query(
            MonHoc, 
            PhanCong.lop,
            func.count(SinhVien.ma_sv).label('student_count')
        ).join(PhanCong, MonHoc.ma_mh == PhanCong.ma_mh)\
         .outerjoin(SinhVien, PhanCong.lop == SinhVien.lop)\
         .filter(PhanCong.ma_gv == current_user.username)\
         .group_by(MonHoc.ma_mh, PhanCong.lop)\
         .order_by(MonHoc.hoc_ky, MonHoc.ma_mh).all()
        
        # Transform results for easier template usage
        teacher_courses = []
        for mh, lop, count in results:
            teacher_courses.append({
                'ma_mh': mh.ma_mh,
                'ten_mh': mh.ten_mh,
                'so_tin_chi': mh.so_tin_chi,
                'percent_cc': mh.percent_cc,
                'percent_bt': mh.percent_bt,
                'percent_kt': mh.percent_kt,
                'percent_th': mh.percent_th,
                'percent_thi': mh.percent_thi,
                'lop': lop,
                'student_count': count
            })
            
        return render_template('admin_manage_courses.html', courses=teacher_courses)

@app.route('/admin/courses/add', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.ADMIN)
def admin_add_course():
    if request.method == 'POST':
        ma_mh = request.form.get('ma_mh')
        ten_mh = request.form.get('ten_mh')
        so_tin_chi = request.form.get('so_tin_chi')
        # Lấy dữ liệu học kỳ
        hoc_ky = request.form.get('hoc_ky') 

        existing = MonHoc.query.get(ma_mh)
        if existing:
            flash('Lỗi: Mã môn học đã tồn tại.', 'danger')
            return redirect(url_for('admin_add_course'))

        try:
            new_course = MonHoc(
                ma_mh=ma_mh,
                ten_mh=ten_mh,
                so_tin_chi=int(so_tin_chi),
                # Thêm học kỳ vào
                hoc_ky=int(hoc_ky),
                # Thêm trọng số
                percent_cc=int(request.form.get('percent_cc', 10)),
                percent_bt=int(request.form.get('percent_bt', 0)),
                percent_kt=int(request.form.get('percent_kt', 0)),
                percent_th=int(request.form.get('percent_th', 0)),
                percent_thi=int(request.form.get('percent_thi', 90)) 
            )
            db.session.add(new_course)
            db.session.commit()
            flash('Thêm môn học mới thành công!', 'success')
            return redirect(url_for('admin_manage_courses'))

        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi thêm môn học: {e}', 'danger')

    return render_template('admin_add_course.html')

@app.route('/admin/courses/edit/<ma_mh>', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.ADMIN)
def admin_edit_course(ma_mh):
    course = MonHoc.query.get_or_404(ma_mh)

    if request.method == 'POST':
        try:
            course.ten_mh = request.form.get('ten_mh')
            course.so_tin_chi = int(request.form.get('so_tin_chi'))
            # Cập nhật học kỳ
            course.hoc_ky = int(request.form.get('hoc_ky'))
            
            # Cập nhật trọng số
            course.percent_cc = int(request.form.get('percent_cc', 10))
            course.percent_bt = int(request.form.get('percent_bt', 0))
            course.percent_kt = int(request.form.get('percent_kt', 0))
            course.percent_th = int(request.form.get('percent_th', 0))
            course.percent_thi = int(request.form.get('percent_thi', 90)) 
            
            db.session.commit()
            flash('Cập nhật môn học thành công!', 'success')
            return redirect(url_for('admin_manage_courses'))

        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi cập nhật: {e}', 'danger')

    return render_template('admin_edit_course.html', course=course)

@app.route('/admin/courses/delete/<ma_mh>', methods=['POST'])
@login_required
@role_required(VaiTroEnum.ADMIN)
def admin_delete_course(ma_mh):
    course = MonHoc.query.get_or_404(ma_mh)
    try:
        db.session.delete(course) # Cascade delete sẽ xóa KetQua
        db.session.commit()
        flash('Đã xóa môn học thành công!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa môn học: {e}', 'danger')
    return redirect(url_for('admin_manage_courses'))

# 4.5. Quản lý Điểm
# === THAY THẾ HÀM admin_manage_grades CŨ BẰNG HÀM NÀY ===
@app.route('/admin/grades', methods=['GET']) # Chỉ dùng GET
@login_required
@role_required(VaiTroEnum.GIAOVIEN, VaiTroEnum.ADMIN)
def admin_manage_grades():
    # Lấy danh sách Lớp và Môn học cho dropdown
    if current_user.has_role('ADMIN'):
        lop_hoc_tuples = db.session.query(SinhVien.lop).distinct().order_by(SinhVien.lop).all()
        danh_sach_lop = [lop[0] for lop in lop_hoc_tuples if lop[0]]
        danh_sach_mon_hoc = MonHoc.query.order_by(MonHoc.ten_mh).all()
    else:
        # Nếu là Giáo viên, chỉ lấy các lớp và môn học được phân công trong PhanCong
        assigned_classes = db.session.query(PhanCong.lop).filter(PhanCong.ma_gv == current_user.username).distinct().all()
        danh_sach_lop = [lop[0] for lop in assigned_classes if lop[0]]
        
        assigned_subjects = db.session.query(MonHoc).join(PhanCong, MonHoc.ma_mh == PhanCong.ma_mh).filter(PhanCong.ma_gv == current_user.username).distinct().all()
        danh_sach_mon_hoc = assigned_subjects

    # Lấy Lớp và Môn học được chọn từ URL (nếu có)
    selected_lop = request.args.get('lop', None)
    selected_mh_id = request.args.get('ma_mh', None)

    grades_data = []
    selected_mon_hoc = None

    # Nếu Lớp và Môn học đã được chọn -> Truy vấn điểm chi tiết
    if selected_lop and selected_mh_id:
        selected_mon_hoc = MonHoc.query.get(selected_mh_id)
        if selected_mon_hoc:
            # Lấy thông tin SV và điểm của họ cho môn này
            grades_data = db.session.query(
                SinhVien.ma_sv,
                SinhVien.ho_ten,
                KetQua.diem_chuyen_can,
                KetQua.diem_bai_tap,
                KetQua.diem_kiem_tra,
                KetQua.diem_thuc_hanh,
                KetQua.diem_thi,
                KetQua.diem_tong_ket,
                KetQua.diem_tong_ket_4,
                KetQua.diem_chu
            ).select_from(SinhVien).outerjoin( # LEFT JOIN để lấy cả SV chưa có điểm
                KetQua, and_(SinhVien.ma_sv == KetQua.ma_sv, KetQua.ma_mh == selected_mh_id)
            ).filter(
                SinhVien.lop == selected_lop # Lọc theo lớp
            ).order_by(SinhVien.ma_sv).all()

    return render_template(
        'admin_manage_grades.html',
        danh_sach_lop=danh_sach_lop,
        danh_sach_mon_hoc=danh_sach_mon_hoc,
        selected_lop=selected_lop,           # Gửi lớp đã chọn
        selected_mh_id=selected_mh_id,       # Gửi mã môn đã chọn
        selected_mon_hoc=selected_mon_hoc, # Gửi thông tin môn học đã chọn
        grades_data=grades_data            # Gửi danh sách điểm chi tiết
    )
# =======================================================

@app.route('/admin/grades/enter/<lop>/<ma_mh>', methods=['GET'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN, VaiTroEnum.ADMIN)
def admin_enter_grades(lop, ma_mh):
    # Security Check for Teachers
    if not current_user.has_role('ADMIN'):
        assignment = PhanCong.query.filter_by(lop=lop, ma_mh=ma_mh, ma_gv=current_user.username).first()
        if not assignment:
            flash('Bạn không được phân công giảng dạy lớp/môn này.', 'danger')
            return redirect(url_for('admin_manage_grades'))

    mon_hoc = MonHoc.query.get_or_404(ma_mh)
    sinh_vien_list = SinhVien.query.filter_by(lop=lop).order_by(SinhVien.ma_sv).all()

    if not sinh_vien_list:
        flash(f'Không tìm thấy sinh viên nào trong lớp {lop}.', 'warning')
        return redirect(url_for('admin_manage_grades'))

    # Lấy điểm thành phần hiện có
    diem_hien_co_raw = KetQua.query.filter(
        KetQua.ma_mh == ma_mh,
        KetQua.ma_sv.in_([sv.ma_sv for sv in sinh_vien_list])
    ).all()
    # Tạo dict lưu điểm của từng SV
    diem_hien_co_dict = {
        kq.ma_sv: {
            'cc': kq.diem_chuyen_can,
            'bt': kq.diem_bai_tap,
            'kt': kq.diem_kiem_tra,
            'th': kq.diem_thuc_hanh,
            'thi': kq.diem_thi,
            'tk': kq.diem_tong_ket,
            'tk_4': kq.diem_tong_ket_4,
            'chu': kq.diem_chu
        } for kq in diem_hien_co_raw
    }

    danh_sach_nhap_diem = []
    for sv in sinh_vien_list:
        scores = diem_hien_co_dict.get(sv.ma_sv, {}) 
        danh_sach_nhap_diem.append({
            'ma_sv': sv.ma_sv,
            'ho_ten': sv.ho_ten,
            'diem_cc': scores.get('cc'),
            'diem_bt': scores.get('bt'),
            'diem_kt': scores.get('kt'),
            'diem_th': scores.get('th'),
            'diem_thi': scores.get('thi'),
            'diem_tk': scores.get('tk'),
            'diem_tk_4': scores.get('tk_4'),
            'diem_chu': scores.get('chu')
        })

    return render_template(
        'admin_enter_grades.html',
        lop=lop,
        mon_hoc=mon_hoc,
        danh_sach_nhap_diem=danh_sach_nhap_diem
    )
# === THAY THẾ HÀM admin_save_grades CŨ BẰNG HÀM NÀY ===
@app.route('/admin/grades/save', methods=['POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN, VaiTroEnum.ADMIN)
def admin_save_grades():
    try:
        ma_mh = request.form.get('ma_mh')
        lop = request.form.get('lop') # Lấy lại để redirect
        
        # Security Check for Teachers
        if not current_user.has_role('ADMIN'):
             assignment = PhanCong.query.filter_by(lop=lop, ma_mh=ma_mh, ma_gv=current_user.username).first()
             if not assignment:
                 flash('Bạn không có quyền lưu điểm cho lớp/môn này.', 'danger')
                 return redirect(url_for('admin_manage_grades'))

        updated_count = 0
        created_count = 0

        # Dữ liệu form sẽ có dạng: diem_cc_MaSV, diem_bt_MaSV, ...
        scores_by_sv = {} 

        # 1. Gom điểm từ form vào dict
        for key, value in request.form.items():
            if key.startswith('diem_'):
                parts = key.split('_')
                if len(parts) == 3: # diem_type_MaSV
                    score_type = parts[1] # cc, bt, kt, th, thi
                    ma_sv = parts[2]

                    if ma_sv not in scores_by_sv:
                        scores_by_sv[ma_sv] = {'cc': None, 'bt': None, 'kt': None, 'th': None, 'thi': None}

                    try:
                        if value.strip(): 
                            score_float = float(value) 
                            if not (0 <= score_float <= 10):
                                raise ValueError("Điểm không hợp lệ 0-10")
                            
                            if score_type in scores_by_sv[ma_sv]:
                                 scores_by_sv[ma_sv][score_type] = score_float
                        
                    except (ValueError, TypeError):
                        flash(f'Lỗi: Điểm "{value}" ({score_type}) của SV {ma_sv} không hợp lệ. Giá trị này sẽ bị bỏ qua.', 'warning')

        # 2. Xử lý và lưu vào CSDL
        for ma_sv, scores in scores_by_sv.items():
            
            student_exists = SinhVien.query.get(ma_sv)
            if not student_exists: continue 

            existing_grade = KetQua.query.get((ma_sv, ma_mh))

            if all(v is None for v in scores.values()) and not existing_grade:
                continue

            if existing_grade:
                # UPDATE
                changed = False
                if scores['cc'] is not None and existing_grade.diem_chuyen_can != scores['cc']:
                    existing_grade.diem_chuyen_can = scores['cc']; changed = True
                if scores['bt'] is not None and existing_grade.diem_bai_tap != scores['bt']:
                    existing_grade.diem_bai_tap = scores['bt']; changed = True
                if scores['kt'] is not None and existing_grade.diem_kiem_tra != scores['kt']:
                    existing_grade.diem_kiem_tra = scores['kt']; changed = True
                if scores['th'] is not None and existing_grade.diem_thuc_hanh != scores['th']:
                    existing_grade.diem_thuc_hanh = scores['th']; changed = True
                if scores['thi'] is not None and existing_grade.diem_thi != scores['thi']:
                    existing_grade.diem_thi = scores['thi']; changed = True

                if changed:
                    existing_grade.calculate_final_score() 
                    updated_count += 1
            else:
                # INSERT: Tạo mới
                new_grade = KetQua(
                    ma_sv=ma_sv,
                    ma_mh=ma_mh,
                    diem_chuyen_can=scores['cc'],
                    diem_bai_tap=scores['bt'],
                    diem_kiem_tra=scores['kt'],
                    diem_thuc_hanh=scores['th'],
                    diem_thi=scores['thi']
                )
                new_grade.calculate_final_score()
                db.session.add(new_grade)
                created_count += 1


        if updated_count > 0 or created_count > 0:
            db.session.commit()
            flash(f'Lưu điểm thành công! (Bản ghi mới: {created_count}, Bản ghi cập nhật: {updated_count})', 'success')
        else:
            flash('Không có thay đổi nào về điểm được lưu.', 'info')

        # Quay lại đúng trang nhập điểm đó
        return redirect(url_for('admin_enter_grades', lop=lop, ma_mh=ma_mh))

    except Exception as e:
        db.session.rollback()
        flash(f'Đã xảy ra lỗi nghiêm trọng khi lưu điểm: {e}', 'danger')
        lop = request.form.get('lop')
        ma_mh = request.form.get('ma_mh')
        if lop and ma_mh:
             return redirect(url_for('admin_enter_grades', lop=lop, ma_mh=ma_mh))
        else:
             return redirect(url_for('admin_manage_grades'))
# ========================================================
# 4.6. Báo cáo & Thống kê
# === THAY THẾ HÀM calculate_gpa_expression CŨ ===
def calculate_gpa_expression():
    """Trả về biểu thức SQLAlchemy để tính GPA hệ 10 DỰA TRÊN ĐIỂM TỔNG KẾT."""
    # Chỉ tính tổng điểm và tín chỉ cho những môn ĐÃ CÓ điểm tổng kết
    total_points = func.sum(
        case(
            (KetQua.diem_tong_ket != None, KetQua.diem_tong_ket * MonHoc.so_tin_chi),
            else_=0.0 # Bỏ qua môn chưa có điểm TK
        )
    )
    total_credits = func.sum(
        case(
            (KetQua.diem_tong_ket != None, MonHoc.so_tin_chi),
            else_=0 # Không tính tín chỉ môn chưa có điểm TK
        )
    )
    # Trả về GPA, hoặc None nếu không có tín chỉ nào hợp lệ
    return case(
        (total_credits > 0, total_points / total_credits),
        else_ = None # GPA là None nếu chưa có môn nào hoàn thành
    ).label("gpa")
# =================================================
# === THAY THẾ HÀM calculate_gpa_4_expression CŨ ===
def calculate_gpa_4_expression():
    """Trả về biểu thức SQLAlchemy để tính GPA hệ 4 DỰA TRÊN ĐIỂM TỔNG KẾT."""
    # Chuyển điểm tổng kết (hệ 10) sang điểm hệ 4
    diem_he_4 = case(
        (KetQua.diem_tong_ket >= 8.5, 4.0),
        (KetQua.diem_tong_ket >= 8.0, 3.5),
        (KetQua.diem_tong_ket >= 7.0, 3.0),
        (KetQua.diem_tong_ket >= 6.5, 2.5),
        (KetQua.diem_tong_ket >= 5.5, 2.0),
        (KetQua.diem_tong_ket >= 5.0, 1.5),
        (KetQua.diem_tong_ket >= 4.0, 1.0),
        else_=0.0
    )

    # Chỉ tính tổng điểm và tín chỉ cho những môn ĐÃ CÓ điểm tổng kết
    total_points_4 = func.sum(
        case(
            (KetQua.diem_tong_ket != None, diem_he_4 * MonHoc.so_tin_chi),
            else_=0.0
        )
    )
    total_credits = func.sum(
        case(
            (KetQua.diem_tong_ket != None, MonHoc.so_tin_chi),
            else_=0
        )
    )
    # Trả về GPA 4, hoặc None nếu không có tín chỉ hợp lệ
    return case(
        (total_credits > 0, total_points_4 / total_credits),
        else_ = None
    ).label("gpa_4")
# ==================================================
@app.route('/admin/reports')
@login_required
@role_required(VaiTroEnum.GIAOVIEN, VaiTroEnum.ADMIN)
def admin_reports_index():
    return render_template('admin_reports_index.html')

@app.route('/admin/reports/high_gpa')
@login_required
@role_required(VaiTroEnum.GIAOVIEN, VaiTroEnum.ADMIN)
def admin_report_high_gpa():
    GPA4_THRESHOLD = 3.0
    gpa_10_expression = calculate_gpa_expression()
    gpa_4_expression = calculate_gpa_4_expression()

    query = db.session.query(
        SinhVien.ma_sv, SinhVien.ho_ten, SinhVien.lop,
        gpa_10_expression.label('gpa_10'), gpa_4_expression.label('gpa_4')
    ).join(
        KetQua, SinhVien.ma_sv == KetQua.ma_sv
    ).join(
        MonHoc, KetQua.ma_mh == MonHoc.ma_mh
    )

    # Permission Check for Teachers
    if not current_user.has_role('ADMIN'):
        assigned_classes = db.session.query(PhanCong.lop).filter(PhanCong.ma_gv == current_user.username).distinct().all()
        assigned_class_list = [c[0] for c in assigned_classes if c[0]]
        if not assigned_class_list:
             # Teacher has no classes, show empty list
             query = query.filter(1==0)
        else:
             query = query.filter(SinhVien.lop.in_(assigned_class_list))

    results = query.group_by(
        SinhVien.ma_sv, SinhVien.ho_ten, SinhVien.lop
    ).having(
        gpa_4_expression > GPA4_THRESHOLD
    ).order_by(
        gpa_4_expression.desc()
    ).all()

    def classify_gpa_4(gpa4):
        if gpa4 is None:
            return "Yếu"
        if gpa4 >= 3.6:
            return "Xuất sắc"
        elif gpa4 >= 3.2:
            return "Giỏi"
        elif gpa4 >= 2.5:
            return "Khá"
        elif gpa4 >= 2.0:
            return "Trung bình"
        else:
            return "Yếu"

    category_counts = {"Yếu": 0, "Trung bình": 0, "Khá": 0, "Giỏi": 0, "Xuất sắc": 0}
    for row in results:
        if row.gpa_4 is not None:
             category = classify_gpa_4(row.gpa_4)
             if category in category_counts:
                 category_counts[category] += 1
    chart_labels = list(category_counts.keys())
    chart_data = list(category_counts.values())

    return render_template(
        'admin_report_high_gpa.html',
        results=results,
        threshold=GPA4_THRESHOLD,
        chart_labels=chart_labels,
        chart_data=chart_data
    )

@app.route('/admin/reports/missing_grade', methods=['GET'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN, VaiTroEnum.ADMIN)
def admin_report_missing_grade():
    # Filter subjects for dropdown
    if current_user.has_role('ADMIN'):
        danh_sach_mon_hoc = MonHoc.query.order_by(MonHoc.ten_mh).all()
    else:
        # Teachers only see assigned subjects
        danh_sach_mon_hoc = db.session.query(MonHoc).join(PhanCong, MonHoc.ma_mh == PhanCong.ma_mh)\
            .filter(PhanCong.ma_gv == current_user.username)\
            .distinct()\
            .order_by(MonHoc.ten_mh).all()

    selected_mh_id = request.args.get('ma_mh')
    results = []
    selected_mon_hoc = None
    stats = {
        'total_students': 0,
        'completed': 0,
        'incomplete': 0,
        'completion_rate': 0
    }

    if selected_mh_id:
        # Validate permission for selected subject
        if not current_user.has_role('ADMIN'):
            # Check if teacher is assigned to this subject
            is_assigned = db.session.query(PhanCong).filter(
                PhanCong.ma_gv == current_user.username,
                PhanCong.ma_mh == selected_mh_id
            ).first()
            if not is_assigned:
                flash('Bạn không có quyền xem báo cáo của môn học này.', 'danger')
                return redirect(url_for('admin_report_missing_grade'))

        selected_mon_hoc = MonHoc.query.get(selected_mh_id)
        
        # 1. Determine required components
        required_components = []
        if selected_mon_hoc.percent_cc > 0: required_components.append(('Chuyên cần', 'diem_chuyen_can'))
        if selected_mon_hoc.percent_bt > 0: required_components.append(('Bài tập', 'diem_bai_tap'))
        if selected_mon_hoc.percent_kt > 0: required_components.append(('Kiểm tra', 'diem_kiem_tra'))
        if selected_mon_hoc.percent_th > 0: required_components.append(('Thực hành', 'diem_thuc_hanh'))
        if selected_mon_hoc.percent_thi > 0: required_components.append(('Thi', 'diem_thi'))

        # 2. Get target students
        query = SinhVien.query
        
        if not current_user.has_role('ADMIN'):
             assigned_classes_for_subject = db.session.query(PhanCong.lop).filter(
                 PhanCong.ma_gv == current_user.username,
                 PhanCong.ma_mh == selected_mh_id
             ).distinct().all()
             assigned_class_list = [c[0] for c in assigned_classes_for_subject if c[0]]
             
             if not assigned_class_list:
                 query = query.filter(1==0)
             else:
                 query = query.filter(SinhVien.lop.in_(assigned_class_list))
        
        all_students = query.order_by(SinhVien.lop, SinhVien.ma_sv).all()
        stats['total_students'] = len(all_students)

        # 3. Check grades
        for sv in all_students:
            kq = KetQua.query.filter_by(ma_sv=sv.ma_sv, ma_mh=selected_mh_id).first()
            missing = []
            
            if not kq:
                # Missing everything
                missing = [name for name, col in required_components]
            else:
                for name, col in required_components:
                    if getattr(kq, col) is None:
                        missing.append(name)
            
            if missing:
                results.append({
                    'ma_sv': sv.ma_sv,
                    'ho_ten': sv.ho_ten,
                    'lop': sv.lop,
                    'missing': missing
                })
            else:
                stats['completed'] += 1

        stats['incomplete'] = len(results)
        if stats['total_students'] > 0:
            stats['completion_rate'] = round((stats['completed'] / stats['total_students']) * 100, 1)

    return render_template(
        'admin_report_missing_grade.html',
        danh_sach_mon_hoc=danh_sach_mon_hoc,
        selected_mon_hoc=selected_mon_hoc,
        results=results,
        stats=stats
    )

@app.route('/admin/reports/class_gpa')
@login_required
@role_required(VaiTroEnum.GIAOVIEN, VaiTroEnum.ADMIN)
def admin_report_class_gpa():
    # Lấy danh sách lớp
    if current_user.has_role('ADMIN'):
        danh_sach_lop = db.session.query(SinhVien.lop).distinct().order_by(SinhVien.lop).all()
        danh_sach_lop = [l[0] for l in danh_sach_lop if l[0]]
    else:
        # Giáo viên chỉ thấy lớp được phân công
        assigned_classes = db.session.query(PhanCong.lop).filter(PhanCong.ma_gv == current_user.username).distinct().all()
        danh_sach_lop = [l[0] for l in assigned_classes if l[0]]

    selected_lop = request.args.get('lop')
    
    # Validate permission for selected class
    if selected_lop and not current_user.has_role('ADMIN'):
        if selected_lop not in danh_sach_lop:
            flash('Bạn không có quyền xem báo cáo của lớp này.', 'danger')
            return redirect(url_for('admin_report_class_gpa'))

    lop_gpa_10 = None
    lop_gpa_4 = None
    chart_labels = []
    chart_data = [] # Số lượng SV theo xếp loại
    
    # Dữ liệu cho biểu đồ so sánh (Tất cả các lớp)
    comparison_labels = []
    comparison_data = []

    # 1. Tính GPA trung bình cho TẤT CẢ các lớp để vẽ biểu đồ so sánh
    if danh_sach_lop:
        gpa_4_expr = calculate_gpa_4_expression()
        # Query tính GPA trung bình của từng lớp
        # Subquery: Tính GPA 4 cho từng sinh viên trước
        subquery = db.session.query(
            SinhVien.lop,
            SinhVien.ma_sv,
            gpa_4_expr.label('sv_gpa_4')
        ).join(KetQua, SinhVien.ma_sv == KetQua.ma_sv)\
         .join(MonHoc, KetQua.ma_mh == MonHoc.ma_mh)\
         .group_by(SinhVien.ma_sv, SinhVien.lop).subquery()

        # Main query: Group by Lớp và tính AVG(sv_gpa_4)
        query_stats = db.session.query(
            subquery.c.lop,
            func.avg(subquery.c.sv_gpa_4)
        ).group_by(subquery.c.lop)

        # Filter comparison chart for teachers
        if not current_user.has_role('ADMIN'):
             query_stats = query_stats.filter(subquery.c.lop.in_(danh_sach_lop))

        class_stats = query_stats.all()

        for cls_name, avg_gpa in class_stats:
            if cls_name:
                comparison_labels.append(cls_name)
                comparison_data.append(round(avg_gpa, 2) if avg_gpa else 0.0)

    # 2. Xử lý logic cho lớp được chọn
    if selected_lop:
        gpa_10_expr = calculate_gpa_expression()
        gpa_4_expr = calculate_gpa_4_expression()

        # Lấy danh sách SV của lớp đó kèm GPA
        # Lấy danh sách SV của lớp đó kèm GPA
        results = db.session.query(
            gpa_10_expr, gpa_4_expr
        ).select_from(SinhVien)\
         .join(KetQua, SinhVien.ma_sv == KetQua.ma_sv)\
         .join(MonHoc, KetQua.ma_mh == MonHoc.ma_mh)\
         .filter(SinhVien.lop == selected_lop)\
         .group_by(SinhVien.ma_sv).all()
        
        # Tính trung bình của lớp
        total_gpa_10 = 0
        count_10 = 0
        total_gpa_4 = 0
        count_4 = 0
        
        # Phân loại
        classification = {
            "Xuất sắc": 0, "Giỏi": 0, "Khá": 0, "Trung bình": 0, "Yếu": 0
        }

        for g10, g4 in results:
            if g10 is not None:
                total_gpa_10 += g10
                count_10 += 1
            
            if g4 is not None:
                total_gpa_4 += g4
                count_4 += 1
                
                # Phân loại dựa trên hệ 4
                if g4 >= 3.6: classification["Xuất sắc"] += 1
                elif g4 >= 3.2: classification["Giỏi"] += 1
                elif g4 >= 2.5: classification["Khá"] += 1
                elif g4 >= 2.0: classification["Trung bình"] += 1
                else: classification["Yếu"] += 1
            else:
                 classification["Yếu"] += 1 # Chưa có điểm tính là yếu hoặc chưa xếp loại

        if count_10 > 0: lop_gpa_10 = total_gpa_10 / count_10
        if count_4 > 0: lop_gpa_4 = total_gpa_4 / count_4
        
        chart_labels = list(classification.keys())
        chart_data = list(classification.values())

    return render_template('admin_report_class_gpa.html', 
                           danh_sach_lop=danh_sach_lop, 
                           selected_lop=selected_lop,
                           lop_gpa_10=lop_gpa_10,
                           lop_gpa_4=lop_gpa_4,
                           chart_labels=chart_labels,
                           chart_data=chart_data,
                           comparison_labels=comparison_labels,
                           comparison_data=comparison_data)



# === THÊM BÁO CÁO 4: PHÂN BỐ ĐIỂM ===


@app.route('/admin/audit_log')
@login_required
@role_required(VaiTroEnum.GIAOVIEN, VaiTroEnum.ADMIN)
def admin_audit_log():
    # Lấy logs, mới nhất lên đầu
    # Nếu là Admin, lấy hết
    if current_user.has_role('ADMIN'):
        logs = LichSuHoatDong.query.order_by(LichSuHoatDong.timestamp.desc()).limit(100).all()
    else:
        # Nếu là Giáo viên, lọc theo:
        # 1. Hành động của chính họ
        # 2. Hành động liên quan đến sinh viên thuộc lớp họ dạy (dựa vào details chứa Mã SV)
        
        # Lấy danh sách lớp được phân công
        assigned_classes = db.session.query(PhanCong.lop).filter(PhanCong.ma_gv == current_user.username).distinct().all()
        assigned_class_list = [c[0] for c in assigned_classes if c[0]]
        
        # Lấy danh sách Mã SV thuộc các lớp này
        assigned_students = []
        if assigned_class_list:
            assigned_students = db.session.query(SinhVien.ma_sv).filter(SinhVien.lop.in_(assigned_class_list)).all()
            assigned_student_ids = [s[0] for s in assigned_students]
        else:
            assigned_student_ids = []

        # Lấy nhiều log hơn để filter dần (vì filter text trong DB khó chính xác và chậm nếu dùng LIKE nhiều)
        # Lấy 500 log gần nhất để kiểm tra
        candidates = LichSuHoatDong.query.order_by(LichSuHoatDong.timestamp.desc()).limit(500).all()
        
        logs = []
        for log in candidates:
            # Case 1: Chính giáo viên làm
            if log.user_id == current_user.username:
                logs.append(log)
                continue
            
            # Case 2: Liên quan đến sinh viên của giáo viên
            # Kiểm tra xem details có chứa mã SV nào không
            if log.details and assigned_student_ids:
                # Cách đơn giản: check string containment
                # Để tối ưu, có thể check từng SV, nhưng nếu list SV lớn thì chậm.
                # Tuy nhiên, log.details thường ngắn.
                # Check nhanh:
                is_related = False
                for sv_id in assigned_student_ids:
                    if sv_id in log.details:
                        is_related = True
                        break
                
                if is_related:
                    logs.append(log)
            
            if len(logs) >= 100:
                break
    
    return render_template('admin_audit_log.html', logs=logs)
# ========================================

@app.route('/admin/reports/warning')
@login_required
@role_required(VaiTroEnum.GIAOVIEN, VaiTroEnum.ADMIN)
def admin_report_warning():
    # Lấy tất cả sinh viên
    query = SinhVien.query
    
    # Permission Check for Teachers
    if not current_user.has_role('ADMIN'):
        assigned_classes = db.session.query(PhanCong.lop).filter(PhanCong.ma_gv == current_user.username).distinct().all()
        assigned_class_list = [c[0] for c in assigned_classes if c[0]]
        if not assigned_class_list:
             query = query.filter(1==0)
        else:
             query = query.filter(SinhVien.lop.in_(assigned_class_list))
             
    sinh_vien_list = query.all()
    warning_list = []

    for sv in sinh_vien_list:
        # Lấy tất cả kết quả của SV
        ket_qua_list = KetQua.query.filter_by(ma_sv=sv.ma_sv).all()
        
        # 1. Tính GPA hệ 4
        total_credits = 0
        total_points_4 = 0
        failed_subjects = []

        for kq in ket_qua_list:
            mh = MonHoc.query.get(kq.ma_mh)
            if mh and kq.diem_tong_ket_4 is not None:
                total_credits += mh.so_tin_chi
                total_points_4 += kq.diem_tong_ket_4 * mh.so_tin_chi
            
            # 2. Kiểm tra môn rớt (Điểm F)
            if kq.diem_chu == 'F':
                failed_subjects.append({
                    'ma_mh': kq.ma_mh,
                    'ten_mh': mh.ten_mh if mh else kq.ma_mh,
                    'diem': kq.diem_tong_ket
                })

        gpa_4 = 0.0
        if total_credits > 0:
            gpa_4 = round(total_points_4 / total_credits, 2)

        # Điều kiện cảnh báo: GPA < 2.0 HOẶC có môn rớt
        if gpa_4 < 2.0 or failed_subjects:
            warning_list.append({
                'ma_sv': sv.ma_sv,
                'ho_ten': sv.ho_ten,
                'lop': sv.lop,
                'gpa_4': gpa_4,
                'failed_subjects': failed_subjects
            })

    return render_template('admin_report_warning.html', warning_list=warning_list)

@app.route('/admin/reports/custom_query', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.ADMIN)
def admin_report_custom_query():
    danh_sach_mon_hoc = MonHoc.query.order_by(MonHoc.ten_mh).all()
    
    results = []
    selected_mh_id = request.form.get('ma_mh') if request.method == 'POST' else None
    score_type = request.form.get('score_type') # '10', '4', 'char'
    operator = request.form.get('operator') # 'gt', 'lt', 'eq', 'gte', 'lte'
    value_input = request.form.get('value')

    if request.method == 'POST' and selected_mh_id and score_type and operator and value_input:
        query = db.session.query(
            SinhVien.ma_sv,
            SinhVien.ho_ten,
            SinhVien.lop,
            KetQua.diem_tong_ket,
            KetQua.diem_tong_ket_4,
            KetQua.diem_chu
        ).join(KetQua, SinhVien.ma_sv == KetQua.ma_sv).filter(
            KetQua.ma_mh == selected_mh_id
        )

        try:
            if score_type == '10':
                val = float(value_input)
                col = KetQua.diem_tong_ket
                if operator == 'gt': query = query.filter(col > val)
                elif operator == 'lt': query = query.filter(col < val)
                elif operator == 'eq': query = query.filter(col == val)
                elif operator == 'gte': query = query.filter(col >= val)
                elif operator == 'lte': query = query.filter(col <= val)
            
            elif score_type == '4':
                val = float(value_input)
                col = KetQua.diem_tong_ket_4
                if operator == 'gt': query = query.filter(col > val)
                elif operator == 'lt': query = query.filter(col < val)
                elif operator == 'eq': query = query.filter(col == val)
                elif operator == 'gte': query = query.filter(col >= val)
                elif operator == 'lte': query = query.filter(col <= val)

            elif score_type == 'char':
                # Map letters to numeric ranks for comparison
                # F=0, D=1, D+=2, C=3, C+=4, B=5, B+=6, A=7
                ranks = {'F': 0, 'D': 1, 'D+': 2, 'C': 3, 'C+': 4, 'B': 5, 'B+': 6, 'A': 7}
                input_rank = ranks.get(value_input.upper())
                
                print(f"DEBUG: value_input='{value_input}', input_rank={input_rank}, operator='{operator}'")

                if input_rank is not None:
                    # We have to fetch all and filter in Python because storing ranks in DB is not done
                    # Or we can use the 10-scale equivalent ranges.
                    # Let's use Python filtering for simplicity as dataset is small-ish.
                    # But for "Equal", we can just query.
                    if operator == 'eq':
                        query = query.filter(KetQua.diem_chu == value_input.upper())
                        results = query.all()
                    else:
                        # Fetch all for this subject and filter
                        all_rows = query.all()
                        filtered = []
                        for row in all_rows:
                            r_rank = ranks.get(row.diem_chu)
                            if r_rank is None: 
                                print(f"DEBUG: Skipping row with diem_chu='{row.diem_chu}'")
                                continue
                            
                            print(f"DEBUG: Checking row: {row.ma_sv}, diem_chu='{row.diem_chu}', r_rank={r_rank}")

                            if operator == 'gt' and r_rank > input_rank: filtered.append(row)
                            elif operator == 'lt' and r_rank < input_rank: filtered.append(row)
                            elif operator == 'gte' and r_rank >= input_rank: filtered.append(row)
                            elif operator == 'lte' and r_rank <= input_rank: filtered.append(row)
                        results = filtered
                    
                    # Skip the default query.all() below if we did python filtering
                    if operator != 'eq':
                        return render_template(
                            'admin_report_custom_query.html',
                            danh_sach_mon_hoc=danh_sach_mon_hoc,
                            results=results,
                            selected_mh_id=selected_mh_id,
                            score_type=score_type,
                            operator=operator,
                            value=value_input
                        )

            if score_type != 'char' or operator == 'eq':
                results = query.all()

        except ValueError:
            flash('Giá trị nhập vào không hợp lệ.', 'danger')

    return render_template(
        'admin_report_custom_query.html',
        danh_sach_mon_hoc=danh_sach_mon_hoc,
        results=results,
        selected_mh_id=selected_mh_id,
        score_type=score_type,
        operator=operator,
        value=value_input
    )



# 4.7. Gửi Thông báo


# 4.8. Nhập Excel Sinh viên
@app.route('/admin/import_students', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN, VaiTroEnum.ADMIN)
def admin_import_students():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Không có tệp nào được chọn.', 'danger')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('Chưa chọn tệp.', 'danger')
            return redirect(request.url)

        if file and file.filename.endswith(('.xls', '.xlsx')):
            try:

                df = pd.read_excel(file)
                
                # Mapping columns
                col_map = {
                    'MÃ SV': 'ma_sinh_vien',
                    'HỌ VÀ TÊN': 'ten_sinh_vien',
                    'NGÀY SINH': 'ngay_sinh',
                    'LỚP': 'lop',
                    'KHOA': 'khoa',
                    'EMAIL': 'email',
                    'ĐỊA CHỈ': 'location',
                    'HỆ ĐT': 'he_dao_tao',
                    'PASSWORD': 'password', # Optional
                    'ROLE': 'role' # Optional
                }

                # Check for required columns (Vietnamese or English fallback)
                # We will prioritize Vietnamese headers.
                # Required: MÃ SV, HỌ VÀ TÊN
                
                # Normalize columns to upper case for easier matching if needed, but let's stick to the map first.
                # Actually, let's try to find the columns in the df.
                
                found_map = {}
                for vn_col, internal_col in col_map.items():
                    if vn_col in df.columns:
                        found_map[internal_col] = vn_col
                    elif vn_col.lower() in df.columns: # try lowercase
                         found_map[internal_col] = vn_col.lower()
                    # Fallback to internal name if exists (backward compatibility)
                    elif internal_col in df.columns:
                        found_map[internal_col] = internal_col
                
                if 'ma_sinh_vien' not in found_map or 'ten_sinh_vien' not in found_map:
                     flash(f'Lỗi: File Excel phải chứa ít nhất các cột: MÃ SV, HỌ VÀ TÊN', 'danger')
                     return redirect(request.url)

                created_count = 0
                errors = []
                for index, row in df.iterrows():
                    # Get values using the map
                    ma_sv_col = found_map.get('ma_sinh_vien')
                    ten_sv_col = found_map.get('ten_sinh_vien')
                    
                    ma_sv = str(row[ma_sv_col]).strip()
                    ten_sv = str(row[ten_sv_col]).strip()
                    
                    # Password
                    password_col = found_map.get('password')
                    if password_col and pd.notna(row[password_col]):
                        password = str(row[password_col])
                    else:
                        password = f"{ma_sv}@123"
                    
                    # Role
                    role_col = found_map.get('role')
                    if role_col and pd.notna(row[role_col]):
                         role_str = str(row[role_col]).upper()
                    else:
                        role_str = 'SINHVIEN'

                    if role_str != 'SINHVIEN':
                        errors.append(f'Dòng {index+2}: Vai trò "{role_str}" không hợp lệ. Bỏ qua.')
                        continue
                    
                    existing_user = TaiKhoan.query.get(ma_sv)
                    if existing_user:
                        errors.append(f'Dòng {index+2}: Mã SV "{ma_sv}" đã tồn tại. Bỏ qua.')
                        continue

                    new_account = TaiKhoan(username=ma_sv, vai_tro=VaiTroEnum.SINHVIEN.value)
                    new_account.set_password(password)

                    # Optional fields
                    lop = None
                    if 'lop' in found_map and pd.notna(row[found_map['lop']]):
                        lop = str(row[found_map['lop']])
                    
                    khoa = None
                    if 'khoa' in found_map and pd.notna(row[found_map['khoa']]):
                        khoa = str(row[found_map['khoa']])
                        
                    email = None
                    if 'email' in found_map and pd.notna(row[found_map['email']]):
                        email = str(row[found_map['email']])
                        
                    location = None
                    if 'location' in found_map and pd.notna(row[found_map['location']]):
                        location = str(row[found_map['location']])
                        
                    he_dao_tao = 'CU_NHAN'
                    if 'he_dao_tao' in found_map and pd.notna(row[found_map['he_dao_tao']]):
                        val = str(row[found_map['he_dao_tao']]).upper()
                        if 'KY' in val or 'KỸ' in val: he_dao_tao = 'KY_SU'
                        
                    ngay_sinh = None
                    if 'ngay_sinh' in found_map and pd.notna(row[found_map['ngay_sinh']]):
                         try:
                             ngay_sinh = pd.to_datetime(row[found_map['ngay_sinh']])
                         except:
                             pass

                    new_student = SinhVien(
                        ma_sv=ma_sv, ho_ten=ten_sv,
                        lop = lop,
                        khoa = khoa,
                        email = email,
                        location = location,
                        he_dao_tao = he_dao_tao,
                        ngay_sinh = ngay_sinh
                    )
                    db.session.add(new_account)
                    db.session.add(new_student)
                    created_count += 1

                db.session.commit()
                flash(f'Nhập file thành công! Đã thêm mới {created_count} sinh viên.', 'success')
                for error in errors: flash(error, 'warning')

            except Exception as e:
                db.session.rollback()
                flash(f'Đã xảy ra lỗi nghiêm trọng khi đọc file: {e}', 'danger')

            return redirect(url_for('admin_manage_students'))

    return render_template('admin_import_students.html')

# 4.9. Nhập Excel Điểm
# === THAY THẾ HÀM admin_import_grades CŨ BẰNG HÀM NÀY ===
@app.route('/admin/grades/import', methods=['GET', 'POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_import_grades():
    # Lấy danh sách môn học (Lọc theo giáo viên nếu không phải Admin)
    if current_user.has_role('ADMIN'):
        danh_sach_mon_hoc = MonHoc.query.order_by(MonHoc.ten_mh).all()
    else:
        # Chỉ lấy các môn mà giáo viên được phân công
        assigned_subjects = db.session.query(MonHoc).join(PhanCong).filter(PhanCong.ma_gv == current_user.username).distinct().all()
        danh_sach_mon_hoc = sorted(assigned_subjects, key=lambda x: x.ten_mh)

    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Không có tệp nào được chọn.', 'danger')
            return redirect(request.url)
        file = request.files['file']
        selected_mh = request.form.get('ma_mh')
        if file.filename == '' or not selected_mh:
            flash('Vui lòng chọn Môn học và tệp Excel.', 'danger')
            return redirect(request.url)

        # Kiểm tra quyền (Double check cho POST request)
        if not current_user.has_role('ADMIN'):
            # Kiểm tra xem GV có được phân công dạy môn này không
            assignment = PhanCong.query.filter_by(ma_gv=current_user.username, ma_mh=selected_mh).first()
            if not assignment:
                flash('Bạn không có quyền nhập điểm cho môn học này.', 'danger')
                return redirect(request.url)

        if file and file.filename.endswith(('.xls', '.xlsx')):
            try:
                df = pd.read_excel(file)
                # Yêu cầu 6 cột: Mã SV và 5 điểm thành phần (theo tên cột tiếng Việt khi xuất file)
                # Mapping từ tên cột trong Excel (Tiếng Việt) sang biến xử lý
                col_map = {
                    'Mã SV': 'ma_sinh_vien',
                    'Điểm CC': 'diem_chuyen_can',
                    'Điểm BT': 'diem_bai_tap',
                    'Điểm KT': 'diem_kiem_tra',
                    'Điểm TH': 'diem_thuc_hanh',
                    'Điểm Thi': 'diem_thi'
                }
                
                # Kiểm tra xem file có đủ các cột bắt buộc không
                missing_cols = [col for col in col_map.keys() if col not in df.columns]
                
                # Fallback: Nếu không tìm thấy cột tiếng Việt, thử tìm cột tiếng Anh cũ (để tương thích ngược nếu cần)
                if missing_cols:
                     # Nếu thiếu cột tiếng Việt, thử check cột tiếng Anh
                     english_cols = ['ma_sinh_vien', 'diem_chuyen_can', 'diem_bai_tap', 'diem_kiem_tra', 'diem_thuc_hanh', 'diem_thi']
                     if all(col in df.columns for col in english_cols):
                         # Nếu có đủ cột tiếng Anh, dùng mapping tiếng Anh
                         col_map = {col: col for col in english_cols}
                     else:
                         # Nếu thiếu cả 2, báo lỗi theo tên cột Tiếng Việt cho thân thiện
                         flash(f'Lỗi: File Excel thiếu các cột bắt buộc: {", ".join(missing_cols)}', 'danger')
                         return redirect(request.url)

                updated_count = 0
                created_count = 0
                errors = []
                skipped_count = 0
                
                # Lấy danh sách lớp được phân công cho môn này (nếu là GV) để kiểm tra từng SV
                allowed_classes = []
                if not current_user.has_role('ADMIN'):
                    assignments = PhanCong.query.filter_by(ma_gv=current_user.username, ma_mh=selected_mh).all()
                    allowed_classes = [a.lop for a in assignments]

                for index, row in df.iterrows():
                    # Lấy mã SV từ cột tương ứng trong map
                    col_ma_sv = [k for k, v in col_map.items() if v == 'ma_sinh_vien'][0]
                    ma_sv = str(row[col_ma_sv]).strip() if pd.notna(row[col_ma_sv]) else None
                    
                    if not ma_sv: skipped_count += 1; continue

                    # Kiểm tra xem SV có thuộc lớp mình dạy không (nếu là GV)
                    if not current_user.has_role('ADMIN'):
                        sv = SinhVien.query.get(ma_sv)
                        if not sv or sv.lop not in allowed_classes:
                            errors.append(f"Dòng {index+2}: Bạn không được phân công dạy SV '{ma_sv}' (Lớp {sv.lop if sv else 'Unknown'}). Bỏ qua.")
                            continue

                    # Lấy và validate từng điểm thành phần
                    diem_cc, diem_bt, diem_kt, diem_th, diem_thi = None, None, None, None, None
                    valid_scores = True
                    
                    # Mapping biến nội bộ -> tên biến đích
                    score_vars = {
                        'diem_chuyen_can': 'diem_cc',
                        'diem_bai_tap': 'diem_bt',
                        'diem_kiem_tra': 'diem_kt',
                        'diem_thuc_hanh': 'diem_th',
                        'diem_thi': 'diem_thi'
                    }

                    for excel_col, internal_col in col_map.items():
                        if internal_col == 'ma_sinh_vien': continue # Bỏ qua mã SV
                        
                        score_var_name = score_vars.get(internal_col)
                        score_val = row.get(excel_col, None)
                        
                        temp_score = None
                        if pd.notna(score_val): # Chỉ xử lý nếu ô không trống
                            try:
                                temp_score = float(score_val)
                                if not (0 <= temp_score <= 10):
                                    raise ValueError("Điểm không hợp lệ")
                                # Gán giá trị hợp lệ
                                if score_var_name == 'diem_cc': diem_cc = temp_score
                                elif score_var_name == 'diem_bt': diem_bt = temp_score
                                elif score_var_name == 'diem_kt': diem_kt = temp_score
                                elif score_var_name == 'diem_th': diem_th = temp_score
                                elif score_var_name == 'diem_thi': diem_thi = temp_score
                            except (ValueError, TypeError):
                                errors.append(f"Dòng {index+2}: Điểm '{excel_col}' ('{score_val}') của SV '{ma_sv}' không hợp lệ. Bản ghi này có thể không được tính điểm tổng kết.")
                                valid_scores = False 
                        # else: # Giữ None nếu ô trống

                    student_exists = SinhVien.query.get(ma_sv)
                    if not student_exists:
                        errors.append(f"Dòng {index+2}: Mã SV '{ma_sv}' không tồn tại. Bỏ qua.")
                        continue

                    existing_grade = KetQua.query.get((ma_sv, selected_mh))
                    if existing_grade:
                         # Chỉ update nếu có điểm mới từ file và khác điểm cũ
                         changed = False
                         if diem_cc is not None and existing_grade.diem_chuyen_can != diem_cc:
                              existing_grade.diem_chuyen_can = diem_cc; changed=True
                         if diem_bt is not None and existing_grade.diem_bai_tap != diem_bt:
                              existing_grade.diem_bai_tap = diem_bt; changed=True
                         if diem_kt is not None and existing_grade.diem_kiem_tra != diem_kt:
                              existing_grade.diem_kiem_tra = diem_kt; changed=True
                         if diem_th is not None and existing_grade.diem_thuc_hanh != diem_th:
                              existing_grade.diem_thuc_hanh = diem_th; changed=True
                         if diem_thi is not None and existing_grade.diem_thi != diem_thi:
                              existing_grade.diem_thi = diem_thi; changed=True

                         if changed:
                              existing_grade.calculate_final_score() # Tính lại điểm TK
                              updated_count += 1
                    else:
                        new_grade = KetQua(ma_sv=ma_sv, ma_mh=selected_mh,
                                           diem_chuyen_can=diem_cc,
                                           diem_bai_tap=diem_bt,
                                           diem_kiem_tra=diem_kt,
                                           diem_thuc_hanh=diem_th,
                                           diem_thi=diem_thi)
                        new_grade.calculate_final_score() # Tính điểm TK
                        db.session.add(new_grade)
                        created_count += 1

                if updated_count > 0 or created_count > 0:
                     db.session.commit()
                     flash(f'Nhập điểm từ Excel thành công! (Thêm mới: {created_count}, Cập nhật: {updated_count}, Bỏ qua: {skipped_count})', 'success')
                else:
                     flash('Không có điểm mới hoặc thay đổi nào được nhập.', 'info')

                for error in errors: flash(error, 'warning')

            except Exception as e:
                db.session.rollback()
                flash(f'Đã xảy ra lỗi nghiêm trọng khi đọc hoặc xử lý file: {e}', 'danger')

            return redirect(url_for('admin_manage_grades'))
        else:
             flash('Lỗi: Định dạng file không được hỗ trợ. Chỉ chấp nhận .xls hoặc .xlsx', 'danger')
             return redirect(request.url)

    return render_template('admin_import_grades.html', danh_sach_mon_hoc=danh_sach_mon_hoc)

# 4.10. Xuất Excel Điểm theo Lớp
# === THAY THẾ HÀM admin_export_grades CŨ BẰNG HÀM NÀY ===
@app.route('/admin/export_grades', methods=['GET'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_export_grades():
    """Trang hiển thị dropdown để chọn Lớp VÀ Môn học."""
    # Lấy danh sách lớp
    if current_user.has_role('ADMIN'):
        lop_hoc_tuples = db.session.query(SinhVien.lop).distinct().order_by(SinhVien.lop).all()
        danh_sach_lop = [lop[0] for lop in lop_hoc_tuples if lop[0]]
        # Lấy danh sách môn học
        danh_sach_mon_hoc = MonHoc.query.order_by(MonHoc.ten_mh).all()
    else:
        # Chỉ lấy các lớp và môn mà giáo viên được phân công
        assigned_classes = db.session.query(PhanCong.lop).filter(PhanCong.ma_gv == current_user.username).distinct().all()
        danh_sach_lop = sorted([lop[0] for lop in assigned_classes if lop[0]])
        
        assigned_subjects = db.session.query(MonHoc).join(PhanCong).filter(PhanCong.ma_gv == current_user.username).distinct().all()
        danh_sach_mon_hoc = sorted(assigned_subjects, key=lambda x: x.ten_mh)

    return render_template(
        'admin_export_grades.html',
        danh_sach_lop=danh_sach_lop,
        danh_sach_mon_hoc=danh_sach_mon_hoc # Gửi thêm danh sách môn học
    )
# ========================================================

# === THAY THẾ HÀM admin_perform_export CŨ BẰNG HÀM NÀY ===
@app.route('/admin/export/perform', methods=['POST'])
@login_required
@role_required(VaiTroEnum.GIAOVIEN)
def admin_perform_export():
    """Xử lý logic và trả về file Excel điểm DẠNG DÀI (đã lọc)."""
    try:
        # Lấy giá trị từ form
        selected_lop = request.form.get('lop')
        selected_mh_id = request.form.get('ma_mh')

        # Kiểm tra quyền (Nếu là GV)
        if not current_user.has_role('ADMIN'):
            # Nếu chọn "Tất cả lớp", phải đảm bảo GV dạy môn đó cho ÍT NHẤT 1 lớp (hoặc logic chặt hơn là chỉ export các lớp được dạy)
            # Nếu chọn "Tất cả môn", phải đảm bảo GV dạy lớp đó
            
            # Đơn giản hóa: Nếu là GV, ta sẽ filter query trực tiếp theo PhanCong
            pass # Logic filter sẽ được thêm vào query bên dưới

        # Bắt đầu truy vấn cơ sở
        query = db.session.query(
            SinhVien.ma_sv,
            SinhVien.ho_ten,
            SinhVien.lop,
            MonHoc.ma_mh,
            MonHoc.ten_mh,
            MonHoc.so_tin_chi,
            KetQua.diem_chuyen_can,
            KetQua.diem_bai_tap,
            KetQua.diem_kiem_tra,
            KetQua.diem_thuc_hanh,
            KetQua.diem_thi,
            KetQua.diem_tong_ket,
            KetQua.diem_chu
        ).select_from(SinhVien).join( # Bắt đầu từ SinhVien
            KetQua, SinhVien.ma_sv == KetQua.ma_sv, isouter=True # LEFT JOIN KetQua
        ).join(
             MonHoc, KetQua.ma_mh == MonHoc.ma_mh, isouter=True # LEFT JOIN MonHoc
        )

        # Nếu là GV, chỉ cho phép xem dữ liệu thuộc PhanCong của mình
        if not current_user.has_role('ADMIN'):
            # Join với PhanCong để lọc
            # Logic: SinhVien.lop VÀ MonHoc.ma_mh phải tồn tại trong bảng PhanCong với ma_gv = current_user
            # Tuy nhiên, query hiện tại join KetQua (ma_mh) và SinhVien (lop).
            # Ta cần đảm bảo cặp (SinhVien.lop, KetQua.ma_mh) nằm trong PhanCong của GV.
            # Lưu ý: Nếu KetQua.ma_mh là NULL (SV chưa có điểm), ta vẫn cần check xem GV có dạy lớp đó môn nào không?
            # Thực ra export điểm thì thường quan tâm môn học.
            
            # Cách tiếp cận: Lọc theo danh sách (Lớp, Môn) mà GV được phân công
            # Subquery hoặc Filter IN
            
            # Lấy danh sách (lop, ma_mh) mà GV dạy
            assignments = db.session.query(PhanCong.lop, PhanCong.ma_mh).filter(PhanCong.ma_gv == current_user.username).all()
            
            # Nếu không có phân công nào, trả về rỗng
            if not assignments:
                 flash(f'Bạn chưa được phân công giảng dạy lớp/môn nào.', 'warning')
                 return redirect(url_for('admin_export_grades'))

            # Xây dựng điều kiện lọc: OR (lop == L1 AND ma_mh == M1) OR (lop == L2 AND ma_mh == M2)...
            # Điều này hơi phức tạp với SQLAlchemy thuần túy nếu danh sách lớn.
            # Cách khác: Join trực tiếp với PhanCong trong query chính
            
            query = query.join(
                PhanCong, 
                and_(
                    PhanCong.lop == SinhVien.lop,
                    PhanCong.ma_mh == MonHoc.ma_mh, # Lưu ý: MonHoc ở đây là từ KetQua join sang
                    PhanCong.ma_gv == current_user.username
                )
            )
            # Lưu ý: MonHoc join ở trên là `isouter=True`. Nếu SV chưa có điểm môn nào, MonHoc.ma_mh sẽ NULL -> PhanCong join sẽ fail -> Dòng đó bị loại.
            # Điều này ĐÚNG với mục đích "Xuất bảng điểm". Chỉ xuất những gì liên quan đến môn mình dạy.
            # Nhưng nếu muốn xuất danh sách SV của lớp mình dạy (kể cả chưa có điểm)?
            # Form export này tập trung vào "Bảng điểm", nên việc join chặt chẽ là hợp lý.


        # Xây dựng tên file
        file_lop_name = "ALL"
        file_mh_name = "ALL"

        # 1. Áp dụng bộ lọc Lớp (nếu người dùng chọn 1 lớp cụ thể)
        if selected_lop and selected_lop != 'all':
            query = query.filter(SinhVien.lop == selected_lop)
            file_lop_name = selected_lop.replace(" ", "_")

        # 2. Áp dụng bộ lọc Môn học (nếu người dùng chọn 1 môn cụ thể)
        if selected_mh_id and selected_mh_id != 'all':
            query = query.filter(KetQua.ma_mh == selected_mh_id)
            file_mh_name = selected_mh_id.replace(" ", "_")
        
        # 3. Chỉ lấy những SV có bản ghi điểm (nếu lọc theo môn hoặc cả 2)
        #    Nếu chỉ lọc theo lớp, ta vẫn muốn lấy cả SV chưa có điểm
        if selected_mh_id and selected_mh_id != 'all':
             query = query.filter(KetQua.ma_sv != None) # Đảm bảo có kết quả

        # Sắp xếp kết quả
        query_results = query.order_by(SinhVien.lop, SinhVien.ma_sv, MonHoc.ma_mh).all()

        if not query_results:
            flash(f'Không tìm thấy dữ liệu điểm nào cho lựa chọn của bạn.', 'warning')
            return redirect(url_for('admin_export_grades'))

        # 4. Chuẩn bị dữ liệu cho DataFrame
        data_for_df = []
        for row in query_results:
             # Bỏ qua nếu là SV trong lớp nhưng chưa có điểm môn nào (chỉ xảy ra khi lọc theo lớp)
            if row.ma_mh is None: 
                continue
                
            data_for_df.append({
                'Mã SV': row.ma_sv,
                'Họ tên': row.ho_ten,
                'Lớp': row.lop,
                'Mã MH': row.ma_mh,
                'Tên Môn học': row.ten_mh,
                'Số TC': row.so_tin_chi,
                'Điểm CC': row.diem_chuyen_can,
                'Điểm BT': row.diem_bai_tap,
                'Điểm KT': row.diem_kiem_tra,
                'Điểm TH': row.diem_thuc_hanh,
                'Điểm Thi': row.diem_thi,
                'Điểm TK (10)': row.diem_tong_ket,
                'Điểm Chữ': row.diem_chu
            })
        
        if not data_for_df:
            flash(f'Không có dữ liệu điểm cụ thể nào được tìm thấy (có thể sinh viên trong lớp chưa học môn nào).', 'warning')
            return redirect(url_for('admin_export_grades'))

        df = pd.DataFrame(data_for_df)

        # 5. Tạo file Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name=f'Diem_{file_lop_name}', index=False)
        output.seek(0)

        # 6. Trả file về cho người dùng
        download_name = f'BangDiem_Lop_{file_lop_name}_Mon_{file_mh_name}.xlsx'
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=download_name
        )

    except Exception as e:
        flash(f'Đã xảy ra lỗi khi xuất file điểm: {e}', 'danger')
        return redirect(url_for('admin_export_grades'))
# =======================================================

# 4.11. Xuất Excel Danh sách Sinh viên
@app.route('/admin/export_students_excel')
@login_required
@role_required(VaiTroEnum.GIAOVIEN, VaiTroEnum.ADMIN)
def admin_export_students_excel():
    try:
        search_ma_sv = request.args.get('ma_sv', '')
        search_ho_ten = request.args.get('ho_ten', '')
        filter_lop = request.args.get('lop', '')
        filter_khoa = request.args.get('khoa', '')

        query = SinhVien.query
        if search_ma_sv: query = query.filter(SinhVien.ma_sv.ilike(f'%{search_ma_sv}%'))
        if search_ho_ten: query = query.filter(SinhVien.ho_ten.ilike(f'%{search_ho_ten}%'))
        if filter_lop: query = query.filter(SinhVien.lop == filter_lop)
        if filter_khoa: query = query.filter(SinhVien.khoa == filter_khoa)

        students = query.order_by(SinhVien.ma_sv).all()
        if not students:
            flash('Không có dữ liệu sinh viên nào để xuất.', 'warning')
            return redirect(url_for('admin_manage_students'))

        data_for_df = [{'MÃ SV': sv.ma_sv, 'HỌ VÀ TÊN': sv.ho_ten, 'NGÀY SINH': sv.ngay_sinh,
                        'LỚP': sv.lop, 'KHOA': sv.khoa, 'EMAIL': sv.email,
                        'ĐỊA CHỈ': sv.location, 'HỆ ĐT': sv.he_dao_tao} for sv in students]
        df = pd.DataFrame(data_for_df)
        if 'NGÀY SINH' in df.columns:
            # Sửa lỗi: Thêm errors='coerce' để xử lý ngày không hợp lệ thành NaT
            df['NGÀY SINH'] = pd.to_datetime(df['NGÀY SINH'], errors='coerce').dt.strftime('%d-%m-%Y')
            # Thay NaT thành chuỗi rỗng
            df['NGÀY SINH'] = df['NGÀY SINH'].fillna('')


        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='DanhSachSinhVien', index=False)
        output.seek(0)

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='DanhSachSinhVien_Filtered.xlsx'
        )
    except Exception as e:
        flash(f'Đã xảy ra lỗi khi xuất file: {e}', 'danger')
        return redirect(url_for('admin_manage_students'))




# --- 5. KHỞI CHẠY ỨNG DỤNG ---
if __name__ == '__main__':
    with app.app_context():
        # Tạo tất cả các bảng nếu chưa tồn tại
        db.create_all()
        ensure_teacher_profile_columns()
        
        # === CẬP NHẬT LOGIC TẠO TÀI KHOẢN MẪU ===
        if not TaiKhoan.query.filter_by(username='giaovien01').first():
            print("Tạo tài khoản giáo viên mẫu...")
            # 1. Tạo tài khoản
            admin_user = TaiKhoan(
                username='giaovien01',
                vai_tro=VaiTroEnum.GIAOVIEN
            )
            admin_user.set_password('admin@123') # Mật khẩu ví dụ
            db.session.add(admin_user)
            
            # 2. Tạo hồ sơ giáo viên (MỚI)
            default_teacher_profile = GiaoVien(
                ma_gv='giaovien01',
                ho_ten='Giáo vụ (Mặc định)',
                email='giaovien01@ptit.edu.vn', # Email mẫu
                khoa_bo_mon='Phòng Giáo vụ'
            )
            db.session.add(default_teacher_profile)
            
            # 3. Lưu cả hai
            db.session.commit()
            print("Tạo xong. Username: giaovien01, Password: admin@123")
    # Tắt debug khi deploy thực tế
    # Bật debug=True để xem lỗi và để server tự khởi động lại khi sửa code
    app.run(host='0.0.0.0', port=5000, debug=True)
