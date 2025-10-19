import asyncio
import os
import sqlite3
from typing import List
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from telethon import TelegramClient, events
from telethon.errors import ChatWriteForbiddenError, ChannelPrivateError, FloodWaitError, SessionPasswordNeededError
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest, GetFullChannelRequest
from telethon.tl.types import Channel
from telethon.tl.functions.auth import SendCodeRequest
from dotenv import load_dotenv

# ==================== CONFIG ==================== #
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")  # .env faylida ADMIN_ID qo‘shilishi kerak

DB_FILE = "userbot_settings.db"

# ==================== FSM STATES ==================== #
class SettingsForm(StatesGroup):
    waiting_for_auto_reply_text = State()
    waiting_for_response_reply_text = State()
    waiting_for_message_text = State()
    waiting_for_send_interval = State()
    waiting_for_messages_per_minute = State()

class ProfileForm(StatesGroup):
    waiting_for_api_id = State()
    waiting_for_api_hash = State()
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_password = State()

# ==================== DATABASE SETUP ==================== #
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS groups (
        link TEXT PRIMARY KEY
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
        ("response_reply_enabled", "0")
    ]
    c.executemany("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", defaults)
    conn.commit()
    conn.close()

def get_setting(key):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def set_setting(key, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def load_groups():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT link FROM groups")
    groups = [row[0] for row in c.fetchall()]
    conn.close()
    return groups

def save_group(link):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO groups (link) VALUES (?)", (link,))
    conn.commit()
    conn.close()

def remove_group(link):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM groups WHERE link = ?", (link,))
    conn.commit()
    conn.close()

def load_profiles():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT api_id, api_hash, phone, session_name FROM profiles")
    profs = [{'api_id': row[0], 'api_hash': row[1], 'phone': row[2], 'session_name': row[3]} for row in c.fetchall()]
    conn.close()
    return profs

def save_profile(api_id, api_hash, phone, session_name):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO profiles (api_id, api_hash, phone, session_name) VALUES (?, ?, ?, ?)",
              (api_id, api_hash, phone, session_name))
    conn.commit()
    conn.close()

# Initialize database
init_db()

# ==================== GLOBAL VARS ==================== #
messages_per_minute = int(get_setting("messages_per_minute"))
send_interval = int(get_setting("send_interval"))
message_text = get_setting("message_text")
auto_reply_text = get_setting("auto_reply_text")
auto_reply_enabled = bool(int(get_setting("auto_reply_enabled")))
response_reply_text = get_setting("response_reply_text")
response_reply_enabled = bool(int(get_setting("response_reply_enabled")))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
clients: List[TelegramClient] = []

# ==================== TELETHON EVENTS ==================== #
async def auto_reply_handler(event):
    if event.is_private and auto_reply_enabled:
        await event.reply(auto_reply_text)

async def response_reply_handler(event):
    if not event.is_private and response_reply_enabled:
        me = await event.client.get_me()
        if me.username and f"@{me.username}" in event.raw_text:
            await event.reply(response_reply_text)

# ==================== FUNKSIYALAR ==================== #
async def join_group(link):
    success = 0
    for client in clients:
        try:
            await client(JoinChannelRequest(link))
            print(f"✅ {client._self_id} guruhga qo‘shildi: {link}")
            success += 1
        except Exception as e:
            print(f"[Xato] {client._self_id} uchun qo‘shilishda: {e}")
    if success > 0:
        save_group(link)
        return True
    return False

async def leave_group(client, group_id):
    try:
        await client(LeaveChannelRequest(group_id))
        print(f"↩ {client._self_id} guruhdan chiqildi: {group_id}")
    except Exception as e:
        print(f"[Xato] {client._self_id} chiqishda: {e}")

