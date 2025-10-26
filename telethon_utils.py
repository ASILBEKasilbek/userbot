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
from datetime import datetime, timedelta
from collections import defaultdict
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

 
# BATCH_SIZE = 4    
# DELAY_BETWEEN_MSG = (5, 10)  
# PAUSE_BETWEEN_BATCH = 60     
# GLOBAL_SLEEP = 300           
# FLOOD_BLOCKED = {} 

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
    from db import load_groups  # ichkarida chaqiramiz, aylanish oldini olish uchun
    existing_groups = load_groups(profile_id)

    try:
        if isinstance(entity, Channel):
            full = await client(GetFullChannelRequest(entity))
            linked_chat_id = getattr(full.full_chat, "linked_chat_id", None)

            if linked_chat_id:
                link = f"https://t.me/c/{linked_chat_id}"
                if link in existing_groups:
                    logger.warning(f"⚠️ {client._self_id} kanal allaqachon bazada bor: {link}, qayta qo‘shilmaydi.")
                    return False

                try:
                    linked_channel = await client.get_entity(linked_chat_id)
                    await client(JoinChannelRequest(linked_channel))
                    save_group(link, profile_id)
                    logger.info(f"📡 {client._self_id} kanalga avtomatik qo‘shildi: {linked_channel.title}")
                    return True
                except Exception as e:
                    logger.warning(f"❌ Kanalga qo‘shila olmadi: {e}")
                    return False

            # Agar linked_chat_id topilmasa, invite link orqali urinish
            invite_link = getattr(full.full_chat, "exported_invite", None)
            if invite_link and hasattr(invite_link, "link"):
                if invite_link.link in existing_groups:
                    logger.warning(f"⚠️ {client._self_id} kanal allaqachon bazada bor: {invite_link.link}")
                    return False
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


# Tunable parametrlar (defaultlarni o'zgartiring)
DELAY_BETWEEN_MSG = (6, 12)      # har xabar orasidagi random sekundlar (biroz kattaroq)
BATCH_SIZE = 6
PAUSE_BETWEEN_BATCH = 200        # har batch dan keyin tanaffus (sekund)
GLOBAL_SLEEP = 900               # barcha profillar aylanmasi (sekund)
MESSAGES_PER_MINUTE = 6          # xavfsiz minimal limit (profil holatiga qarab kamaytiring)
FLOOD_BLOCKED = {}              # profile_id -> unblock datetime
# Cache va profiling state
_entity_cache = {}               # link -> entity obyekti
_profile_send_history = defaultdict(list)  # profile_id -> list of send timestamps (datetime)
_profile_backoff = {}            # profile_id -> seconds to wait (adaptive backoff)

# Helper: entity cache olish
async def get_entity_cached(client: TelegramClient, link: str):
    key = f"{client._self_id}:{link}"
    if key in _entity_cache:
        return _entity_cache[key]
    entity = await client.get_entity(link)
    _entity_cache[key] = entity
    return entity

# Helper: xabarni ozgina variatsiya qilish
def make_variation(message_text: str) -> str:
    # kichik random id va emoji qo'shish — aynan bir xil matn yuborilmasligi uchun
    suffix = f" · id{random.randint(1000,9999)}"
    # ba'zida emoji qo'shamiz, ba'zida belgi
    extras = ["", " ✅", " ✨", " 🔔", " 📌"]
    return f"{message_text}{random.choice(extras)}{suffix}"

# Helper: messages_per_minute limitni tekshirish
def can_send_now(profile_id: int) -> bool:
    now = datetime.now()
    window_start = now - timedelta(minutes=1)
    # filter eski timestamplarni olib tashlash
    _profile_send_history[profile_id] = [t for t in _profile_send_history[profile_id] if t > window_start]
    return len(_profile_send_history[profile_id]) < MESSAGES_PER_MINUTE

# Yaxshilangan send_message_safe



async def send_message_safe(client: TelegramClient, link: str, message_text: str, profile_id: int, idx: int, total: int) -> bool:
    """Adaptive flood himoya bilan yuborish."""
    try:
        # Agar profilga backoff qo'yilgan bo'lsa — tekshirib o'tamiz
        if profile_id in _profile_backoff:
            unblock_time = _profile_backoff[profile_id]
            if datetime.now() < unblock_time:
                remaining = (unblock_time - datetime.now()).seconds
                logger.info(f"⏸️ Profil {profile_id} blocklangan, {remaining}s qoldi: {link}")
                return False
            else:
                del _profile_backoff[profile_id]

        # messages_per_minute tekshiruvi
        if not can_send_now(profile_id):
            # Agar bu limitdan oshib ketgan bo'lsa — profilni qisqa backoffga qo'yamiz
            backoff = timedelta(seconds=60 + random.randint(20, 60))
            _profile_backoff[profile_id] = datetime.now() + backoff
            logger.warning(f"🚫 {client._self_id} uchun rate limit (messages_per_minute) bosildi. {backoff.seconds}s block.")
            return False

        # entity ni cache orqali oling
        entity = await get_entity_cached(client, link)
        # Send with slight variation
        final_text = make_variation(message_text)
        await client.send_message(entity, final_text)
        # record timestamp for rate limiting
        _profile_send_history[profile_id].append(datetime.now())

        logger.info(f"✅ [{idx}/{total}] Yuborildi: {link}")
        return True

    except FloodWaitError as e:
        # Telegram aytgan seconds ga mos holda profilni block qilamiz
        unblock_time = datetime.now() + timedelta(seconds=e.seconds + 5)
        _profile_backoff[profile_id] = unblock_time
        # logging uchun adaptive profiling
        logger.warning(f"🚨 FLOOD ({client._self_id}) - wait {e.seconds}s => profil blocklandi until {unblock_time}")
        return False

    except ChatWriteForbiddenError:
        logger.warning(f"🚫 Yozish taqiqlangan: {link}")
        return False
    except (UserBannedInChannelError, ChannelPrivateError):
        logger.warning(f"🚫 Guruhdan o‘chirilmoqda yoki private: {link}")
        remove_group(link, profile_id)
        # clear cache for this link
        key = f"{client._self_id}:{link}"
        _entity_cache.pop(key, None)
        return False
    except Exception as e:
        logger.error(f"❌ [{idx}] {link} - {e}")
        return False

