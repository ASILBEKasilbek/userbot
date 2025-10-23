import asyncio
import random
import logging
from telethon import TelegramClient, events
from telethon.errors import (
    ChatWriteForbiddenError,
    ChannelPrivateError,
    FloodWaitError,
    UserBannedInChannelError,
)
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest, GetFullChannelRequest
from telethon.tl.types import Channel
from db import load_groups, save_group, remove_group, get_profile_setting

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Optimal sozlamalar
BATCH_SIZE = 10         # Har batchdagi guruhlar soni
DELAY_BETWEEN_MSG = (5, 10)  # Xabar orasidagi random kutish (sekundlarda)
PAUSE_BETWEEN_BATCH = 60     # Batchdan keyin tanaffus (sekundlarda)
GLOBAL_SLEEP = 300           # Barcha profillar bir siklni tugatgandan keyin kutish (sekundlarda)

async def auto_reply_handler(event):
    """Shaxsiy xabarlarga avtomatik javob berish."""
    profile_id = event.client.profile_id
    auto_reply_enabled = bool(int(get_profile_setting(profile_id, "auto_reply_enabled") or 0))
    auto_reply_text = get_profile_setting(profile_id, "auto_reply_text") or "Salom! Bu avtomatik javob."
    if event.is_private and auto_reply_enabled:
        try:
            await event.reply(auto_reply_text)
            logger.info(f"📩 {event.client._self_id} shaxsiy xabarga avto javob yubordi.")
        except Exception as e:
            logger.error(f"❌ Avto javob yuborishda xato: {e}")

async def response_reply_handler(event):
    """Guruhlarda foydalanuvchi nomiga javob berish."""
    profile_id = event.client.profile_id
    response_reply_enabled = bool(int(get_profile_setting(profile_id, "response_reply_enabled") or 0))
    response_reply_text = get_profile_setting(profile_id, "response_reply_text") or "Avto javob guruhda."
    if not event.is_private and response_reply_enabled:
        try:
            me = await event.client.get_me()
            if me.username and f"@{me.username}" in event.raw_text:
                await event.reply(response_reply_text)
                logger.info(f"📢 {event.client._self_id} guruhda @{me.username} ga javob berdi.")
        except Exception as e:
            logger.error(f"❌ Guruh avto javobida xato: {e}")

async def join_group(client: TelegramClient, link: str, profile_id: int) -> bool:
    """Guruhga qo‘shilish va uni ma'lumotlar bazasiga saqlash."""
    try:
        entity = await client.get_entity(link)
        await client(JoinChannelRequest(entity))
        save_group(link, profile_id)
        logger.info(f"✅ {client._self_id} guruhga qo‘shildi: {link}")
        return True
    except FloodWaitError as e:
        logger.warning(f"⏳ FloodWait {e.seconds}s qo‘shilishda: {link}")
        await asyncio.sleep(e.seconds + 1)
        return await join_group(client, link, profile_id)  # Qayta urinish
    except Exception as e:
        logger.error(f"❌ {client._self_id} guruhga qo‘shilishda xato: {link} - {e}")
        return False

async def leave_group(client: TelegramClient, group_id: int, profile_id: int, link: str):
    """Guruhdan chiqish va uni ma'lumotlar bazasidan o‘chirish."""
    try:
        await client(LeaveChannelRequest(group_id))
        remove_group(link, profile_id)
        logger.info(f"🚪 {client._self_id} guruhdan chiqildi va DBdan o‘chirildi: {link}")
    except Exception as e:
        logger.error(f"❌ {client._self_id} guruhdan chiqishda xato: {link} - {e}")
        remove_group(link, profile_id)  # Xato bo‘lsa ham DBdan o‘chirish

async def try_join_linked_channel(client: TelegramClient, entity, profile_id: int) -> bool:
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
                    save_group(f"https://t.me/c/{linked_chat_id}", profile_id)
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
                    save_group(invite_link.link, profile_id)
                    logger.info(f"📡 {client._self_id} havola orqali kanalga qo‘shildi: {invite_link.link}")
                    return True
                except Exception as e:
                    logger.warning(f"❌ Havola orqali kanalga qo‘shila olmadi: {e}")
                    return False
    except Exception as e:
        logger.error(f"🔍 Bog‘langan kanalni aniqlashda xato: {e}")
    return False

async def load_existing_groups(client: TelegramClient, profile_id: int):
    """Mavjud guruhlarni yuklash va ma'lumotlar bazasiga saqlash."""
    try:
        dialogs = await client.get_dialogs()
        for d in dialogs:
            if isinstance(d.entity, Channel) and (d.entity.broadcast or d.entity.megagroup):
                try:
                    entity = d.entity
                    link = f"https://t.me/{entity.username}" if entity.username else f"https://t.me/c/{entity.id}"
                    save_group(link, profile_id)
                    logger.info(f"✅ {client._self_id} guruh yuklandi: {link}")
                except Exception as e:
                    logger.error(f"❌ Guruh linkini olishda xato: {e}")
    except Exception as e:
        logger.error(f"❌ {client._self_id} mavjud guruhlarni yuklashda xato: {e}")

