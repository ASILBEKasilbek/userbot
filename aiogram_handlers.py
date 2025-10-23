import logging
from functools import wraps
from aiogram import Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneNumberInvalidError, ApiIdInvalidError
from telethon.tl.functions.auth import SendCodeRequest
from config import ADMIN_ID
from db import load_profiles, save_profile, remove_profile, load_groups, get_profile_setting, update_profile_setting
from states import SettingsForm, ProfileForm, MainForm
from telethon_utils import auto_reply_handler, response_reply_handler, load_existing_groups
from constants import MESSAGES, MAIN_MENU_BUTTONS, PROFILE_MENU_BUTTONS, DELETE_CONFIRM_BUTTONS
from keyboards import get_main_keyboard, get_profile_keyboard, get_profile_selection_keyboard, get_delete_confirm_keyboard
from telethon.errors import SessionPasswordNeededError, PhoneNumberInvalidError, ApiIdInvalidError
from telethon import events
from telethon_utils import load_existing_groups
from db import save_profile, remove_profile,save_group
from telethon.tl.functions.channels import JoinChannelRequest


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

dp = Dispatcher()
clients = []

def admin_only(handler):
    @wraps(handler)
    async def wrapper(message: types.Message, *args, **kwargs):
        if message.from_user.id != int(ADMIN_ID):
            await message.answer(MESSAGES["NO_PERMISSION"])
            return
        return await handler(message, *args, **kwargs)
    return wrapper

def handle_errors(handler):
    @wraps(handler)
    async def wrapper(message: types.Message, state: FSMContext, *args, **kwargs):
        try:
            return await handler(message, state, *args, **kwargs)
        except PhoneNumberInvalidError:
            await message.answer(MESSAGES["INVALID_PHONE"])
            await state.clear()
        except ApiIdInvalidError:
            await message.answer(MESSAGES["INVALID_API_ID"])
            await state.clear()
        except SessionPasswordNeededError:
            await state.update_data(client=kwargs.get('client') or (await state.get_data()).get('client'))
            await state.set_state(ProfileForm.waiting_for_password)
            await message.answer("🔐 2FA parolni yuboring:")
        except Exception as e:
            logger.error(f"Xato yuz berdi: {e}")
            await message.answer(f"❌ Xato yuz berdi: {str(e)}. Iltimos, qaytadan urinib ko‘ring.")
            await state.clear()
    return wrapper

@dp.message(Command("start"))
@admin_only
async def start_cmd(message: types.Message, state: FSMContext):
    await state.set_state(MainForm.main_menu)
    await message.answer(MESSAGES["WELCOME"], reply_markup=get_main_keyboard())

@dp.message(MainForm.main_menu, F.text == MAIN_MENU_BUTTONS["ADD_PROFILE"])
@admin_only
async def add_profile_start(message: types.Message, state: FSMContext):
    await state.set_state(ProfileForm.waiting_for_api_id)
    await message.answer("🔢 API ID ni yuboring (my.telegram.org dan oling):")

@dp.message(ProfileForm.waiting_for_api_id)
@admin_only
async def process_api_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer(MESSAGES["INVALID_API_ID"])
        return
    await state.update_data(api_id=int(message.text))
    await state.set_state(ProfileForm.waiting_for_api_hash)
    await message.answer("🔑 API HASH ni yuboring (my.telegram.org dan oling):")

@dp.message(ProfileForm.waiting_for_api_hash)
@admin_only
async def process_api_hash(message: types.Message, state: FSMContext):
    api_hash = message.text.strip()
    if not api_hash:
        await message.answer(MESSAGES["INVALID_API_HASH"])
        return
    await state.update_data(api_hash=api_hash)
    await state.set_state(ProfileForm.waiting_for_phone)
    await message.answer(MESSAGES["INVALID_PHONE"])

@dp.message(ProfileForm.waiting_for_phone)
@admin_only
@handle_errors
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    if not phone.startswith('+') or not phone[1:].isdigit():
        await message.answer(MESSAGES["INVALID_PHONE"])
        return
    data = await state.get_data()
    api_id = data['api_id']
    api_hash = data['api_hash']
    session_name = f"session_{phone[1:]}"
    client = TelegramClient(session_name, api_id, api_hash)
    await client.connect()
    sent_code = await client.send_code_request(phone)
    await state.update_data(client=client, session_name=session_name, code_hash=sent_code.phone_code_hash, phone=phone)
    await state.set_state(ProfileForm.waiting_for_code)
    await message.answer("🔢 Telegramdan kelgan tasdiqlash kodini yuboring:")