# Yaxshilangan send_profile_messages (batch + pausa + tekshiruvlar)
async def send_profile_messages(client: TelegramClient):
    profile_id = client.profile_id

    # FLOOD_BLOCKED (sizning mavjud) bilan ham moslash
    if profile_id in FLOOD_BLOCKED:
        if datetime.now() < FLOOD_BLOCKED[profile_id]:
            remaining = (FLOOD_BLOCKED[profile_id] - datetime.now()).seconds
            logger.info(f"⏸️ {client._self_id} Flood kutmoqda ({remaining}s qoldi)...")
            return
        else:
            del FLOOD_BLOCKED[profile_id]

    if not bool(int(get_profile_setting(profile_id, "auto_send_enabled") or 0)):
        logger.info(f"⏸️ {client._self_id} uchun avto yuborish o‘chirilgan.")
        return

    message_text = get_profile_setting(profile_id, "message_text") or "📢 Avto xabar!"
    groups = load_groups(profile_id)
    total_groups = len(groups)

    if not groups:
        logger.info(f"📂 {client._self_id} uchun guruhlar topilmadi.")
        return

    logger.info(f"🚀 {client._self_id} uchun {total_groups} ta guruhga yuborish boshlandi.")

    for i, link in enumerate(groups, start=1):
        # Agar profilda adaptive backoff bo'lsa, chiqarib ketamiz
        if profile_id in _profile_backoff and datetime.now() < _profile_backoff[profile_id]:
            logger.info(f"⏸️ {_profile_backoff[profile_id]}gacha profil blocklandi, to'xtatildi.")
            break

        ok = await send_message_safe(client, link, message_text, profile_id, i, total_groups)

        # agar yuborilgan bo'lsa yoki yo'q bo'lsa ham, small delay lekin adaptiv
        # agar muvaffaqiyatsiz va profil block bo'lsa, to'xtatamiz
        await asyncio.sleep(random.uniform(*DELAY_BETWEEN_MSG))

        if not ok:
            # Agar profil adaptive backoff o'rnatilgan bo'lsa — chiqamiz
            if profile_id in _profile_backoff:
                logger.info(f"⚠️ {client._self_id} flood/limit tufayli to'xtatildi.")
                break

        # Batch pauza qo'llash
        if i % BATCH_SIZE == 0 and i != total_groups:
            pause = PAUSE_BETWEEN_BATCH + random.randint(0, 40)
            logger.info(f"🛌 Batch tugadi ({i}/{total_groups}). Pauza {pause}s...")
            await asyncio.sleep(pause)

    logger.info(f"✅ {client._self_id} uchun yuborish yakunlandi.")

# Yaxshilangan send_to_groups_auto: profiling va staggered profiling
async def send_to_groups_auto(clients: list):
    """Barcha profillar parallel ravishda guruhlarga xabar yuborish.
       Qo'shimcha: profilni stagger (boshqa profilga birma-bir) tarzda boshlash."""
    # boshida har bir profilda kichik staggers qo'yamiz
    for idx, c in enumerate(clients):
        await asyncio.sleep(random.uniform(1, 3))  # kichik stagger

    while True:
        try:
            # Staggered start: har bir profilni alohida kechiktirish bilan ishga tushurish mumkin
            tasks = []
            for client in clients:
                # agar profil bloklangan bo'lsa, boshqasiga o'tish
                pid = client.profile_id
                if pid in _profile_backoff and datetime.now() < _profile_backoff[pid]:
                    logger.info(f"⏭️ {client._self_id} blocklangan, o'tkazildi.")
                    continue
                tasks.append(send_profile_messages(client))

            if tasks:
                await asyncio.gather(*tasks)

            logger.info(f"🌙 Barcha profillar aylanib chiqdi. {GLOBAL_SLEEP}s kutish...")
            await asyncio.sleep(GLOBAL_SLEEP + random.randint(0, 120))
        except Exception as e:
            logger.error(f"🔥 Asosiy siklda xato: {e}")
            wait_time = random.randint(20, 60)
            logger.info(f"♻️ {wait_time}s keyin qayta uriniladi...")
            await asyncio.sleep(wait_time)

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