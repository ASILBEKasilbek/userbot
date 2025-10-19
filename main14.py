import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telethon.sync import TelegramClient
from telethon import events
from telethon.errors import ChatWriteForbiddenError, ChannelPrivateError, FloodWaitError
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.types import ChatBannedRights, Channel
from dotenv import load_dotenv
load_dotenv()
    
# Aiogram bot tokenini o'rnating (Telegram BotFatherdan oling)
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Telethon userbot uchun API ID va HASH (foydalanuvchi bergan)
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION_NAME = 'userbot_session'
PHONE = '+998332726418'

# O'zgaruvchilar (sozlamalar)
messages_per_minute = 30  # 1 daqiqada nechta guruhga xabar
auto_reply_text = 'Salom! Bu avtomatik javob.'
auto_reply_enabled = True  # Avto xabar holati
response_reply_enabled = False  # Javob xabar holati (guruhdagi mentions ga javob, hozircha o'chirilgan)
response_reply_text = 'Avto javob guruhda.'

# Aiogram bot va dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Telethon client (userbot)
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# Auto javob uchun event (lichkaga)
@client.on(events.NewMessage(incoming=True))
async def auto_reply(event):
    if event.is_private and auto_reply_enabled:
        await event.reply(auto_reply_text)\

@client.on(events.NewMessage(incoming=True))
async def mention_auto_reply(event):
    # Faqat guruhda ishlasin
    if event.is_private:
        return
    
    # Agar avtomatik javob funksiyasi o'chirilgan bo'lsa
    if not response_reply_enabled:
        return

    # Mening username-imni olish
    me = await client.get_me()
    my_username = me.username.lower() if me.username else None

    if not my_username:
        return  # Agar foydalanuvchida username bo'lmasa, chiqamiz

    # Kimdir meni tilga oldimi?
    message_text = event.raw_text.lower()
    if f"@{my_username}" in message_text:
        try:
            await event.reply(response_reply_text)
            print(f"↪ Guruhda @{my_username} tilga olindi, javob yuborildi.")
        except Exception as e:
            print(f"Xatolik yuz berdi: {e}")


# Guruhlarga xabar yuborish funksiyasi (tezlik sozlamasi bilan, har bir guruh orasida kutish)
async def send_to_groups(message):
    dialogs = await client.get_dialogs()
    sleep_time = 60 / messages_per_minute  # Har bir xabar orasidagi sekund
    for dialog in dialogs:
        if dialog.is_group or dialog.is_channel:
            try:
                await client.send_message(dialog.id, message)
                print(f"Xabar {dialog.name} ga yuborildi")
                await asyncio.sleep(sleep_time)
            except ChatWriteForbiddenError as e:
                print(f"{dialog.name} ga yozib bo'lmaydi (yozish taqiqlangan)...")
                # Agar linked channel bo'lsa, obuna bo'lishga urinish
                await handle_join_linked_channel(dialog.id)
                # Qayta urinish
                try:
                    await client.send_message(dialog.id, message)
                    print(f"Qayta yuborildi {dialog.name} ga")
                    await asyncio.sleep(sleep_time)
                except:
                    await leave_blocked_group(dialog.id)
            except ChannelPrivateError:
                print(f"{dialog.name} maxfiy, chiqib ketilmoqda...")
                await leave_blocked_group(dialog.id)
            except FloodWaitError as e:
                print(f"Flood kutish: {e.seconds} sekund")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                print(f"Xato: {e}")
                await leave_blocked_group(dialog.id)

# Linked channelga obuna bo'lish (agar mavjud bo'lsa)
async def handle_join_linked_channel(group_id):
    try:
        entity = await client.get_entity(group_id)
        if isinstance(entity, Channel) and entity.linked_chat_id:
            linked_channel_id = entity.linked_chat_id
            await client(JoinChannelRequest(linked_channel_id))
            print(f"Linked kanalga obuna bo'ldi: {linked_channel_id}")
        else:
            print("Linked kanal topilmadi.")
    except Exception as e:
        print(f"Linked kanal xatosi: {e}")

# Kanalga qo'shilish
async def join_channel(channel_username_or_id):
    try:
        await client(JoinChannelRequest(channel_username_or_id))
        print(f"{channel_username_or_id} ga qo'shildi")
    except Exception as e:
        print(f"Xato: {e}")

# Bloklangan yoki yozish taqiqlangan guruhdan chiqish
async def leave_blocked_group(group_id):
    try:
        participant = await client.get_permissions(group_id, 'me')
        if participant.is_banned or participant.banned_rights.send_messages:
            await client(LeaveChannelRequest(group_id))
            print(f"Bloklangan guruh {group_id} dan chiqildi")
    except Exception as e:
        print(f"Xato: {e}")

# Barcha bloklangan guruhlardan chiqish
async def leave_all_blocked():
    dialogs = await client.get_dialogs()
    for dialog in dialogs:
        if dialog.is_group or dialog.is_channel:
            await leave_blocked_group(dialog.id)

