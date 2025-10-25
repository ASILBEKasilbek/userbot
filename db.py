import sqlite3
import logging
import threading

_db_lock = threading.Lock() 
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DB_NAME = 'userbot_settings.db'

def get_connection():
    # 🔧 Muhim o‘zgarish: timeout va check_same_thread qo‘shildi
    return sqlite3.connect(DB_NAME, timeout=10, check_same_thread=False)

def init_db():
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_id INTEGER,
            api_hash TEXT,
            phone TEXT,
            session_name TEXT,
            auto_reply_enabled INTEGER DEFAULT 0,
            auto_reply_text TEXT DEFAULT 'Salom! Bu avtomatik javob.',
            response_reply_enabled INTEGER DEFAULT 0,
            response_reply_text TEXT DEFAULT 'Avto javob guruhda.',
            message_text TEXT DEFAULT '📢 Bu avtomatik xabar!',
            auto_send_enabled INTEGER DEFAULT 0,
            messages_per_minute INTEGER DEFAULT 30,
            send_interval INTEGER DEFAULT 60
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link TEXT,
            profile_id INTEGER,
            FOREIGN KEY (profile_id) REFERENCES profiles(id)
        )''')
        conn.commit()
        logger.info("Ma'lumotlar bazasi muvaffaqiyatli yaratildi.")
    except Exception as e:
        logger.error(f"Ma'lumotlar bazasi yaratishda xato: {e}")
    finally:
        conn.close()

def save_profile(api_id, api_hash, phone, session_name):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("INSERT INTO profiles (api_id, api_hash, phone, session_name) VALUES (?, ?, ?, ?)",
                  (api_id, api_hash, phone, session_name))
        conn.commit()
        profile_id = c.lastrowid
        logger.info(f"Profil saqlandi: {phone}, ID: {profile_id}")
        return profile_id
    except Exception as e:
        logger.error(f"Profil saqlashda xato: {e}")
        return None
    finally:
        conn.close()

def remove_profile(profile_id):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        c.execute("DELETE FROM groups WHERE profile_id = ?", (profile_id,))
        conn.commit()
        logger.info(f"Profil o‘chirildi: ID {profile_id}")
    except Exception as e:
        logger.error(f"Profil o‘chirishda xato: {e}")
    finally:
        conn.close()

def load_profiles():
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT id, api_id, api_hash, phone, session_name, auto_reply_enabled, auto_reply_text, response_reply_enabled, response_reply_text, message_text, auto_send_enabled, messages_per_minute, send_interval FROM profiles")
        profiles = [{'id': row[0], 'api_id': row[1], 'api_hash': row[2], 'phone': row[3], 'session_name': row[4], 
                     'auto_reply_enabled': row[5], 'auto_reply_text': row[6], 'response_reply_enabled': row[7], 
                     'response_reply_text': row[8], 'message_text': row[9], 'auto_send_enabled': row[10], 
                     'messages_per_minute': row[11], 'send_interval': row[12]} for row in c.fetchall()]
        return profiles
    except Exception as e:
        logger.error(f"Profillarni yuklashda xato: {e}")
        return []
    finally:
        conn.close()

def save_group(link, profile_id):
    try:
        with _db_lock:   # <-- lock ichida bajariladi
            conn = get_connection()
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO groups (link, profile_id) VALUES (?, ?)", (link, profile_id))
            conn.commit()
            logger.info(f"Guruh saqlandi: {link}, Profil ID: {profile_id}")
            
    except Exception as e:
        logger.error(f"Guruh saqlashda xato: {e}")
    finally:
        conn.close()

def remove_duplicate_groups():
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('''
            DELETE FROM groups
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM groups
                GROUP BY link, profile_id
            )
        ''')
        deleted = conn.total_changes
        conn.commit()
        logger.info(f"🧹 Dublikat guruhlar o‘chirildi: {deleted} ta yozuv.")
    except Exception as e:
        logger.error(f"Dublikatlarni o‘chirishda xato: {e}")
    finally:
        conn.close()

def remove_group(link, profile_id):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM groups WHERE link = ? AND profile_id = ?", (link, profile_id))
        conn.commit()
        logger.info(f"Guruh o‘chirildi: {link}, Profil ID: {profile_id}")
    except Exception as e:
        logger.error(f"Guruh o‘chirishda xato: {e}")
    finally:
        conn.close()

def load_groups(profile_id):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT link FROM groups WHERE profile_id = ?", (profile_id,))
        groups = [row[0] for row in c.fetchall()]
        return groups
    except Exception as e:
        logger.error(f"Guruhlarni yuklashda xato: {e}")
        return []
    finally:
        conn.close()

def update_profile_setting(profile_id, key, value):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(f"UPDATE profiles SET {key} = ? WHERE id = ?", (value, profile_id))
        conn.commit()
        logger.info(f"Profil sozlamasi yangilandi: ID {profile_id}, {key} = {value}")
    except Exception as e:
        logger.error(f"Profil sozlamasini yangilashda xato: {e}")
    finally:
        conn.close()

def get_profile_setting(profile_id, key):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(f"SELECT {key} FROM profiles WHERE id = ?", (profile_id,))
        result = c.fetchone()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"Profil sozlamasini olishda xato: {e}")
        return None
    finally:
        conn.close()
