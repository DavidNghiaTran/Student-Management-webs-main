from api.index import app, db, TaiKhoan, VaiTroEnum, bcrypt
from sqlalchemy import text

with app.app_context():
    # Check if admin exists
    admin = TaiKhoan.query.filter_by(username='admin').first()
    if not admin:
        hashed_password = bcrypt.generate_password_hash('admin123').decode('utf-8')
        
        # Use raw SQL to bypass Enum check if necessary (SQLite doesn't enforce Enums strictly usually, but SQLAlchemy does)
        # However, if the column is defined as Enum in SQLAlchemy, it tries to convert.
        # Let's try raw SQL insertion.
        sql = text("INSERT INTO tai_khoan (username, password, vai_tro) VALUES (:u, :p, :r)")
        db.session.execute(sql, {'u': 'admin', 'p': hashed_password, 'r': 'ADMIN'})
        db.session.commit()
        
        print("Admin account created successfully.")
        print("Username: admin")
        print("Password: admin123")
    else:
        print("Admin account already exists.")
        if admin.vai_tro != VaiTroEnum.ADMIN:
            # Update role using raw SQL
            sql = text("UPDATE tai_khoan SET vai_tro = :r WHERE username = :u")
            db.session.execute(sql, {'r': 'ADMIN', 'u': 'admin'})
            db.session.commit()
            print("Updated existing 'admin' user to ADMIN role.")