@dp.message(ProfileForm.waiting_for_code)
@admin_only
@handle_errors
async def process_code(message: types.Message, state: FSMContext):
    data = await state.get_data()
    client = data.get('client')
    phone = data.get('phone')
    code_hash = data.get('code_hash')
    code = message.text.strip()
    if not code.isdigit():
        await message.answer(MESSAGES["INVALID_CODE"])
        return
    await client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
    api_id = data.get('api_id')
    api_hash = data.get('api_hash')
    session_name = data.get('session_name')
    profile_id = save_profile(api_id, api_hash, phone, session_name)
    if profile_id is None:
        await client.disconnect()
        await message.answer("❌ Profil saqlanmadi. Ma'lumotlar bazasi bilan muammo yuz berdi.")
        await state.clear()
        return
    client.profile_id = profile_id
    client.add_event_handler(auto_reply_handler, events.NewMessage(incoming=True))
    client.add_event_handler(response_reply_handler, events.NewMessage(incoming=True, pattern=r'(?i)@[\w\d_]+'))
    await load_existing_groups(client, profile_id)
    clients.append(client)
    await message.answer(MESSAGES["PROFILE_ADDED"].format(phone=phone))
    await state.set_state(MainForm.main_menu)
    await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())

@dp.message(ProfileForm.waiting_for_password)
@admin_only
@handle_errors
async def process_password(message: types.Message, state: FSMContext):
    data = await state.get_data()
    client = data.get('client')
    phone = data.get('phone')
    session_name = data.get('session_name')
    api_id = data.get('api_id')
    api_hash = data.get('api_hash')
    password = message.text.strip()
    await client.sign_in(password=password)
    profile_id = save_profile(api_id, api_hash, phone, session_name)
    if profile_id is None:
        await client.disconnect()
        await message.answer("❌ Profil saqlanmadi. Ma'lumotlar bazasi bilan muammo yuz berdi.")
        await state.clear()
        return
    client.profile_id = profile_id
    client.add_event_handler(auto_reply_handler, events.NewMessage(incoming=True))
    client.add_event_handler(response_reply_handler, events.NewMessage(incoming=True, pattern=r'(?i)@[\w\d_]+'))
    await load_existing_groups(client, profile_id)
    clients.append(client)
    await message.answer(MESSAGES["PROFILE_ADDED"].format(phone=phone))
    await state.set_state(MainForm.main_menu)
    await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())

@dp.message(MainForm.main_menu, F.text == MAIN_MENU_BUTTONS["LIST_PROFILES"])
@admin_only
async def show_profiles(message: types.Message, state: FSMContext):
    profiles = load_profiles()
    if not profiles:
        await message.answer(MESSAGES["NO_PROFILES"])
        return
    await state.set_state(MainForm.profile_menu)
    await message.answer("📱 Profilni tanlang:", reply_markup=get_profile_selection_keyboard(profiles))

@dp.message(MainForm.profile_menu, F.text.regexp(r'\+998\d{9}'))
@admin_only
async def select_profile(message: types.Message, state: FSMContext):
    profiles = load_profiles()
    phone = message.text.strip()
    selected = next((p for p in profiles if p['phone'] == phone), None)
    if not selected:
        await message.answer(MESSAGES["PROFILE_NOT_FOUND"].format(phone=phone))
        return
    await state.update_data(current_profile_id=selected['id'], current_phone=phone)
    await state.set_state(MainForm.profile_menu)
    await message.answer(f"📱 {phone} profili tanlandi.", reply_markup=get_profile_keyboard())

@dp.message(MainForm.profile_menu, F.text == PROFILE_MENU_BUTTONS["DELETE_PROFILE"])
@admin_only
async def delete_profile_start(message: types.Message, state: FSMContext):
    data = await state.get_data()
    phone = data.get('current_phone')
    if not phone:
        await message.answer("❌ Profil tanlanmagan. Iltimos, avval profil tanlang.")
        await state.set_state(MainForm.main_menu)
        await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())
        return
    await state.set_state(MainForm.waiting_for_profile_delete)
    await message.answer(MESSAGES["CONFIRM_DELETE"].format(phone=phone), reply_markup=get_delete_confirm_keyboard())

