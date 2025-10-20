from aiogram.fsm.state import State, StatesGroup

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

class MainForm(StatesGroup):
    main_menu = State()
    profile_menu = State()
    waiting_for_profile_delete = State()