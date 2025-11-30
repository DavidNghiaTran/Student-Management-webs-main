from api.index import app, db, TaiKhoan

with app.app_context():
    user = TaiKhoan.query.filter_by(username='admin').first()
    if user:
        print(f"User: {user.username}")
        print(f"Role: {user.vai_tro}")
        print(f"Role Type: {type(user.vai_tro)}")
        if hasattr(user.vai_tro, 'value'):
            print(f"Role Value: {user.vai_tro.value}")
    else:
        print("User 'admin' not found")