async def handle_linked_channel(client, entity):
    try:
        if isinstance(entity, Channel):
            full = await client(GetFullChannelRequest(entity))
            if full.full_chat.linked_chat_id:
                await client(JoinChannelRequest(full.full_chat.linked_chat_id))
                print(f"✅ {client._self_id} linked kanalga obuna: {full.full_chat.linked_chat_id}")
                return True
    except Exception as e:
        print(f"[Xato] {client._self_id} linked tekshirishda: {e}")
    return False

async def send_to_groups_auto():
    global message_text, messages_per_minute
    while True:
        groups = load_groups()
        if not groups:
            await asyncio.sleep(send_interval)
            continue

        print("📨 Avtomatik yuborish boshlandi...")
        for link in groups.copy():
            sent = 0
            for client in clients:
                try:
                    entity = await client.get_entity(link)
                    await client.send_message(entity, message_text)
                    print(f"✅ {client._self_id} yuborildi: {link}")
                    sent += 1
                except ChatWriteForbiddenError:
                    print(f"🚫 {client._self_id} yozish taqiqlangan: {link} — Linked tekshirilmoqda...")
                    if await handle_linked_channel(client, entity):
                        try:
                            await client.send_message(entity, message_text)
                            print(f"✅ Qayta yuborildi {client._self_id}: {link}")
                            sent += 1
                        except Exception as e:
                            print(f"[Xato] {client._self_id} qayta yuborish: {e}")
                except ChannelPrivateError:
                    print(f"🚫 {client._self_id} maxfiy kanal: {link}")
                except FloodWaitError as e:
                    print(f"⏳ {client._self_id} FloodWait: {e.seconds}s kutish...")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    print(f"[Xato] {client._self_id} {link}: {e}")
                await asyncio.sleep(1)  # klientlar orasida kichik pauza

            if sent == 0:
                remove_group(link)
                for client in clients:
                    try:
                        entity = await client.get_entity(link)
                        await leave_group(client, entity.id)
                    except:
                        pass

            await asyncio.sleep(60 / messages_per_minute)

        print("✅ Barcha guruhlarga yuborildi.")
        await asyncio.sleep(send_interval)

# ==================== AIROGRAM HANDLERLAR ==================== #
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Guruh qo‘shish"), KeyboardButton(text="📋 Guruhlar ro‘yxati")],
        [KeyboardButton(text="📄 Profil ma'lumotlari"), KeyboardButton(text="🚪 Bloklanganlardan chiqish")],
        [KeyboardButton(text="🛠 Avto javob sozlamalari"), KeyboardButton(text="✉ Yuboriladigan xabar matni")],
        [KeyboardButton(text="➕ Profil qo‘shish")],
    ],
    resize_keyboard=True,
    row_width=2
)

@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    await state.clear()
    await message.answer("🤖 Userbot boshqaruv paneli ishga tushdi.", reply_markup=main_keyboard)

