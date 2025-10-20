from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from constants import MAIN_MENU_BUTTONS, PROFILE_MENU_BUTTONS

def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=MAIN_MENU_BUTTONS["ADD_PROFILE"]),
                KeyboardButton(text=MAIN_MENU_BUTTONS["LIST_PROFILES"]),
                KeyboardButton(text=MAIN_MENU_BUTTONS["DELETE_PROFILE"])
            ],
            [
                KeyboardButton(text=MAIN_MENU_BUTTONS["LIST_GROUPS"]),
                KeyboardButton(text=MAIN_MENU_BUTTONS["CHANGE_AUTO_REPLY_TEXT"]),
                KeyboardButton(text=MAIN_MENU_BUTTONS["CHANGE_RESPONSE_REPLY_TEXT"])
            ],
            [
                KeyboardButton(text=MAIN_MENU_BUTTONS["MESSAGE_TEXT"]),
                KeyboardButton(text=MAIN_MENU_BUTTONS["TOGGLE_AUTO_SEND"])
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def get_profile_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=PROFILE_MENU_BUTTONS["ADD_GROUP"]),
                KeyboardButton(text=PROFILE_MENU_BUTTONS["LIST_GROUPS"]),
                KeyboardButton(text=PROFILE_MENU_BUTTONS["PROFILE_INFO"])
            ],
            [KeyboardButton(text=PROFILE_MENU_BUTTONS["BACK_TO_MAIN"])]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def get_profile_selection_keyboard(profiles: list) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=p['phone'])] for p in profiles] + [[KeyboardButton(text=MAIN_MENU_BUTTONS["BACK_TO_MAIN"])]],
        resize_keyboard=True,
        one_time_keyboard=True
    )