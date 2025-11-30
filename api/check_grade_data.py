import sqlite3
import os

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'qlsv.db'))

def check_data():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Check count of non-null values
        cursor.execute("SELECT COUNT(diem_cuoi_ky), COUNT(diem_thi) FROM ket_qua")
        counts = cursor.fetchone()
        print(f"Non-null diem_cuoi_ky: {counts[0]}")
        print(f"Non-null diem_thi: {counts[1]}")

        # Check if there are cases where diem_cuoi_ky has data but diem_thi is null
        cursor.execute("SELECT COUNT(*) FROM ket_qua WHERE diem_cuoi_ky IS NOT NULL AND diem_thi IS NULL")
        conflict_count = cursor.fetchone()[0]
        print(f"Rows with diem_cuoi_ky but no diem_thi: {conflict_count}")

    except Exception as e:
        print(f"Check failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    check_data()
