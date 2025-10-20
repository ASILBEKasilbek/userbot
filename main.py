import asyncio
import logging
from aiogram import Bot
from db import init_db, load_profiles
from aiogram_handlers import dp, clients
from telethon_utils import send_to_groups_auto, auto_reply_handler, response_reply_handler
from telethon import TelegramClient, events
from config import BOT_TOKEN
from telethon_utils import load_existing_groups

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

init_db()
bot = Bot(token=BOT_TOKEN)

async def main():
    """Botni ishga tushirish va profillarni yuklash."""
    profiles = load_profiles()
    for prof in profiles:
        client = TelegramClient(prof['session_name'], prof['api_id'], prof['api_hash'])
        client.profile_id = prof['id']
        try:
            await client.connect()
            if await client.is_user_authorized():
                client.add_event_handler(auto_reply_handler, events.NewMessage(incoming=True))
                client.add_event_handler(response_reply_handler, events.NewMessage(incoming=True, pattern=r'(?i)@[\w\d_]+'))
                await load_existing_groups(client, prof['id'])
                clients.append(client)
                me = await client.get_me()
                logger.info(f"🔗 Userbot ulandi: {me.first_name} (@{me.username or 'None'})")
            else:
                logger.warning(f"Profil avtorizatsiya qilinmadi: {prof['phone']}")
                await client.disconnect()
        except Exception as e:
            logger.error(f"Profil ulanmadi {prof['phone']}: {e}")
            await client.disconnect()

    asyncio.create_task(send_to_groups_auto(clients))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())