@dp.message(MainForm.waiting_for_profile_delete, F.text == DELETE_CONFIRM_BUTTONS["CONFIRM_YES"])
@admin_only
async def process_delete_profile(message: types.Message, state: FSMContext):
    data = await state.get_data()
    profile_id = data.get('current_profile_id')
    phone = data.get('current_phone')
    if not profile_id:
        await message.answer("❌ Profil tanlanmagan. Iltimos, avval profil tanlang.")
        await state.set_state(MainForm.main_menu)
        await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())
        return
    client = next((c for c in clients if c.profile_id == profile_id), None)
    if client:
        try:
            await client.disconnect()
            clients.remove(client)
        except Exception as e:
            logger.error(f"Profilni o'chirishda ulanishni uzishda xato: {e}")
    remove_profile(profile_id)
    await message.answer(MESSAGES["PROFILE_DELETED"].format(phone=phone))
    await state.set_state(MainForm.main_menu)
    await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())

@dp.message(MainForm.waiting_for_profile_delete, F.text == DELETE_CONFIRM_BUTTONS["CONFIRM_NO"])
@admin_only
async def cancel_delete_profile(message: types.Message, state: FSMContext):
    await state.set_state(MainForm.profile_menu)
    await message.answer("📱 Profil menyusiga qaytdingiz.", reply_markup=get_profile_keyboard())

@dp.message(MainForm.profile_menu, F.text == PROFILE_MENU_BUTTONS["ADD_GROUP"])
@admin_only
async def ask_group_link(message: types.Message, state: FSMContext):
    data = await state.get_data()
    profile_id = data.get('current_profile_id')
    if not profile_id:
        await message.answer("❌ Profil tanlanmagan. Iltimos, avval profil tanlang.")
        await state.set_state(MainForm.main_menu)
        await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())
        return
    await message.answer("🔗 Guruh linklarini yuboring (har birini yangi qatorda, masalan: https://t.me/groupname):")

@dp.message(MainForm.profile_menu, F.text.contains("https://t.me/"))
@admin_only
async def add_groups(message: types.Message, state: FSMContext):
    data = await state.get_data()
    profile_id = data.get('current_profile_id')
    if not profile_id:
        await message.answer("❌ Profil tanlanmagan. Iltimos, avval profil tanlang.")
        await state.set_state(MainForm.main_menu)
        await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())
        return
    client = next((c for c in clients if c.profile_id == profile_id), None)
    if not client:
        await message.answer("❌ Tanlangan profil uchun ulanish topilmadi.")
        return
    links = [line.strip() for line in message.text.splitlines() if "https://t.me/" in line]
    groups = load_groups(profile_id)
    added = 0
    for link in links:
        if link not in groups:
            try:
                entity = await client.get_entity(link)
                await client(JoinChannelRequest(entity))
                save_group(link, profile_id)
                await client.send_message(entity, get_profile_setting(profile_id, "message_text"))
                added += 1
            except Exception as e:
                logger.error(f"Guruh qo‘shishda xato: {link} - {e}")
    await message.answer(MESSAGES["GROUPS_ADDED"].format(count=added, total=len(load_groups(profile_id))))
    await message.answer("📱 Profil menyusiga qaytdingiz.", reply_markup=get_profile_keyboard())

@dp.message(MainForm.profile_menu, F.text == PROFILE_MENU_BUTTONS["LIST_GROUPS"])
@admin_only
async def show_groups(message: types.Message, state: FSMContext):
    data = await state.get_data()
    profile_id = data.get('current_profile_id')
    if not profile_id:
        await message.answer("❌ Profil tanlanmagan. Iltimos, avval profil tanlang.")
        await state.set_state(MainForm.main_menu)
        await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())
        return
    groups = load_groups(profile_id)
    if not groups:
        await message.answer(MESSAGES["NO_GROUPS"])
    else:
        text = "\n".join([f"{i+1}. {g}" for i, g in enumerate(groups)])
        await message.answer(f"📋 Guruhlar:\n{text}")
    await message.answer("📱 Profil menyusiga qaytdingiz.", reply_markup=get_profile_keyboard())

