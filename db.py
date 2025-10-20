import sqlite3
from config import DB_FILE

def init_db():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS groups (
            link TEXT,
            profile_id INTEGER,
            PRIMARY KEY (link, profile_id)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_id INTEGER,
            api_hash TEXT,
            phone TEXT,
            session_name TEXT
        )''')
        defaults = [
            ("messages_per_minute", "30"),
            ("send_interval", "60"),
            ("message_text", "📢 Bu avtomatik xabar!"),
            ("auto_reply_text", "Salom! Bu avtomatik javob."),
            ("auto_reply_enabled", "1"),
            ("response_reply_text", "Avto javob guruhda."),
            ("response_reply_enabled", "0"),
            ("auto_send_enabled", "0")
        ]
        c.executemany("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", defaults)
        conn.commit()
    except Exception as e:
        print(f"[Xato] Ma'lumotlar bazasi yaratishda: {e}")
    finally:
        conn.close()

def get_setting(key):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = ?", (key,))
        result = c.fetchone()
        return result[0] if result else None
    finally:
        conn.close()

def set_setting(key, value):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
    finally:
        conn.close()

def load_groups(profile_id=None):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        if profile_id is None:
            c.execute("SELECT link FROM groups")
        else:
            c.execute("SELECT link FROM groups WHERE profile_id = ?", (profile_id,))
        groups = [row[0] for row in c.fetchall()]
        return groups
    finally:
        conn.close()

def save_group(link, profile_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO groups (link, profile_id) VALUES (?, ?)", (link, profile_id))
        conn.commit()
    finally:
        conn.close()

def remove_group(link, profile_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM groups WHERE link = ? AND profile_id = ?", (link, profile_id))
        conn.commit()
    finally:
        conn.close()

def load_profiles():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT id, api_id, api_hash, phone, session_name FROM profiles")
        profs = [{'id': row[0], 'api_id': row[1], 'api_hash': row[2], 'phone': row[3], 'session_name': row[4]} for row in c.fetchall()]
        return profs
    except sqlite3.OperationalError as e:
        print(f"[Xato] Profilarni yuklashda: {e}")
        return []
    finally:
        conn.close()

def save_profile(api_id, api_hash, phone, session_name):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO profiles (api_id, api_hash, phone, session_name) VALUES (?, ?, ?, ?)",
                  (api_id, api_hash, phone, session_name))
        profile_id = c.lastrowid
        conn.commit()
        return profile_id
    finally:
        conn.close()

def remove_profile(profile_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        c.execute("DELETE FROM groups WHERE profile_id = ?", (profile_id,))
        conn.commit()
    finally:
        conn.close()