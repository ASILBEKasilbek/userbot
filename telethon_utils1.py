import asyncio
import logging
from telethon import TelegramClient, events
from telethon.errors import ChatWriteForbiddenError, ChannelPrivateError, FloodWaitError, UserBannedInChannelError
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest, GetFullChannelRequest
from telethon.tl.types import Channel
from db import load_groups, save_group, remove_group, get_profile_setting

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

async def auto_reply_handler(event):
    """Shaxsiy xabarlarga avtomatik javob berish."""
    profile_id = event.client.profile_id
    auto_reply_enabled = bool(int(get_profile_setting(profile_id, "auto_reply_enabled") or 0))
    auto_reply_text = get_profile_setting(profile_id, "auto_reply_text") or "Salom! Bu avtomatik javob."
    if event.is_private and auto_reply_enabled:
        await event.reply(auto_reply_text)

async def response_reply_handler(event):
    """Guruhlarda foydalanuvchi nomiga javob berish."""
    profile_id = event.client.profile_id
    response_reply_enabled = bool(int(get_profile_setting(profile_id, "response_reply_enabled") or 0))
    response_reply_text = get_profile_setting(profile_id, "response_reply_text") or "Avto javob guruhda."
    if not event.is_private and response_reply_enabled:
        me = await event.client.get_me()
        if me.username and f"@{me.username}" in event.raw_text:
            await event.reply(response_reply_text)

async def join_group(client: TelegramClient, link: str, profile_id: int) -> bool:
    """Guruhga qo‘shilish va uni ma'lumotlar bazasiga saqlash."""
    try:
        entity = await client.get_entity(link)
        await client(JoinChannelRequest(entity))
        save_group(link, profile_id)
        logger.info(f"{client._self_id} guruhga qo‘shildi: {link}")
        return True
    except Exception as e:
        logger.error(f"{client._self_id} guruhga qo‘shilishda xato: {link} - {e}")
        return False

async def leave_group(client: TelegramClient, group_id: int, profile_id: int, link: str):
    """Guruhdan chiqish va uni ma'lumotlar bazasidan o‘chirish."""
    try:
        await client(LeaveChannelRequest(group_id))
        remove_group(link, profile_id)
        logger.info(f"{client._self_id} guruhdan chiqildi: {link}")
    except Exception as e:
        logger.error(f"{client._self_id} guruhdan chiqishda xato: {link} - {e}")

async def handle_linked_channel(client: TelegramClient, entity, profile_id: int) -> bool:
    """Guruhga bog‘langan kanalga qo‘shilish."""
    try:
        if isinstance(entity, Channel):
            full = await client(GetFullChannelRequest(entity))
            if full.full_chat.linked_chat_id:
                link = f"https://t.me/c/{full.full_chat.linked_chat_id}"
                await client(JoinChannelRequest(full.full_chat.linked_chat_id))
                save_group(link, profile_id)
                logger.info(f"{client._self_id} bog‘langan kanalga qo‘shildi: {link}")
                return True
    except Exception as e:
        logger.error(f"{client._self_id} bog‘langan kanalni tekshirishda xato: {e}")
    return False

async def load_existing_groups(client: TelegramClient, profile_id: int):
    try:
        dialogs = await client.get_dialogs()
        for d in dialogs:
            if isinstance(d.entity, Channel) and (d.entity.broadcast or d.entity.megagroup):
                try:
                    entity = d.entity
                    link = f"https://t.me/{entity.username}" if entity.username else f"https://t.me/c/{entity.id}"
                    save_group(link, profile_id)
                    logger.info(f"{client._self_id} guruh yuklandi: {link}")
                except Exception as e:
                    logger.error(f"Guruh linkini olishda xato: {e}")
    except Exception as e:
        logger.error(f"{client._self_id} mavjud guruhlarni yuklashda xato: {e}")
import asyncio
import logging
import random
from telethon.errors import (
    ChatWriteForbiddenError,
    ChannelPrivateError,
    UserBannedInChannelError,
    FloodWaitError,
)
from telethon.tl.functions.channels import JoinChannelRequest, GetFullChannelRequest
from telethon.tl.types import Channel
from db import load_groups, get_profile_setting
from telethon_utils1 import handle_linked_channel, leave_group