@dp.message(MainForm.profile_menu, F.text == PROFILE_MENU_BUTTONS["PROFILE_INFO"])
@admin_only
async def profile_info(message: types.Message, state: FSMContext):
    data = await state.get_data()
    profile_id = data.get('current_profile_id')
    phone = data.get('current_phone')
    if not profile_id:
        await message.answer("❌ Profil tanlanmagan. Iltimos, avval profil tanlang.")
        await state.set_state(MainForm.main_menu)
        await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())
        return
    profiles = load_profiles()
    selected = next((p for p in profiles if p['id'] == profile_id), None)
    if not selected:
        await message.answer(MESSAGES["PROFILE_NOT_FOUND"].format(phone=phone))
        return
    groups_count = len(load_groups(profile_id))
    info = (
        f"📱 Profil: {phone}\n"
        f"🔢 API ID: {selected['api_id']}\n"
        f"📊 Guruhlar soni: {groups_count}\n"
        f"🔄 Avto javob: {'Faol' if bool(int(get_profile_setting(profile_id, 'auto_reply_enabled'))) else 'O‘chirilgan'}\n"
        f"📝 Avto javob matni: {get_profile_setting(profile_id, 'auto_reply_text')}\n"
        f"🔄 Guruh avto javobi: {'Faol' if bool(int(get_profile_setting(profile_id, 'response_reply_enabled'))) else 'O‘chirilgan'}\n"
        f"📝 Guruh avto javob matni: {get_profile_setting(profile_id, 'response_reply_text')}\n"
        f"✉ Yuboriladigan xabar: {get_profile_setting(profile_id, 'message_text')}\n"
        f"⏱ 1 daqiqada guruhlar: {get_profile_setting(profile_id, 'messages_per_minute')}\n"
        f"⏰ Yuborish oralig'i: {int(get_profile_setting(profile_id, 'send_interval')) // 60} daqiqa\n"
        f"🚀 Avtomatik yuborish: {'Faol' if bool(int(get_profile_setting(profile_id, 'auto_send_enabled'))) else 'O‘chirilgan'}"
    )
    await message.answer(info, reply_markup=get_profile_keyboard())

@dp.message(MainForm.profile_menu, F.text == PROFILE_MENU_BUTTONS["CHANGE_AUTO_REPLY_TEXT"])
@admin_only
async def change_auto_reply_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    profile_id = data.get('current_profile_id')
    if not profile_id:
        await message.answer("❌ Profil tanlanmagan. Iltimos, avval profil tanlang.")
        await state.set_state(MainForm.main_menu)
        await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())
        return
    await state.set_state(SettingsForm.waiting_for_auto_reply_text)
    await message.answer("📝 Yangi avto javob matnini yuboring:")

@dp.message(SettingsForm.waiting_for_auto_reply_text)
@admin_only
async def process_auto_reply_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    profile_id = data.get('current_profile_id')
    if not profile_id:
        await message.answer("❌ Profil tanlanmagan. Iltimos, avval profil tanlang.")
        await state.set_state(MainForm.main_menu)
        await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())
        return
    text = message.text.strip()
    if not text:
        await message.answer(MESSAGES["INVALID_TEXT"])
        return
    update_profile_setting(profile_id, "auto_reply_text", text)
    await message.answer(MESSAGES["TEXT_UPDATED"].format(type="Avto javob matni", text=text))
    await state.set_state(MainForm.profile_menu)
    await message.answer("📱 Profil menyusiga qaytdingiz.", reply_markup=get_profile_keyboard())

@dp.message(MainForm.profile_menu, F.text == PROFILE_MENU_BUTTONS["TOGGLE_AUTO_REPLY"])
@admin_only
async def toggle_auto_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    profile_id = data.get('current_profile_id')
    if not profile_id:
        await message.answer("❌ Profil tanlanmagan. Iltimos, avval profil tanlang.")
        await state.set_state(MainForm.main_menu)
        await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())
        return
    auto_reply_enabled = bool(int(get_profile_setting(profile_id, "auto_reply_enabled") or 0))
    auto_reply_enabled = not auto_reply_enabled
    update_profile_setting(profile_id, "auto_reply_enabled", "1" if auto_reply_enabled else "0")
    status = "yoqildi" if auto_reply_enabled else "o‘chirildi"
    await message.answer(MESSAGES["AUTO_REPLY_TOGGLED"].format(status=status), reply_markup=get_profile_keyboard())

@dp.message(MainForm.profile_menu, F.text == PROFILE_MENU_BUTTONS["CHANGE_RESPONSE_REPLY_TEXT"])
@admin_only
async def change_response_reply_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    profile_id = data.get('current_profile_id')
    if not profile_id:
        await message.answer("❌ Profil tanlanmagan. Iltimos, avval profil tanlang.")
        await state.set_state(MainForm.main_menu)
        await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())
        return
    await state.set_state(SettingsForm.waiting_for_response_reply_text)
    await message.answer("📝 Yangi guruh avto javob matnini yuboring:")

