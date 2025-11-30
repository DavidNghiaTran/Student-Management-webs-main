import sqlite3
import os

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'qlsv.db'))

def verify():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("PRAGMA table_info(ket_qua)")
        columns = cursor.fetchall()
        print("Columns in 'ket_qua' table:")
        for col in columns:
            print(f"- {col[1]} ({col[2]})")
            
    except Exception as e:
        print(f"Verification failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    verify()
