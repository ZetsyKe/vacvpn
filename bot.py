import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder, WebAppInfo
from dotenv import load_dotenv
from typing import Dict, List

# Загрузка переменных окружения из key.env
load_dotenv("backend/key.env")

# Получение токена из окружения
TOKEN = os.getenv("TOKEN")
WEB_APP_URL = "https://vacvpn.vercel.app"
SUPPORT_NICK = "@vacvpn_support"
TG_CHANNEL = "@vac_vpn"

# Проверка токена
if not TOKEN:
    raise ValueError("❌ Переменная TOKEN не найдена в key.env")

# Инициализация бота
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Хранилища
referrals_db: Dict[int, List[int]] = {}
user_balances: Dict[int, int] = {}
referral_checks: Dict[int, bool] = {}

# Клавиатуры
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(
        types.KeyboardButton(text="🔐 Личный кабинет"),
        types.KeyboardButton(text="📊 Мои рефералы")
    )
    builder.row(
        types.KeyboardButton(text="👥 Рефералка"),
        types.KeyboardButton(text="🛠️ Техподдержка")
    )
    return builder.as_markup(resize_keyboard=True)

def get_cabinet_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="📲 Открыть личный кабинет",
            web_app=WebAppInfo(url=WEB_APP_URL)
        )
    )
    builder.row(
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")
    )
    return builder.as_markup()

def get_ref_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="🤜🤛 Поделиться ссылкой",
            url=f"https://t.me/share/url?url=https://t.me/vacvpnbot?start=ref_{user_id}"
        )
    )
    builder.row(
        types.InlineKeyboardButton(text="📊 Мои рефералы", callback_data="my_referrals")
    )
    builder.row(
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")
    )
    return builder.as_markup()

def get_support_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="📞 Написать в поддержку",
            url=f"https://t.me/{SUPPORT_NICK[1:]}"
        )
    )
    builder.row(
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")
    )
    return builder.as_markup()

def get_referrals_stats_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_ref")
    )
    return builder.as_markup()

# Текстовые сообщения
def get_welcome_message(user_name: str, is_referral: bool = False):
    return f"""
<b>Рады видеть вас снова, {user_name}!</b>

Перейдите в личный кабинет по ссылке:

👉👉 {WEB_APP_URL} 👈👈

👫 Пригласите друга в VAC VPN и получите бонус!

📌 Обязательно подпишитесь на наш канал ({TG_CHANNEL})!
"""

def get_cabinet_message():
    return f"""
<b>Личный кабинет VAC VPN</b>

Для доступа к VPN перейдите по ссылке:
👉👉 {WEB_APP_URL} 👈👈
"""

def get_ref_message(user_id: int):
    balance = user_balances.get(user_id, 0)
    ref_count = len(referrals_db.get(user_id, []))
    return f"""
<b>Реферальная программа VAC VPN</b>

Пригласите друга по вашей ссылке:
<code>https://t.me/vacvpnbot?start=ref_{user_id}</code>

<b>Ваша статистика:</b>
├ Приглашено: <b>{ref_count} чел.</b>
└ Заработано: <b>{balance}₽</b>

За каждого приглашённого друга вы получаете <b>50₽</b> на баланс!
"""

def get_support_message():
    return f"""
<b>Техническая поддержка VAC VPN</b>

Если у вас возникли вопросы или проблемы:

📞 Telegram: {SUPPORT_NICK}
📢 Наш канал: {TG_CHANNEL}
"""

def get_referrals_stats_message(user_id: int):
    refs = referrals_db.get(user_id, [])
    balance = user_balances.get(user_id, 0)
    active_refs = [ref_id for ref_id in refs if referral_checks.get(ref_id, False)]

    if not refs:
        return "<b>Ваши рефералы</b>\n\nУ вас пока нет приглашенных пользователей"

    message = "<b>Ваши рефералы</b>\n\n"
    message += f"Всего приглашено: <b>{len(refs)} чел.</b>\n"
    message += f"Активных: <b>{len(active_refs)} чел.</b>\n"
    message += f"Заработано: <b>{balance}₽</b>\n\n"
    message += "<b>Список рефералов:</b>\n"

    for i, ref_id in enumerate(refs, 1):
        status = "✅" if ref_id in active_refs else "❌"
        message += f"{i}. ID: <code>{ref_id}</code> {status}\n"

    return message

# Обработчики
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    args = message.text.split()
    is_referral = False

    if len(args) > 1 and args[1].startswith('ref_'):
        referrer_id = int(args[1][4:])
        referred_id = user.id

        if referred_id != referrer_id:
            if referrer_id not in referrals_db:
                referrals_db[referrer_id] = []

            if referred_id not in referrals_db[referrer_id]:
                referrals_db[referrer_id].append(referred_id)
                user_balances[referrer_id] = user_balances.get(referrer_id, 0) + 50
                referral_checks[referred_id] = True
                is_referral = True
                try:
                    await bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 Новый реферал!\nID: {referred_id}\nВаш баланс: {user_balances[referrer_id]}₽"
                    )
                except:
                    pass

    await message.answer(
        text=get_welcome_message(user.full_name, is_referral),
        reply_markup=get_main_keyboard()
    )

@dp.message(lambda message: message.text == "🔐 Личный кабинет")
async def cabinet_handler(message: types.Message):
    await message.answer(
        text=get_cabinet_message(),
        reply_markup=get_cabinet_keyboard()
    )

@dp.message(lambda message: message.text == "👥 Рефералка")
async def ref_handler(message: types.Message):
    await message.answer(
        text=get_ref_message(message.from_user.id),
        reply_markup=get_ref_keyboard(message.from_user.id),
        disable_web_page_preview=True
    )

@dp.message(lambda message: message.text == "🛠️ Техподдержка")
async def support_handler(message: types.Message):
    await message.answer(
        text=get_support_message(),
        reply_markup=get_support_keyboard()
    )

@dp.message(lambda message: message.text == "📊 Мои рефералы")
async def referrals_stats_handler(message: types.Message):
    await message.answer(
        text=get_referrals_stats_message(message.from_user.id),
        reply_markup=get_referrals_stats_keyboard(),
        disable_web_page_preview=True
    )

@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        text=get_welcome_message(callback.from_user.full_name),
        reply_markup=None
    )
    await callback.message.answer(
        text="Вы вернулись в главное меню",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_ref")
async def back_to_ref_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        text=get_ref_message(callback.from_user.id),
        reply_markup=get_ref_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "my_referrals")
async def my_referrals_handler(callback: types.CallbackQuery):
    await callback.message.edit_text(
        text=get_referrals_stats_message(callback.from_user.id),
        reply_markup=get_referrals_stats_keyboard()
    )
    await callback.answer()

# Запуск
async def main():
    await bot.set_chat_menu_button(
        menu_button=types.MenuButtonWebApp(
            text="VAC VPN",
            web_app=WebAppInfo(url=WEB_APP_URL)
        )
    )
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