async def try_join_linked_channel(client, entity, profile_id: int) -> bool:
    """Agar yozish uchun kanalga obuna bo‘lish kerak bo‘lsa, avtomatik kanalga qo‘shiladi."""
    try:
        if isinstance(entity, Channel):
            full = await client(GetFullChannelRequest(entity))

            # Guruh bilan bog‘langan kanalni tekshirish
            linked_chat_id = getattr(full.full_chat, "linked_chat_id", None)
            if linked_chat_id:
                try:
                    linked_channel = await client.get_entity(linked_chat_id)
                    await client(JoinChannelRequest(linked_channel))
                    logger.info(f"📡 {client._self_id} kanalga avtomatik qo‘shildi: {linked_channel.title}")
                    return True
                except Exception as e:
                    logger.warning(f"❌ Kanalga qo‘shila olmadi: {e}")
                    return False

            # Agar linked_chat_id topilmasa, kanal havolasini olishga urinadi
            invite_link = getattr(full.full_chat, "exported_invite", None)
            if invite_link and hasattr(invite_link, "link"):
                try:
                    await client(JoinChannelRequest(invite_link.link))
                    logger.info(f"📡 {client._self_id} havola orqali kanalga qo‘shildi: {invite_link.link}")
                    return True
                except Exception as e:
                    logger.warning(f"❌ Havola orqali kanalga qo‘shila olmadi: {e}")

    except Exception as e:
        logger.error(f"🔍 Bog‘langan kanalni aniqlashda xato: {e}")

    return False

logger = logging.getLogger(__name__)

# BATCH_SIZE = 30
# DELAY_BETWEEN_MSG = (2, 4)
# PAUSE_BETWEEN_BATCH = 60
# GLOBAL_SLEEP = 300  # barcha profillar uchun aylanib bo‘lgach 5 daqiqa dam
BATCH_SIZE = 5
DELAY_BETWEEN_MSG = (5, 10)
PAUSE_BETWEEN_BATCH = 120
GLOBAL_SLEEP = 300

async def send_message_safe(client, link, message_text, profile_id, idx, total_groups):
    try:
        entity = await client.get_entity(link)
        await client.send_message(entity, message_text)
        logger.info(f"✅ [{idx}/{total_groups}] Yuborildi: {link}")
        return True
    except FloodWaitError as e:
        logger.warning(f"⏳ FloodWait {e.seconds}s: {link}")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        logger.error(f"❌ [{idx}] {link} - Xato: {e}")
    return False



async def send_to_groups_auto(clients: list):
    """Har daqiqada 30 ta guruhga yuborib, keyingi 30tasiga o'tish."""
    while True:
        try:
            for client in clients:
                profile_id = client.profile_id
                if not bool(int(get_profile_setting(profile_id, "auto_send_enabled") or 0)):
                    continue

                message_text = get_profile_setting(profile_id, "message_text") or "📢 Avto xabar!"
                groups = load_groups(profile_id)
                total_groups = len(groups)
                if not groups:
                    continue

                logger.info(f"🚀 {client._self_id} uchun {total_groups} ta guruhga yuborish boshlandi.")

                # Guruhlarni 30 tadan bo‘lib yuborish
                for i in range(0, total_groups, BATCH_SIZE):
                    batch = groups[i:i + BATCH_SIZE]
                    logger.info(f"📦 Partiya: {i//BATCH_SIZE + 1} | {len(batch)} ta guruh yuboriladi...")

                    for j, link in enumerate(batch, start=i + 1):
                        await send_message_safe(client, link, message_text, profile_id, j, total_groups)
                        await asyncio.sleep(random.uniform(*DELAY_BETWEEN_MSG))

                    logger.info(f"😴 {PAUSE_BETWEEN_BATCH}s tanaffus (keyingi 30 ta guruh)...")
                    await asyncio.sleep(PAUSE_BETWEEN_BATCH)

                logger.info(f"✅ {client._self_id} uchun barcha {total_groups} ta guruh yuborildi.")

            logger.info(f"🌙 Barcha profillar uchun aylanib chiqildi. {GLOBAL_SLEEP}s kutish...")
            await asyncio.sleep(GLOBAL_SLEEP)

        except Exception as e:
            logger.error(f"🔥 Asosiy siklda xato: {e}")
            logger.info("♻️ 10 soniyadan keyin qayta uriniladi...")
            await asyncio.sleep(10)