@dp.message(SettingsForm.waiting_for_response_reply_text)
@admin_only
async def process_response_reply_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    profile_id = data.get('current_profile_id')
    if not profile_id:
        await message.answer("❌ Profil tanlanmagan. Iltimos, avval profil tanlang.")
        await state.set_state(MainForm.main_menu)
        await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())
        return
    text = message.text.strip()
    if not text:
        await message.answer(MESSAGES["INVALID_TEXT"])
        return
    update_profile_setting(profile_id, "response_reply_text", text)
    await message.answer(MESSAGES["TEXT_UPDATED"].format(type="Guruh avto javob matni", text=text))
    await state.set_state(MainForm.profile_menu)
    await message.answer("📱 Profil menyusiga qaytdingiz.", reply_markup=get_profile_keyboard())

@dp.message(MainForm.profile_menu, F.text == PROFILE_MENU_BUTTONS["TOGGLE_RESPONSE_REPLY"])
@admin_only
async def toggle_response_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    profile_id = data.get('current_profile_id')
    if not profile_id:
        await message.answer("❌ Profil tanlanmagan. Iltimos, avval profil tanlang.")
        await state.set_state(MainForm.main_menu)
        await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())
        return
    response_reply_enabled = bool(int(get_profile_setting(profile_id, "response_reply_enabled") or 0))
    response_reply_enabled = not response_reply_enabled
    update_profile_setting(profile_id, "response_reply_enabled", "1" if response_reply_enabled else "0")
    status = "yoqildi" if response_reply_enabled else "o‘chirildi"
    await message.answer(MESSAGES["RESPONSE_REPLY_TOGGLED"].format(status=status), reply_markup=get_profile_keyboard())

@dp.message(MainForm.profile_menu, F.text == PROFILE_MENU_BUTTONS["MESSAGE_TEXT"])
@admin_only
async def change_message_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    profile_id = data.get('current_profile_id')
    if not profile_id:
        await message.answer("❌ Profil tanlanmagan. Iltimos, avval profil tanlang.")
        await state.set_state(MainForm.main_menu)
        await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())
        return
    await state.set_state(SettingsForm.waiting_for_message_text)
    await message.answer("📝 Yangi yuboriladigan xabar matnini yuboring:")

@dp.message(SettingsForm.waiting_for_message_text)
@admin_only
async def process_message_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    profile_id = data.get('current_profile_id')
    if not profile_id:
        await message.answer("❌ Profil tanlanmagan. Iltimos, avval profil tanlang.")
        await state.set_state(MainForm.main_menu)
        await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())
        return
    text = message.text.strip()
    if not text:
        await message.answer(MESSAGES["INVALID_TEXT"])
        return
    update_profile_setting(profile_id, "message_text", text)
    await message.answer(MESSAGES["TEXT_UPDATED"].format(type="Yuboriladigan xabar", text=text))
    await state.set_state(MainForm.profile_menu)
    await message.answer("📱 Profil menyusiga qaytdingiz.", reply_markup=get_profile_keyboard())

@dp.message(MainForm.profile_menu, F.text == PROFILE_MENU_BUTTONS["TOGGLE_AUTO_SEND"])
@admin_only
async def toggle_auto_send(message: types.Message, state: FSMContext):
    data = await state.get_data()
    profile_id = data.get('current_profile_id')
    if not profile_id:
        await message.answer("❌ Profil tanlanmagan. Iltimos, avval profil tanlang.")
        await state.set_state(MainForm.main_menu)
        await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())
        return
    auto_send_enabled = bool(int(get_profile_setting(profile_id, "auto_send_enabled") or 0))
    auto_send_enabled = not auto_send_enabled
    update_profile_setting(profile_id, "auto_send_enabled", "1" if auto_send_enabled else "0")
    status = "yoqildi" if auto_send_enabled else "o‘chirildi"
    await message.answer(MESSAGES["AUTO_SEND_TOGGLED"].format(status=status), reply_markup=get_profile_keyboard())

@dp.message(MainForm.profile_menu, F.text == PROFILE_MENU_BUTTONS["BACK_TO_MAIN"])
@admin_only
async def back_to_main_menu(message: types.Message, state: FSMContext):
    await state.set_state(MainForm.main_menu)
    await message.answer(MESSAGES["BACK_TO_MAIN"], reply_markup=get_main_keyboard())

@dp.message()
@admin_only
async def general_handler(message: types.Message, state: FSMContext):
    await message.answer("ℹ Iltimos, menyudan tanlang.")