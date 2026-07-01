import database
import os

db_path = 'bets.db'
if os.path.exists(db_path):
    os.remove(db_path)

database.init_db()
conn = database.get_db()
conn.execute("INSERT INTO users (username, password, is_admin) VALUES ('herbert', '123', 1)")
conn.commit()
conn.close()
print("Database reset and herbert user created.")
