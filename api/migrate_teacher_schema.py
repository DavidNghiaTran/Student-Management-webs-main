import sqlite3
import os

# Path to the database
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'qlsv.db'))

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        print("Starting migration...")
        
        # 1. Create new table with desired schema
        print("Creating new table 'giao_vien_new'...")
        cursor.execute("""
            CREATE TABLE giao_vien_new (
                ma_gv VARCHAR(50) NOT NULL, 
                ho_ten VARCHAR(100) NOT NULL DEFAULT 'Giáo viên', 
                so_dien_thoai VARCHAR(20), 
                email VARCHAR(150), 
                van_phong VARCHAR(120), 
                avatar_url VARCHAR(255), 
                khoa_bo_mon VARCHAR(120), 
                hoc_vi VARCHAR(100), 
                linh_vuc TEXT, 
                PRIMARY KEY (ma_gv), 
                FOREIGN KEY(ma_gv) REFERENCES tai_khoan (username) ON DELETE CASCADE, 
                UNIQUE (email)
            )
        """)

        # 2. Copy data from old table to new table
        # Note: We only select the columns that exist in the old table and map them to the new one.
        # We need to handle cases where columns might be missing if the DB was already partially updated (unlikely but good to be safe)
        # But here we assume the old table has the columns we want to keep.
        print("Copying data...")
        cursor.execute("""
            INSERT INTO giao_vien_new (ma_gv, ho_ten, so_dien_thoai, email, van_phong, avatar_url, khoa_bo_mon, hoc_vi, linh_vuc)
            SELECT ma_gv, ho_ten, so_dien_thoai, email, van_phong, avatar_url, khoa_bo_mon, hoc_vi, linh_vuc
            FROM giao_vien
        """)

        # 3. Drop old table
        print("Dropping old table 'giao_vien'...")
        cursor.execute("DROP TABLE giao_vien")

        # 4. Rename new table
        print("Renaming 'giao_vien_new' to 'giao_vien'...")
        cursor.execute("ALTER TABLE giao_vien_new RENAME TO giao_vien")

        conn.commit()
        print("Migration completed successfully.")

    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
