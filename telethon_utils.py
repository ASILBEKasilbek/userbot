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
    """Telegramdan mavjud guruhlar va kanallarni yuklash."""
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
from telethon.errors import ChatWriteForbiddenError, ChannelPrivateError, UserBannedInChannelError, FloodWaitError

async def send_to_groups_auto(clients: list):
    """Avtomatik ravishda guruhlarga xabar yuborish (real-time natija bilan)."""
    while True:
        for client in clients:
            profile_id = client.profile_id
            auto_send_enabled = bool(int(get_profile_setting(profile_id, "auto_send_enabled") or 0))
            if not auto_send_enabled:
                print(f"🚫 Profil {client._self_id} uchun auto_send o‘chirilgan.")
                continue

            message_text = get_profile_setting(profile_id, "message_text") or "📢 Bu avtomatik xabar!"
            messages_per_minute = int(get_profile_setting(profile_id, "messages_per_minute") or 30)
            send_interval = int(get_profile_setting(profile_id, "send_interval") or 60)
            groups = load_groups(profile_id)

            if not groups:
                print(f"⚠️ {client._self_id} uchun guruhlar topilmadi.")
                continue

            print(f"\n🚀 {client._self_id} uchun avtomatik yuborish boshlandi ({len(groups)} ta guruh)...")

            success_count = 0
            fail_count = 0
            total_groups = len(groups)

            for idx, link in enumerate(groups.copy(), start=1):
                try:
                    entity = await client.get_entity(link)
                    await client.send_message(entity, message_text)
                    print(f"✅ [{idx}/{total_groups}] {link} ga yuborildi")
                    success_count += 1
                except ChatWriteForbiddenError:
                    print(f"⚠️ [{idx}/{total_groups}] {link} yozish taqiqlangan — tekshirilmoqda...")
                    if await handle_linked_channel(client, entity, profile_id):
                        try:
                            await client.send_message(entity, message_text)
                            print(f"🔁 {link} qayta yuborildi")
                            success_count += 1
                        except Exception as e:
                            print(f"❌ {link} qayta yuborishda xato: {e}")
                            fail_count += 1
                    else:
                        await leave_group(client, entity.id, profile_id, link)
                        fail_count += 1
                except (ChannelPrivateError, UserBannedInChannelError):
                    print(f"🚫 [{idx}/{total_groups}] {link} — Maxfiy yoki ban")
                    await leave_group(client, entity.id, profile_id, link)
                    fail_count += 1
                except FloodWaitError as e:
                    print(f"⏳ [{idx}/{total_groups}] FloodWait: {e.seconds}s kutish...")
                    await asyncio.sleep(e.seconds)
                    fail_count += 1
                except Exception as e:
                    print(f"❌ [{idx}/{total_groups}] {link} - xato: {e}")
                    await leave_group(client, entity.id, profile_id, link)
                    fail_count += 1

                await asyncio.sleep(60 / messages_per_minute)

            print(f"\n📊 {client._self_id} uchun natija: {success_count} ta yuborildi, {fail_count} ta muvaffaqiyatsiz.\n")
            await asyncio.sleep(send_interval)

        await asyncio.sleep(60)
