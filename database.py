import sqlite3
import os

DATABASE = 'bets.db'
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    import psycopg2
    from psycopg2.extras import DictCursor

class DBCursorWrapper:
    def __init__(self, cursor, is_postgres=False):
        self.cursor = cursor
        self.is_postgres = is_postgres
        
    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None:
            return None
        if self.is_postgres:
            return dict(row)
        return row
        
    def fetchall(self):
        rows = self.cursor.fetchall()
        if self.is_postgres:
            return [dict(r) for r in rows]
        return rows

    @property
    def lastrowid(self):
        return self.cursor.lastrowid

class DBConnectionWrapper:
    def __init__(self, conn, is_postgres=False):
        self.conn = conn
        self.is_postgres = is_postgres
        
    def execute(self, query, params=None):
        if self.is_postgres:
            query = query.replace('?', '%s')
            query = query.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
            cursor = self.conn.cursor(cursor_factory=DictCursor)
        else:
            cursor = self.conn.cursor()
            
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        return DBCursorWrapper(cursor, self.is_postgres)
        
    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()
        
    def close(self):
        self.conn.close()

def get_db():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL)
        return DBConnectionWrapper(conn, is_postgres=True)
    else:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        return DBConnectionWrapper(conn, is_postgres=False)

def init_db():
    conn = get_db()
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL DEFAULT '',
            points INTEGER DEFAULT 0,
            correct_bets INTEGER DEFAULT 0,
            profile_photo TEXT
        )
    ''')

    if conn.is_postgres:
        columns = conn.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'users'
        """).fetchall()
        column_names = {row['column_name'] for row in columns}
    else:
        columns = conn.execute('PRAGMA table_info(users)').fetchall()
        column_names = {row['name'] for row in columns}

    if 'profile_photo' not in column_names:
        conn.execute('ALTER TABLE users ADD COLUMN profile_photo TEXT')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_a TEXT NOT NULL,
            team_b TEXT NOT NULL,
            date TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            winner TEXT,
            shots_total INTEGER,
            goals_total INTEGER,
            team_a_goals INTEGER,
            team_b_goals INTEGER,
            cards_total INTEGER,
            finishes_total INTEGER,
            api_id INTEGER,
            team_a_crest TEXT,
            team_b_crest TEXT
        )
    ''')

    if conn.is_postgres:
        columns = conn.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'games'
        """).fetchall()
        game_column_names = {row['column_name'] for row in columns}
    else:
        columns = conn.execute('PRAGMA table_info(games)').fetchall()
        game_column_names = {row['name'] for row in columns}

    if 'team_a_goals' not in game_column_names:
        conn.execute('ALTER TABLE games ADD COLUMN team_a_goals INTEGER')
    if 'team_b_goals' not in game_column_names:
        conn.execute('ALTER TABLE games ADD COLUMN team_b_goals INTEGER')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            game_id INTEGER,
            bet_type TEXT NOT NULL, 
            prediction TEXT NOT NULL,
            status TEXT DEFAULT 'pending', 
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(game_id) REFERENCES games(id)
        )
    ''')
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Banco de dados inicializado.")