# Profil ma'lumotlarini ko'rsatish
def get_profile_info():
    return f"""Profil ma'lumotlari
Telefon: {PHONE}
ID: {API_ID}
API Hash: {API_HASH}
Holat: Profilga muvaffaqiyatli kirilgan
• 1 daqiqada nechta guruhga xabar: {messages_per_minute}
"""

# Aiogram bot komandalari va menyusi
from aiogram.utils.keyboard import ReplyKeyboardBuilder

@dp.message(Command('start'))
async def start(message: types.Message):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Profil ma'lumotlari"), KeyboardButton(text="1 daqiqada nechta guruhga xabar")],
            [KeyboardButton(text="Avto xabar matnini o'zgartirish"), KeyboardButton(text="Avto xabar holati")],
            [KeyboardButton(text="Javob xabar holati"), KeyboardButton(text="Javob xabar matnini o'zgartirish")],
            [KeyboardButton(text="Profilni o'chirish"), KeyboardButton(text="Guruhlarga xabar yuborish")],
            [KeyboardButton(text="Kanalga qo'shilish"), KeyboardButton(text="Bloklangan guruhlardan chiqish")],
            [KeyboardButton(text="Orqaga")]
        ],
        resize_keyboard=True
    )

    await message.reply("Salom! Bot ishga tushdi. Quyidagi tugmalardan foydalaning:", reply_markup=keyboard)

@dp.message(lambda message: message.text == "Profil ma'lumotlari")
async def show_profile(message: types.Message):
    await message.reply(get_profile_info())

@dp.message(lambda message: message.text == "1 daqiqada nechta guruhga xabar")
async def set_rate(message: types.Message):
    await message.reply("Yangi qiymatni kiriting (masalan, 30):")

@dp.message(lambda message: message.text.isdigit() and int(message.text) > 0)  # Rate o'zgartirish
async def update_rate(message: types.Message):
    global messages_per_minute
    messages_per_minute = int(message.text)
    await message.reply(f"1 daqiqada nechta guruhga xabar: {messages_per_minute} ga o'zgartirildi.")

@dp.message(lambda message: message.text == "Avto xabar matnini o'zgartirish")
async def set_auto_text(message: types.Message):
    await message.reply("Yangi avto xabar matnini kiriting:")

@dp.message()  # Avto matn o'zgartirish (keyingi xabar)
async def update_auto_text(message: types.Message):
    if message.text not in ["Profil ma'lumotlari", "1 daqiqada nechta guruhga xabar", "Avto xabar matnini o'zgartirish", "Avto xabar holati", "Javob xabar holati", "Javob xabar matnini o'zgartirish", "Profilni o'chirish", "Guruhlarga xabar yuborish", "Kanalga qo'shilish", "Bloklangan guruhlardan chiqish", "Orqaga"]:
        global auto_reply_text
        auto_reply_text = message.text
        await message.reply(f"Avto xabar matni o'zgartirildi: {auto_reply_text}")

@dp.message(lambda message: message.text == "Avto xabar holati")
async def toggle_auto(message: types.Message):
    global auto_reply_enabled
    auto_reply_enabled = not auto_reply_enabled
    status = "Faol" if auto_reply_enabled else "O'chirilgan"
    await message.reply(f"Avto xabar holati: {status}")

@dp.message(lambda message: message.text == "Javob xabar holati")
async def toggle_response(message: types.Message):
    global response_reply_enabled
    response_reply_enabled = not response_reply_enabled
    status = "Faol" if response_reply_enabled else "O'chirilgan"
    await message.reply(f"Javob xabar holati: {status}")

@dp.message(lambda message: message.text == "Javob xabar matnini o'zgartirish")
async def set_response_text(message: types.Message):
    await message.reply("Yangi javob xabar matnini kiriting:")

# Javob matn o'zgartirish (keyingi handler da qo'l bilan ishlash mumkin, lekin yuqoridagi kabi)

@dp.message(lambda message: message.text == "Profilni o'chirish")
async def delete_profile(message: types.Message):
    try:
        os.remove(f"{SESSION_NAME}.session")
        await message.reply("Profil o'chirildi. Qayta ishga tushiring.")
    except:
        await message.reply("Xato: Session fayli topilmadi.")

@dp.message(lambda message: message.text == "Guruhlarga xabar yuborish")
async def cmd_send_message(message: types.Message):
    await message.reply("Xabarni kiriting:")

# Xabar yuborish (keyingi xabar)

@dp.message(lambda message: message.text == "Kanalga qo'shilish")
async def cmd_join_channel(message: types.Message):
    await message.reply("Kanal username yoki ID ni kiriting:")

# Qo'shilish (keyingi)

@dp.message(lambda message: message.text == "Bloklangan guruhlardan chiqish")
async def cmd_leave_blocked(message: types.Message):
    await leave_all_blocked()
    await message.reply("Bloklangan guruhlardan chiqildi")

@dp.message(lambda message: message.text == "Orqaga")
async def back(message: types.Message):
    await start(message)

async def main():
    await client.start(phone=PHONE)

    me = await client.get_me()
    print(f"✅ Ulangan akkaunt: {me.first_name} (@{me.username}) | ID: {me.id}")

    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())