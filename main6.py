import asyncio
import os
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from telethon import TelegramClient, events
from telethon.errors import ChatWriteForbiddenError, ChannelPrivateError, FloodWaitError
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.types import Channel
from dotenv import load_dotenv

# ==================== CONFIG ==================== #
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE", "+998XXXXXXXXX")
SESSION_NAME = "userbot_session"

DB_FILE = "userbot_settings.db"

# ==================== FSM STATES ==================== #
class SettingsForm(StatesGroup):
    waiting_for_auto_reply_text = State()
    waiting_for_response_reply_text = State()
    waiting_for_message_text = State()
    waiting_for_send_interval = State()
    waiting_for_messages_per_minute = State()

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
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# ==================== TELETHON EVENTS ==================== #
@client.on(events.NewMessage(incoming=True))
async def auto_reply_handler(event):
    if event.is_private and auto_reply_enabled:
        await event.reply(auto_reply_text)

@client.on(events.NewMessage(incoming=True, pattern=r'(?i)@[\w\d_]+'))
async def response_reply_handler(event):
    if not event.is_private and response_reply_enabled:
        me = await client.get_me()
        if me.username and f"@{me.username}" in event.raw_text:
            await event.reply(response_reply_text)

# ==================== FUNKSIYALAR ==================== #
async def join_group(link):
    try:
        await client(JoinChannelRequest(link))
        save_group(link)
        print(f"✅ Guruh qo‘shildi: {link}")
        return True
    except Exception as e:
        print(f"[Xato] Guruhga qo‘shilishda: {e}")
        return False

async def leave_group(group_id):
    try:
        await client(LeaveChannelRequest(group_id))
        print(f"↩ Guruhdan chiqildi: {group_id}")
    except Exception as e:
        print(f"[Xato] Guruhdan chiqishda: {e}")

async def handle_linked_channel(entity):
    """Subscribe to linked discussion group if exists"""
    try:
        if isinstance(entity, Channel):
            full_channel = await client.get_entity(entity, force_fetch=True)
            if hasattr(full_channel, 'full_chat') and hasattr(full_channel.full_chat, 'linked_chat_id') and full_channel.full_chat.linked_chat_id:
                try:
                    await client(JoinChannelRequest(full_channel.full_chat.linked_chat_id))
                    print(f"✅ Linked kanalga obuna bo'ldi: {full_channel.full_chat.linked_chat_id}")
                    return True
                except Exception as e:
                    print(f"[Xato] Linked kanalga obuna: {e}")
    except Exception as e:
        print(f"[Xato] Linked kanal tekshirishda: {e}")
    return False

async def send_to_groups_auto():
    """Send messages to groups automatically every send_interval"""
    global message_text, messages_per_minute
    while True:
        groups = load_groups()
        if not groups:
            await asyncio.sleep(send_interval)
            continue

        print("📨 Avtomatik yuborish boshlandi...")
        for link in groups.copy():
            try:
                entity = await client.get_entity(link)
                await client.send_message(entity, message_text)
                print(f"✅ Xabar yuborildi: {link}")
            except ChatWriteForbiddenError:
                print(f"🚫 Yozish taqiqlangan: {link} — Linked kanal tekshirilmoqda...")
                if await handle_linked_channel(entity):
                    try:
                        await client.send_message(entity, message_text)
                        print(f"✅ Qayta yuborildi: {link}")
                    except Exception as e:
                        print(f"[Xato] Qayta yuborish: {e}")
                        remove_group(link)
                        await leave_group(entity.id)
                else:
                    remove_group(link)
                    await leave_group(entity.id)
            except ChannelPrivateError:
                print(f"🚫 Maxfiy kanal: {link} — o‘chirilmoqda...")
                remove_group(link)
                await leave_group(entity.id)
            except FloodWaitError as e:
                print(f"⏳ FloodWait: {e.seconds}s kutish...")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                print(f"[Xato] {link}: {e}")
                remove_group(link)
                await leave_group(entity.id)

            await asyncio.sleep(60 / messages_per_minute)

        print("✅ Barcha guruhlarga yuborildi.")
        await asyncio.sleep(send_interval)

# ==================== AIROGRAM HANDLERLAR ==================== #
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Guruh qo‘shish"), KeyboardButton(text="📋 Guruhlar ro‘yxati")],
        [KeyboardButton(text="📄 Profil ma'lumotlari"), KeyboardButton(text="🚪 Bloklanganlardan chiqish")],
        [KeyboardButton(text="🛠 Avto javob sozlamalari"), KeyboardButton(text="✉ Yuboriladigan xabar matni")],
        # [KeyboardButton(text="⏱ Yuborish oralig'i"), KeyboardButton(text="🚀 1 daqiqada nechta guruh")],
    ],
    resize_keyboard=True,
    row_width=2
)

@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()  # Clear any existing state
    await message.answer("🤖 Userbot boshqaruv paneli ishga tushdi.", reply_markup=main_keyboard)

