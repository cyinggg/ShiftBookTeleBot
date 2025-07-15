# db_setup.py
import sqlite3

# Connect to SQLite DB (creates the file if not exists)
conn = sqlite3.connect("shiftbooktelebot.db")
c = conn.cursor()

# -------------------------------------------
# ✅ Create table: students
# Contains login + shift restriction info
# -------------------------------------------
c.execute('''
CREATE TABLE IF NOT EXISTS students (
    student_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    is_restricted INTEGER NOT NULL DEFAULT 0
)
''')

# -------------------------------------------
# ✅ Create table: bookings
# Stores confirmed shift bookings
# -------------------------------------------
c.execute('''
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    shift_date TEXT NOT NULL,
    shift_type TEXT NOT NULL,
    booked_at TEXT NOT NULL,
    FOREIGN KEY (student_id) REFERENCES students(student_id)
)
''')

# Optional: legacy or future-proof table to track generic reservations
# Not used currently in your `main.py` but kept in case you add `/reserve` logic
c.execute('''
CREATE TABLE IF NOT EXISTS reservations (
    user_id INTEGER PRIMARY KEY,
    reservation_time TEXT
)
''')

# -------------------------------------------
# ✅ Insert sample student data (safe with IGNORE)
# Only inserts if not already present
# -------------------------------------------
students = [
    ('7654321', 'CONG', 0),  # Normal user (no night shift)
    ('1234567', 'YING', 1), 
    ('2401236', 'MUHAMMED IRFAN BIN SHAFARUDIN', 1), 
    ('2401554', 'RYAN TAN YONG SOON', 1),  
    ('2402043', 'VIC GERSUN MONTANO PAMPLONA', 1),
    ('2402492', 'JESSICA CHOY ING CHOY', 1)
]

c.executemany("INSERT OR IGNORE INTO students (student_id, name, is_restricted) VALUES (?, ?, ?)", students)

# Finalize setup
conn.commit()
conn.close()

print("✅ SQLite database initialized successfully and ready.")
