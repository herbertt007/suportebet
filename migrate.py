import sqlite3

conn = sqlite3.connect('bets.db')
c = conn.cursor()

try:
    c.execute('ALTER TABLE users ADD COLUMN password TEXT DEFAULT ""')
    conn.commit()
    print("Column added.")
except sqlite3.OperationalError as e:
    print(f"Error: {e}")

conn.close()