@dp.message(F.text == "📄 Profil ma'lumotlari")
async def profile_info(message: types.Message, state: FSMContext):
    await state.clear()
    groups_count = len(load_groups())
    info = (
        f"📱 Profil:\n"
        f"Telefon: {PHONE}\n"
        f"API ID: {API_ID}\n"
        f"API Hash: {API_HASH}\n"
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
    await state.clear()
    groups = load_groups()
    if not groups:
        await message.answer("📭 Hozircha guruh yo‘q.")
    else:
        text = "\n".join([f"{i+1}. {g}" for i, g in enumerate(groups)])
        await message.answer(f"📋 Guruhlar:\n{text}")

@dp.message(F.text == "➕ Guruh qo‘shish")
async def ask_group_link(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🔗 Guruh linklarini yuboring (har birini yangi qatorda, masalan: https://t.me/groupname).")

@dp.message(F.text.contains("https://t.me/"))
async def add_groups(message: types.Message, state: FSMContext):
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
    await state.clear()
    dialogs = await client.get_dialogs()
    left_count = 0
    for d in dialogs:
        if isinstance(d.entity, Channel):
            try:
                participant = await client.get_permissions(d.id, 'me')
                if participant.is_banned or (participant.banned_rights and participant.banned_rights.send_messages):
                    await leave_group(d.id)
                    groups = load_groups()
                    link = next((g for g in groups if d.id == (await client.get_entity(g)).id), None)
                    if link:
                        remove_group(link)
                    left_count += 1
            except Exception as e:
                print(f"[Xato] Guruh tekshirishda: {e}")
                await leave_group(d.id)
                left_count += 1
    await message.answer(f"✅ {left_count} ta bloklangan guruhdan chiqildi.")

@dp.message(F.text == "🛠 Avto javob sozlamalari")
async def auto_reply_settings(message: types.Message, state: FSMContext):
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
    global auto_reply_enabled
    await state.clear()
    auto_reply_enabled = not auto_reply_enabled
    set_setting("auto_reply_enabled", "1" if auto_reply_enabled else "0")
    status = "Faol" if auto_reply_enabled else "O‘chirilgan"
    await message.answer(f"Avto javob holati: {status}")

@dp.message(F.text == "📝 Avto javob matnini o‘zgartirish")
async def change_auto_reply_text(message: types.Message, state: FSMContext):
    await state.set_state(SettingsForm.waiting_for_auto_reply_text)
    await message.answer("Yangi avto javob matnini yuboring:")

@dp.message(F.text == "🔄 Guruh avto javob holatini o‘zgartirish")
async def toggle_response_reply(message: types.Message, state: FSMContext):
    global response_reply_enabled
    await state.clear()
    response_reply_enabled = not response_reply_enabled
    set_setting("response_reply_enabled", "1" if response_reply_enabled else "0")
    status = "Faol" if response_reply_enabled else "O‘chirilgan"
    await message.answer(f"Guruh avto javob holati: {status}")

@dp.message(F.text == "📝 Guruh avto javob matnini o‘zgartirish")
async def change_response_reply_text(message: types.Message, state: FSMContext):
    await state.set_state(SettingsForm.waiting_for_response_reply_text)
    await message.answer("Yangi guruh avto javob matnini yuboring:")

@dp.message(F.text == "✉ Yuboriladigan xabar matni")
async def change_message_text(message: types.Message, state: FSMContext):
    await state.set_state(SettingsForm.waiting_for_message_text)
    await message.answer("Yangi yuboriladigan xabar matnini yuboring:")

@dp.message(F.text == "⏱ Yuborish oralig'i")
async def change_send_interval(message: types.Message, state: FSMContext):
    await state.set_state(SettingsForm.waiting_for_send_interval)
    await message.answer("Yangi oralig'ni daqiqalarda yuboring (masalan, 1):")

@dp.message(F.text == "🚀 1 daqiqada nechta guruh")
async def change_messages_per_minute(message: types.Message, state: FSMContext):
    await state.set_state(SettingsForm.waiting_for_messages_per_minute)
    await message.answer("1 daqiqada nechta guruhga xabar yuborishni yuboring (masalan, 30):")

@dp.message(F.text == "🔙 Orqaga")
async def back_to_main(message: types.Message, state: FSMContext):
    await state.clear()
    await start_cmd(message, state)

@dp.message(SettingsForm.waiting_for_auto_reply_text)
async def process_auto_reply_text(message: types.Message, state: FSMContext):
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
    global messages_per_minute
    text = message.text.strip()
    if text.isdigit() and int(text) > 0:
        messages_per_minute = int(text)
        set_setting("messages_per_minute", str(messages_per_minute))
        await message.answer(f"1 daqiqada {text} ta guruhga o'zgartirildi.")
        await state.clear()
    else:
        await message.answer("Iltimos, musbat butun son yuboring (masalan, 30).")

@dp.message()
async def general_handler(message: types.Message, state: FSMContext):
    await message.answer("Iltimos, sozlamani o'zgartirish uchun mos tugmani bosing.")

# ==================== ASOSIY MAIN ==================== #
async def main():
    await client.start(PHONE)
    me = await client.get_me()
    print(f"🔗 Userbot ulandi: {me.first_name} (@{me.username or 'None'})")

    asyncio.create_task(send_to_groups_auto())

    await asyncio.gather(
        dp.start_polling(bot),
        client.run_until_disconnected()
    )

if __name__ == "__main__":
    asyncio.run(main())