@dp.message(F.text == "📄 Profil ma'lumotlari")
async def profile_info(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    await state.clear()
    profiles = load_profiles()
    groups_count = len(load_groups())
    prof_info = "📱 Profillar:\n"
    for p in profiles:
        prof_info += f"- Telefon: {p['phone']}, API ID: {p['api_id']}\n"
    info = (
        prof_info + "\n"
        f"Guruhlar soni: {groups_count}\n"
        f"Avto javob: {'Faol' if auto_reply_enabled else 'O‘chirilgan'}\n"
        f"Avto javob matni: {auto_reply_text}\n"
        f"Guruh avto javobi: {'Faol' if response_reply_enabled else 'O‘chirilgan'}\n"
        f"Guruh avto javob matni: {response_reply_text}\n"
        f"Yuboriladigan xabar: {message_text}\n"
        f"1 daqiqada guruhlar: {messages_per_minute}\n"
        f"Yuborish oralig'i: {send_interval // 60} daqiqa"
    )
    await message.answer(info)

@dp.message(F.text == "📋 Guruhlar ro‘yxati")
async def show_groups(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    await state.clear()
    groups = load_groups()
    if not groups:
        await message.answer("📭 Hozircha guruh yo‘q.")
    else:
        text = "\n".join([f"{i+1}. {g}" for i, g in enumerate(groups)])
        await message.answer(f"📋 Guruhlar:\n{text}")

@dp.message(F.text == "➕ Guruh qo‘shish")
async def ask_group_link(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    await state.clear()
    await message.answer("🔗 Guruh linklarini yuboring (har birini yangi qatorda, masalan: https://t.me/groupname).")

@dp.message(F.text.contains("https://t.me/"))
async def add_groups(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    await state.clear()
    links = [line.strip() for line in message.text.splitlines() if "https://t.me/" in line]
    groups = load_groups()
    added = 0

    for link in links:
        if link not in groups:
            if await join_group(link):
                added += 1

    await message.answer(f"✅ {added} ta yangi guruh qo‘shildi. Umumiy: {len(load_groups())} ta.")

@dp.message(F.text == "🚪 Bloklanganlardan chiqish")
async def leave_blocked_handler(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    await state.clear()
    left_count = 0
    for client in clients:
        dialogs = await client.get_dialogs()
        for d in dialogs:
            if isinstance(d.entity, Channel):
                try:
                    me = await client.get_me()
                    participant = await client.get_participant(d.entity, me)
                    if participant.banned_rights and participant.banned_rights.send_messages:
                        await leave_group(client, d.entity.id)
                        groups = load_groups()
                        link = next((g for g in groups if d.entity.id == (await client.get_entity(g)).id), None)
                        if link:
                            remove_group(link)
                        left_count += 1
                except ValueError:
                    pass
                except Exception as e:
                    print(f"[Xato] {client._self_id} guruh tekshirishda: {e}")
    await message.answer(f"✅ {left_count} ta bloklangan guruhdan chiqildi.")

@dp.message(F.text == "🛠 Avto javob sozlamalari")
async def auto_reply_settings(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    await state.clear()
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔄 Avto javob holatini o‘zgartirish")],
            [KeyboardButton(text="📝 Avto javob matnini o‘zgartirish")],
            [KeyboardButton(text="🔄 Guruh avto javob holatini o‘zgartirish")],
            [KeyboardButton(text="📝 Guruh avto javob matnini o‘zgartirish")],
            [KeyboardButton(text="🔙 Orqaga")],
        ],
        resize_keyboard=True
    )
    await message.answer("🛠 Avto javob sozlamalari:", reply_markup=keyboard)

@dp.message(F.text == "🔄 Avto javob holatini o‘zgartirish")
async def toggle_auto_reply(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    global auto_reply_enabled
    await state.clear()
    auto_reply_enabled = not auto_reply_enabled
    set_setting("auto_reply_enabled", "1" if auto_reply_enabled else "0")
    status = "Faol" if auto_reply_enabled else "O‘chirilgan"
    await message.answer(f"Avto javob holati: {status}")

@dp.message(F.text == "📝 Avto javob matnini o‘zgartirish")
async def change_auto_reply_text(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    await state.set_state(SettingsForm.waiting_for_auto_reply_text)
    await message.answer("Yangi avto javob matnini yuboring:")

@dp.message(F.text == "🔄 Guruh avto javob holatini o‘zgartirish")
async def toggle_response_reply(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    global response_reply_enabled
    await state.clear()
    response_reply_enabled = not response_reply_enabled
    set_setting("response_reply_enabled", "1" if response_reply_enabled else "0")
    status = "Faol" if response_reply_enabled else "O‘chirilgan"
    await message.answer(f"Guruh avto javob holati: {status}")

@dp.message(F.text == "📝 Guruh avto javob matnini o‘zgartirish")
async def change_response_reply_text(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    await state.set_state(SettingsForm.waiting_for_response_reply_text)
    await message.answer("Yangi guruh avto javob matnini yuboring:")

@dp.message(F.text == "✉ Yuboriladigan xabar matni")
async def change_message_text(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    await state.set_state(SettingsForm.waiting_for_message_text)
    await message.answer("Yangi yuboriladigan xabar matnini yuboring:")

@dp.message(F.text == "⏱ Yuborish oralig'i")
async def change_send_interval(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    await state.set_state(SettingsForm.waiting_for_send_interval)
    await message.answer("Yangi oralig'ni daqiqalarda yuboring (masalan, 1):")

@dp.message(F.text == "🚀 1 daqiqada nechta guruh")
async def change_messages_per_minute(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    await state.set_state(SettingsForm.waiting_for_messages_per_minute)
    await message.answer("1 daqiqada nechta guruhga xabar yuborishni yuboring (masalan, 30):")

@dp.message(F.text == "🔙 Orqaga")
async def back_to_main(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    await state.clear()
    await start_cmd(message, state)

@dp.message(SettingsForm.waiting_for_auto_reply_text)
async def process_auto_reply_text(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    global auto_reply_text
    text = message.text.strip()
    if text:
        auto_reply_text = text
        set_setting("auto_reply_text", text)
        await message.answer(f"Avto javob matni o'zgartirildi: {text}")
        await state.clear()
    else:
        await message.answer("Iltimos, bo‘sh bo‘lmagan matn yuboring.")

@dp.message(SettingsForm.waiting_for_response_reply_text)
async def process_response_reply_text(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    global response_reply_text
    text = message.text.strip()
    if text:
        response_reply_text = text
        set_setting("response_reply_text", text)
        await message.answer(f"Guruh avto javob matni o'zgartirildi: {text}")
        await state.clear()
    else:
        await message.answer("Iltimos, bo‘sh bo‘lmagan matn yuboring.")

@dp.message(SettingsForm.waiting_for_message_text)
async def process_message_text(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    global message_text
    text = message.text.strip()
    if text:
        message_text = text
        set_setting("message_text", text)
        await message.answer(f"Yuboriladigan xabar o'zgartirildi: {text}")
        await state.clear()
    else:
        await message.answer("Iltimos, bo‘sh bo‘lmagan matn yuboring.")

@dp.message(SettingsForm.waiting_for_send_interval)
async def process_send_interval(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    global send_interval
    text = message.text.strip()
    if text.isdigit() and int(text) > 0:
        send_interval = int(text) * 60
        set_setting("send_interval", str(send_interval))
        await message.answer(f"Yuborish oralig'i {text} daqiqaga o'zgartirildi.")
        await state.clear()
    else:
        await message.answer("Iltimos, musbat butun son yuboring (masalan, 1).")

@dp.message(SettingsForm.waiting_for_messages_per_minute)
async def process_messages_per_minute(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    global messages_per_minute
    text = message.text.strip()
    if text.isdigit() and int(text) > 0:
        messages_per_minute = int(text)
        set_setting("messages_per_minute", str(messages_per_minute))
        await message.answer(f"1 daqiqada {text} ta guruhga o'zgartirildi.")
        await state.clear()
    else:
        await message.answer("Iltimos, musbat butun son yuboring (masalan, 30).")

@dp.message(F.text == "➕ Profil qo‘shish")
async def add_profile_start(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    await state.set_state(ProfileForm.waiting_for_api_id)
    await message.answer("API ID ni yuboring:")

@dp.message(ProfileForm.waiting_for_api_id)
async def process_api_id(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    if not message.text.isdigit():
        await message.answer("Butun son yuboring.")
        return
    await state.update_data(api_id=int(message.text))
    await state.set_state(ProfileForm.waiting_for_api_hash)
    await message.answer("API HASH ni yuboring:")

@dp.message(ProfileForm.waiting_for_api_hash)
async def process_api_hash(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    await state.update_data(api_hash=message.text.strip())
    await state.set_state(ProfileForm.waiting_for_phone)
    await message.answer("Telefon raqamini yuboring (+998...):")

@dp.message(ProfileForm.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    phone = message.text.strip()
    if not phone.startswith('+'):
        await message.answer("+ bilan boshlanishi kerak.")
        return
    await state.update_data(phone=phone)
    data = await state.get_data()
    api_id = data['api_id']
    api_hash = data['api_hash']
    session_name = f"session_{phone[1:]}"
    client = TelegramClient(session_name, api_id, api_hash)
    try:
        await client.connect()
        sent_code = await client.send_code_request(phone)
        await state.update_data(client=client, session_name=session_name, code_hash=sent_code.phone_code_hash)
        await state.set_state(ProfileForm.waiting_for_code)
        await message.answer("Telegramdan kelgan kodni yuboring:")
    except Exception as e:
        await client.disconnect()
        await message.answer(f"Xato: {str(e)}")
        await state.clear()

@dp.message(ProfileForm.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    data = await state.get_data()
    client = data.get('client')
    phone = data.get('phone')
    code_hash = data.get('code_hash')
    code = message.text.strip()
    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
        # Profil muvaffaqiyatli qo‘shildi
        api_id = data.get('api_id')
        api_hash = data.get('api_hash')
        session_name = data.get('session_name')
        save_profile(api_id, api_hash, phone, session_name)
        client.add_event_handler(auto_reply_handler, events.NewMessage(incoming=True))
        client.add_event_handler(response_reply_handler, events.NewMessage(incoming=True, pattern=r'(?i)@[\w\d_]+'))
        clients.append(client)
        await bot.send_message(message.chat.id, f"Profil qo‘shildi: {phone}")
        await state.clear()
    except SessionPasswordNeededError:
        await state.update_data(client=client)
        await state.set_state(ProfileForm.waiting_for_password)
        await bot.send_message(message.chat.id, "2FA parolni yuboring:")
    except Exception as e:
        await client.disconnect()
        await bot.send_message(message.chat.id, f"Xato: {str(e)}")
        await state.clear()

@dp.message(ProfileForm.waiting_for_password)
async def process_password(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    data = await state.get_data()
    client = data.get('client')
    phone = data.get('phone')
    session_name = data.get('session_name')
    api_id = data.get('api_id')
    api_hash = data.get('api_hash')
    password = message.text.strip()
    try:
        await client.sign_in(password=password)
        save_profile(api_id, api_hash, phone, session_name)
        client.add_event_handler(auto_reply_handler, events.NewMessage(incoming=True))
        client.add_event_handler(response_reply_handler, events.NewMessage(incoming=True, pattern=r'(?i)@[\w\d_]+'))
        clients.append(client)
        await bot.send_message(message.chat.id, f"Profil qo‘shildi: {phone}")
        await state.clear()
    except Exception as e:
        await client.disconnect()
        await bot.send_message(message.chat.id, f"Xato: {str(e)}")
        await state.clear()

@dp.message()
async def general_handler(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("Sizga ruxsat yo‘q.")
        return
    await message.answer("Iltimos, sozlamani o'zgartirish uchun mos tugmani bosing.")

# ==================== ASOSIY MAIN ==================== #
async def main():
    profiles = load_profiles()
    for prof in profiles:
        client = TelegramClient(prof['session_name'], prof['api_id'], prof['api_hash'])
        client.add_event_handler(auto_reply_handler, events.NewMessage(incoming=True))
        client.add_event_handler(response_reply_handler, events.NewMessage(incoming=True, pattern=r'(?i)@[\w\d_]+'))
        try:
            await client.connect()
            if await client.is_user_authorized():
                clients.append(client)
                me = await client.get_me()
                print(f"🔗 Userbot ulandi: {me.first_name} (@{me.username or 'None'})")
            else:
                print(f"[Xato] Profil avtorizatsiya qilinmadi: {prof['phone']}")
                await client.disconnect()
        except Exception as e:
            print(f"[Xato] Profil ulanmadi {prof['phone']}: {e}")
            await client.disconnect()

    asyncio.create_task(send_to_groups_auto())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())