async def send_message_safe(client: TelegramClient, link: str, message_text: str, profile_id: int, idx: int, total: int) -> bool:
    """Xavfsiz xabar yuborish, ban yoki taqiqlardan chiqish."""
    try:
        entity = await client.get_entity(link)
        await client.send_message(entity, message_text)
        logger.info(f"✅ [{idx}/{total}] Yuborildi: {link}")
        return True
    except FloodWaitError as e:
        logger.warning(f"⏳ FloodWait {e.seconds}s: {link}")
        await asyncio.sleep(e.seconds + 1)
        return await send_message_safe(client, link, message_text, profile_id, idx, total)  # Qayta urinish
    except ChatWriteForbiddenError as e:
        logger.warning(f"🚫 Yozish taqiqlangan: {link}. Bog'langan kanalga qo'shilish urinilmoqda...")
        if await try_join_linked_channel(client, entity, profile_id):
            return await send_message_safe(client, link, message_text, profile_id, idx, total)  # Qayta urinish
        else:
            logger.error(f"❌ Kanalga qo'shila olmadi, guruhdan chiqilmoqda: {link}")
            await leave_group(client, entity.id, profile_id, link)
            return False
    except UserBannedInChannelError as e:
        logger.error(f"🚫 Foydalanuvchi band qilingan: {link}. Guruhdan chiqarilmoqda...")
        await leave_group(client, entity.id, profile_id, link)
        return False
    except ChannelPrivateError as e:
        logger.error(f"🔒 Shaxsiy kanal: {link}. Guruhdan o'chirilmoqda...")
        remove_group(link, profile_id)
        return False
    except Exception as e:
        logger.error(f"❌ [{idx}] {link} - Xato: {e}")
        error_text = str(e).lower()

        # Agar guruh o‘chgan, private yoki topilmasa — o‘chirish
        if any(k in error_text for k in ["banned", "forbidden", "private", "cannot find any entity"]):
            logger.warning(f"🚫 Guruh mavjud emas yoki yopilgan: {link}. Bazadan o‘chirilmoqda...")
            try:
                await leave_group(client, entity.id if 'entity' in locals() else 0, profile_id, link)
            except Exception:
                remove_group(link, profile_id)
        return False


async def send_profile_messages(client: TelegramClient):
    """Bitta profil uchun guruhlarga xabar yuborish."""
    profile_id = client.profile_id
    if not bool(int(get_profile_setting(profile_id, "auto_send_enabled") or 0)):
        logger.info(f"⏸️ {client._self_id} uchun avto yuborish o'chirilgan.")
        return

    message_text = get_profile_setting(profile_id, "message_text") or "📢 Avto xabar!"
    groups = load_groups(profile_id)
    total_groups = len(groups)
    if not groups:
        logger.info(f"📂 {client._self_id} uchun guruhlar topilmadi.")
        return

    logger.info(f"🚀 {client._self_id} uchun {total_groups} ta guruhga yuborish boshlandi.")

    for i in range(0, total_groups, BATCH_SIZE):
        batch = groups[i:i + BATCH_SIZE]
        logger.info(f"📦 Partiya: {i//BATCH_SIZE + 1} | {len(batch)} ta guruh yuboriladi...")
        for j, link in enumerate(batch, start=i + 1):
            await send_message_safe(client, link, message_text, profile_id, j, total_groups)
            await asyncio.sleep(random.uniform(*DELAY_BETWEEN_MSG))

        if i + BATCH_SIZE < total_groups:  # Oxirgi batchdan keyin pause qilmaslik
            logger.info(f"😴 {PAUSE_BETWEEN_BATCH}s tanaffus (keyingi batch)...")
            await asyncio.sleep(PAUSE_BETWEEN_BATCH)

    logger.info(f"✅ {client._self_id} uchun barcha guruhlar yuborildi.")

async def send_to_groups_auto(clients: list):
    """Barcha profillar parallel ravishda guruhlarga xabar yuborish."""
    while True:
        try:
            tasks = [send_profile_messages(client) for client in clients]
            await asyncio.gather(*tasks)
            logger.info(f"🌙 Barcha profillar aylanib chiqdi. {GLOBAL_SLEEP}s kutish...")
            await asyncio.sleep(GLOBAL_SLEEP)
        except Exception as e:
            logger.error(f"🔥 Asosiy siklda xato: {e}")
            logger.info("♻️ 10 soniyadan keyin qayta uriniladi...")
            await asyncio.sleep(10)