from api.index import app, db, TaiKhoan

with app.app_context():
    users = TaiKhoan.query.all()
    for u in users:
        print(f"User: {u.username}, Role: {u.vai_tro}")
