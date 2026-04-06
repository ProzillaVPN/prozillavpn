import os
import asyncio
import httpx
import signal
import sys
import logging
import time

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.types import WebAppInfo, LinkPreviewOptions

from xray_manager import XrayManager, generate_vless_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

logger.info("=" * 50)
logger.info("🤖 BOT STARTUP CHECK")
logger.info("=" * 50)
logger.info(f"Python: {sys.version}")
logger.info(f"Directory: {os.getcwd()}")
logger.info(f"TOKEN: {'✅ SET' if os.getenv('TOKEN') else '❌ MISSING'}")

TOKEN = os.getenv("TOKEN")

if not TOKEN or len(TOKEN) < 20:
    raise RuntimeError("❌ TOKEN is missing or invalid")

SUPPORT_NICK = os.getenv("SUPPORT_NICK", "@@ProstyleLogo")
TG_CHANNEL = os.getenv("TG_CHANNEL", "@ProzillaVPN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "ProzillaVPN_bot")

TARIFFS = {
    "1month": {
        "title": "1 месяц",
        "price": 149,
        "desc": "Полный доступ на 30 дней"
    },
    "3months": {
        "name": "3 Месяца",
        "price": 399,
        "desc": "Полный доступ на 90 дней"
    },
    "6months": {
        "name": "6 Месяцев",
        "price": 699,
        "desc": "Полный доступ на 180 дней"
    },
    "1year": {
        "title": "1 год",
        "price": 1188,
        "desc": "Полный доступ на 365 дней"
    }
}

# Лучше использовать отдельный URL, если есть
APP_BASE_URL = os.getenv("APP_BASE_URL")
RAILWAY_STATIC_URL = os.getenv("RAILWAY_STATIC_URL")

if APP_BASE_URL:
    BASE_URL = APP_BASE_URL.rstrip("/")
elif RAILWAY_STATIC_URL:
    BASE_URL = f"https://{RAILWAY_STATIC_URL}".rstrip("/")
else:
    raise RuntimeError("❌ API base URL is not set (APP_BASE_URL or RAILWAY_STATIC_URL required)")

API_BASE_URL = BASE_URL
WEB_APP_URL = BASE_URL

logger.info(f"🌐 API сервер: {API_BASE_URL}")
logger.info(f"🌐 Веб-приложение: {WEB_APP_URL}")

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(30.0, connect=10.0),
    limits=httpx.Limits(
        max_connections=100,
        max_keepalive_connections=20
    ),
    headers={
        "Connection": "keep-alive"
    }
)

dp = Dispatcher()

# защита от двойного /start
START_LOCK = {}
PAYMENT_LOCK = {}
PAYMENT_TTL = 15
START_LOCK_TTL = 10  # секунд

async def clear_start_lock(user_id: int):
    await asyncio.sleep(START_LOCK_TTL)
    START_LOCK.pop(user_id, None)

def no_preview():
    return LinkPreviewOptions(is_disabled=True)


async def make_api_request(endpoint: str, method: str = "GET", json_data: dict = None, params: dict = None):
    try:
        url = f"{API_BASE_URL}{endpoint}"

        if method.upper() == "GET":
            response = await http_client.get(url, params=params)

        elif method.upper() == "POST":
            response = await http_client.post(url, json=json_data)

        else:
            raise ValueError(f"Unsupported method: {method}")

        response.raise_for_status()

        try:
            return response.json()
        except Exception:
            logger.error(f"❌ API returned non-JSON: {response.text[:300]}")
            return {"error": "API returned invalid JSON"}

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error {e.response.status_code} for {endpoint}: {e.response.text[:300]}")
        return {"error": f"API error: {e.response.status_code}"}

    except httpx.RequestError as e:
        logger.error(f"Request error for {endpoint}: {e}")
        return {"error": f"Connection error: {str(e)}"}

    except Exception as e:
        logger.exception(f"Unexpected API error for {endpoint}")
        return {"error": f"Unexpected error: {str(e)}"}


async def get_user_info(user_id: int):
    return await make_api_request("/user-data", "GET", params={"user_id": str(user_id)})


async def create_user(user_data: dict):
    return await make_api_request("/init-user", "POST", json_data=user_data)


async def get_vless_config(user_id: int):
    return await make_api_request("/get-vless-config", "GET", params={"user_id": str(user_id)})


async def send_referral_notification(referrer_id: int, referred_user: types.User):
    try:
        referred_username = f"@{referred_user.username}" if referred_user.username else referred_user.first_name

        message = (
            f"🎉 <b>У вас новый реферал!</b>\n\n"
            f"👤 Пользователь: {referred_username}\n"
            f"💰 <b>Бонус 50₽ уже начислен на ваш баланс!</b>\n\n"
            f"Продолжайте приглашать друзей и зарабатывать больше! 🚀"
        )

        await bot.send_message(
            chat_id=referrer_id,
            text=message,
            link_preview_options=no_preview()
        )
        logger.info(f"✅ Уведомление отправлено рефереру {referrer_id}")
        return True

    except Exception as e:
        logger.error(f"❌ Не удалось отправить уведомление рефереру {referrer_id}: {e}")
        return False


def clean_tg_username(value: str) -> str:
    return value[1:] if value.startswith("@") else value


def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(
        types.KeyboardButton(text="💳 Купить подписку"),
        types.KeyboardButton(text="🌐 Веб-кабинет")
    )
    builder.row(
        types.KeyboardButton(text="🔐 Личный кабинет"),
        types.KeyboardButton(text="👥 Рефералка")
    )
    builder.row(
        types.KeyboardButton(text="🛠️ Техподдержка"),
        types.KeyboardButton(text="🔧 VLESS Конфиг")
    )

    return builder.as_markup(resize_keyboard=True)


def get_cabinet_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="📲 Открыть веб-кабинет",
            web_app=WebAppInfo(url=WEB_APP_URL)
        )
    )
    builder.row(
        types.InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_cabinet"),
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")
    )
    return builder.as_markup()


def get_ref_keyboard(user_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="🤜🤛 Поделиться ссылкой",
            url=f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
        )
    )
    builder.row(
        types.InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_refs"),
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")
    )
    return builder.as_markup()


def get_support_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="📞 Написать в поддержку",
            url=f"https://t.me/{clean_tg_username(SUPPORT_NICK)}"
        )
    )
    builder.row(
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")
    )
    return builder.as_markup()


def get_vless_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_vless"),
        types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")
    )
    return builder.as_markup()


def get_welcome_message(user_name: str, is_referral: bool = False):
    message = f"""
<b>Добро пожаловать в ProzillaVPN, {user_name}!</b>

🚀 Получите безопасный и быстрый доступ к интернету с нашей VPN-службой.

📊 <b>Основные возможности:</b>
• 🔒 Защита ваших данных
• 🌐 Обход блокировок
• 🚀 Высокая скорость
• 📱 Работа на всех устройствах

💳 <b>Оплата подписки:</b>
Для покупки подписки перейдите в веб-кабинет через меню бота.
"""
    if is_referral:
        message += "\n🎉 <b>Вы зарегистрировались по реферальной ссылке! Бонус 100₽ уже начислен на ваш баланс!</b>"

    message += "\n\n👫 <b>Пригласите друга и получите бонус!</b>"
    return message


async def get_cabinet_message(user_id: int):
    user_data = await get_user_info(user_id)

    if user_data.get("error"):
        return f"""
<b>Личный кабинет ProzillaVPN</b>

❌ Ошибка загрузки данных: {user_data['error']}

💡 Попробуйте обновить данные или обратитесь в поддержку.
"""

    balance = user_data.get("balance", 0)
    has_subscription = user_data.get("has_subscription", False)
    subscription_days = user_data.get("subscription_days", 0)

    status_text = "✅ Активна" if has_subscription else "❌ Неактивна"
    subscription_info = f"{subscription_days} дней осталось" if has_subscription else "нет активной подписки"

    referral_stats = user_data.get("referral_stats", {})
    total_referrals = referral_stats.get("total_referrals", 0)
    total_bonus_money = referral_stats.get("total_bonus_money", 0)

    return f"""
<b>Личный кабинет ProzillaVPN</b>

💰 Баланс: <b>{balance}₽</b>
📅 Статус подписки: <b>{status_text}</b>
⏰ Осталось дней: <b>{subscription_info}</b>

👥 Реферальная статистика:
• Приглашено друзей: <b>{total_referrals}</b>
• Получено бонусов: <b>{total_bonus_money}₽</b>

💡 Для покупки подписки используйте веб-кабинет.
"""


def get_ref_message(user_id: int):
    return f"""
<b>Реферальная программа ProzillaVPN</b>

Пригласите друга по вашей ссылке:
<code>https://t.me/{BOT_USERNAME}?start=ref_{user_id}</code>

🎁 <b>Бонус за приглашение:</b>
• Вы получаете <b>50₽</b> на баланс
• Ваш друг получает <b>100₽</b> на баланс
• Бонусы начисляются сразу после регистрации!

💡 Делитесь ссылкой и получайте бонусы!
"""


def get_support_message():
    return f"""
<b>Техническая поддержка ProzillaVPN</b>

Если у вас возникли вопросы или проблемы:

📞 Telegram: {SUPPORT_NICK}
📢 Наш канал: {TG_CHANNEL}

⏰ Время ответа: обычно в течение 1–2 часов
"""


async def get_vless_message(user_id: int):
    vless_data = await get_vless_config(user_id)

    if vless_data.get("error"):
        return f"""
<b>VLESS Конфигурация</b>

❌ Ошибка: {vless_data['error']}

💡 Для получения конфигурации необходима активная подписка.
"""

    if not vless_data.get("configs"):
        return """
<b>VLESS Конфигурация</b>

❌ Конфигурация не найдена.

💡 Для получения конфигурации необходима активная подписка.
"""

    message = "<b>🔧 VLESS Конфигурация</b>\n\n"

    for config_data in vless_data["configs"]:
        config = config_data.get("config", {})
        vless_link = config_data.get("vless_link", "Не найдено")
        config_name = config.get("name", "Конфиг")

        message += f"""
<strong>{config_name}</strong>
<code>{vless_link}</code>

📱 <b>Для подключения:</b>
1. Скопируйте ссылку выше
2. Вставьте в ваше VPN-приложение
3. Импортируйте конфигурацию

💡 <b>Рекомендуемые приложения:</b>
• Android: V2BOX
• iOS: V2BOX
• Windows: Hiddify
• macOS: V2BOX
"""

    return message


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    user_id = user.id

    # 🔒 1. защита от двойного запуска
    now = time.time()
    last_time = START_LOCK.get(user_id)

    if last_time and now - last_time < START_LOCK_TTL:
        logger.warning(f"⚠️ Duplicate /start ignored for user {user_id}")
        return

    START_LOCK[user_id] = now

    try:
        args = message.text.split() if message.text else []
        is_referral = False
        referrer_id = None

        # 🎯 рефералка
        if len(args) > 1 and args[1].startswith("ref_"):
            raw_referrer_id = args[1][4:]
            if raw_referrer_id.isdigit() and int(raw_referrer_id) != user_id:
                is_referral = True
                referrer_id = int(raw_referrer_id)
                logger.info(f"🎯 Реферальная регистрация: {user_id} от {referrer_id}")

        # 👤 создание пользователя
        user_create_result = await create_user({
            "user_id": str(user_id),
            "username": user.username or "",
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "start_param": args[1] if len(args) > 1 else ""
        })

        logger.info(f"User create result: {user_create_result}")

        # 🎁 реферал уведомление
        if is_referral and referrer_id:
            await send_referral_notification(referrer_id, user)

        # 💬 ответ пользователю
        await message.answer(
            text=get_welcome_message(user.first_name or "друг", is_referral),
            reply_markup=get_main_keyboard(),
            link_preview_options=no_preview()
        )

    finally:
        START_LOCK.pop(user_id, None)


@dp.message(Command("cabinet"))
async def cmd_cabinet(message: types.Message):
    user_id = message.from_user.id
    cabinet_text = await get_cabinet_message(user_id)
    await message.answer(
        cabinet_text,
        reply_markup=get_cabinet_keyboard(),
        link_preview_options=no_preview()
    )


@dp.message(Command("referral"))
async def cmd_referral(message: types.Message):
    user_id = message.from_user.id
    await message.answer(
        get_ref_message(user_id),
        reply_markup=get_ref_keyboard(user_id),
        link_preview_options=no_preview()
    )


@dp.message(Command("support"))
async def cmd_support(message: types.Message):
    await message.answer(
        get_support_message(),
        reply_markup=get_support_keyboard(),
        link_preview_options=no_preview()
    )


@dp.message(Command("vless"))
async def cmd_vless(message: types.Message):
    user_id = message.from_user.id
    vless_text = await get_vless_message(user_id)
    await message.answer(
        vless_text,
        reply_markup=get_vless_keyboard(),
        link_preview_options=no_preview()
    )


@dp.message(F.text == "💳 Купить подписку")
async def buy_subscription_handler(message: types.Message):
    builder = InlineKeyboardBuilder()

    builder.row(
        types.InlineKeyboardButton(
            text="🟢 1 месяц — 149₽",
            callback_data="tariff_1month"
        )
    )
    builder.row(
        types.InlineKeyboardButton(
            text="🔵 1 год — 1188₽ (99₽/мес)",
            callback_data="tariff_1year"
        )
    )
    builder.row(
        types.InlineKeyboardButton(
            text="🟣 Пожизненно — 9999₽",
            callback_data="tariff_lifetime"
        )
    )

    await message.answer(
        "⚡ <b>Выберите тариф</b>\n\n"
        "После выбора мы создадим безопасную оплату 🔒",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("tariff_"))
async def tariff_select(callback: types.CallbackQuery):
    tariff_key = callback.data.replace("tariff_", "")
    tariff = TARIFFS.get(tariff_key)

    if not tariff:
        await callback.answer("Тариф не найден", show_alert=True)
        return

    builder = InlineKeyboardBuilder()

    builder.row(
        types.InlineKeyboardButton(
            text="💳 Перейти к оплате",
            callback_data=f"pay_{tariff_key}"
        )
    )
    builder.row(
        types.InlineKeyboardButton(
            text="🔙 Назад к тарифам",
            callback_data="back_to_tariffs"
        )
    )

    await callback.message.edit_text(
        f"""
🔥 <b>{tariff['title']}</b>

💰 <b>Цена:</b> {tariff['price']}₽
📦 <b>Описание:</b> {tariff['desc']}

🔒 Оплата защищена и занимает менее 10 секунд
⚡ После оплаты доступ активируется автоматически
        """,
        reply_markup=builder.as_markup()
    )

    await callback.answer()

@dp.callback_query(F.data == "back_to_tariffs")
async def back_to_tariffs(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()

    builder.row(
        types.InlineKeyboardButton(text="🟢 1 месяц — 149₽", callback_data="tariff_1month")
    )
    builder.row(
        types.InlineKeyboardButton(text="🔵 1 год — 1188₽ (99₽/мес)", callback_data="tariff_1year")
    )
    builder.row(
        types.InlineKeyboardButton(text="🟣 Пожизненно — 9999₽", callback_data="tariff_lifetime")
    )

    await callback.message.edit_text(
        "⚡ <b>Выберите тариф</b>",
        reply_markup=builder.as_markup()
    )

    await callback.answer()

@dp.callback_query(F.data.startswith("pay_"))
async def create_payment(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    tariff_key = callback.data.replace("pay_", "")
    tariff = TARIFFS.get(tariff_key)

    if not tariff:
        await callback.answer("Ошибка тарифа", show_alert=True)
        return

    await callback.message.edit_text(
        "⏳ <b>Создаём безопасную оплату...</b>\n\nЭто займёт 1–2 секунды"
    )

    result = await make_api_request(
        "/activate-tariff",
        method="POST",
        json_data={
            "user_id": str(user_id),
            "tariff": tariff_key
            # "price": tariff["price"]
        }
    )

    if result.get("error"):
        await callback.message.answer(f"❌ Ошибка: {result['error']}")
        return

    payment_url = result.get("payment_url")

    if not payment_url:
        await callback.message.answer("❌ Ошибка оплаты (нет ссылки)")
        return

    payment_id = result.get("payment_id")

    builder = InlineKeyboardBuilder()

    builder.row(
        types.InlineKeyboardButton(text="💳 Оплатить", url=payment_url)
    )

    builder.row(
        types.InlineKeyboardButton(
            text="✅ Я оплатил",
            callback_data=f"check_{payment_id}"
        )
    )

    builder.row(
    types.InlineKeyboardButton(
        text="🔄 Проверить оплату",
        callback_data=f"check_{payment_id}"
    )
)

    await callback.message.edit_text(
        f"""
💳 <b>Оплата готова</b>

📦 Тариф: <b>{tariff['title']}</b>
💰 Сумма: <b>{tariff['price']}₽</b>

🔒 После оплаты нажмите кнопку ниже
⚡ Активация происходит автоматически
        """,
        reply_markup=builder.as_markup()
    )

    await callback.answer()

@dp.message(F.text == "🔐 Личный кабинет")
async def cabinet_handler(message: types.Message):
    user_id = message.from_user.id
    cabinet_text = await get_cabinet_message(user_id)
    await message.answer(
        cabinet_text,
        reply_markup=get_cabinet_keyboard(),
        link_preview_options=no_preview()
    )


@dp.message(F.text == "👥 Рефералка")
async def referral_handler(message: types.Message):
    user_id = message.from_user.id
    await message.answer(
        get_ref_message(user_id),
        reply_markup=get_ref_keyboard(user_id),
        link_preview_options=no_preview()
    )


@dp.message(F.text == "🛠️ Техподдержка")
async def support_handler(message: types.Message):
    await message.answer(
        get_support_message(),
        reply_markup=get_support_keyboard(),
        link_preview_options=no_preview()
    )


@dp.message(F.text == "🌐 Веб-кабинет")
async def web_app_handler(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="📲 Открыть веб-кабинет",
            web_app=WebAppInfo(url=WEB_APP_URL)
        )
    )
    await message.answer(
        "🌐 <b>Веб-кабинет ProzillaVPN</b>\n\nДля покупки подписки и управления аккаунтом откройте веб-кабинет:",
        reply_markup=builder.as_markup(),
        link_preview_options=no_preview()
    )


@dp.message(F.text == "🔧 VLESS Конфиг")
async def vless_handler(message: types.Message):
    user_id = message.from_user.id
    vless_text = await get_vless_message(user_id)
    await message.answer(
        vless_text,
        reply_markup=get_vless_keyboard(),
        link_preview_options=no_preview()
    )

@dp.message(Command("testvpn"))
async def test_vpn(message: types.Message):
    try:
        user_id = message.from_user.id
        email = f"user_{user_id}"

        xray = XrayManager()
        success, result = await xray.add_user(email=email)

        if not success:
            await message.answer(f"❌ Ошибка создания ключа:\n<code>{result}</code>")
            return

        user_uuid = result
        vless_key = generate_vless_key(user_uuid, email)

        await message.answer(
            f"✅ VPN ключ создан:\n\n<code>{vless_key}</code>"
        )

    except Exception as e:
        logger.exception("Ошибка в /testvpn")
        await message.answer(f"❌ Критическая ошибка:\n<code>{str(e)}</code>")

@dp.message(Command("testapi"))
async def test_api(message: types.Message):
    try:
        response = await http_client.get("http://72.56.22.233:8002/")
        await message.answer(
            f"Status: {response.status_code}\n\n"
            f"Body:\n<code>{response.text[:1000]}</code>"
        )
    except Exception as e:
        await message.answer(f"API error: <code>{str(e)}</code>")

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_handler(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        "🏠 <b>Главное меню ProzillaVPN</b>",
        reply_markup=get_main_keyboard(),
        link_preview_options=no_preview()
    )

    await callback.answer()


@dp.callback_query(F.data == "refresh_cabinet")
async def refresh_cabinet_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    cabinet_text = await get_cabinet_message(user_id)

    try:
        await callback.message.edit_text(
            cabinet_text,
            reply_markup=get_cabinet_keyboard(),
            link_preview_options=no_preview()
        )
    except Exception as e:
        logger.warning(f"edit_text failed in refresh_cabinet: {e}")
        await callback.message.answer(
            cabinet_text,
            reply_markup=get_cabinet_keyboard(),
            link_preview_options=no_preview()
        )

    await callback.answer("✅ Данные обновлены")


@dp.callback_query(F.data == "refresh_refs")
async def refresh_refs_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    new_ref_message = get_ref_message(user_id)

    try:
        await callback.message.edit_text(
            new_ref_message,
            reply_markup=get_ref_keyboard(user_id),
            link_preview_options=no_preview()
        )
    except Exception as e:
        logger.warning(f"edit_text failed in refresh_refs: {e}")
        await callback.message.answer(
            new_ref_message,
            reply_markup=get_ref_keyboard(user_id),
            link_preview_options=no_preview()
        )

    await callback.answer("✅ Статистика обновлена")

@dp.callback_query(F.data.startswith("check_"))
async def check_payment(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    payment_id = callback.data.replace("check_", "")

    if not payment_id or len(payment_id) < 10:
        await callback.message.edit_text("❌ Ошибка: неверный payment_id")
        return

    await callback.message.edit_text("⏳ Проверяем оплату...")

    result = await make_api_request(
        "/check-payment",
        method="GET",
        params={
            "payment_id": payment_id,
            "user_id": str(user_id)
        }
    )

    if result.get("error"):
        await callback.message.edit_text(
            f"❌ Ошибка:\n{result['error']}"
        )
        return

    status = result.get("status")

    if status != "succeeded":
        await callback.message.edit_text(
            "❌ <b>Оплата ещё не прошла</b>\n\n"
            "Подождите 10–30 секунд и нажмите ещё раз"
        )
        return

    # ✅ ОПЛАТА ПРОШЛА → ПОЛУЧАЕМ КОНФИГ
    vless = await get_vless_config(user_id)

    if not vless.get("success"):
        await callback.message.edit_text(
            "⚠️ Оплата прошла, но конфиг ещё не готов. Попробуйте через 5 секунд."
        )
        return

    configs = vless.get("configs", [])
    first = configs[0] if configs else {}

    vless_link = first.get("vless_link", "не найден")

    await callback.message.edit_text(
        f"""
🎉 <b>Оплата прошла!</b>

🚀 Подписка активирована

🔐 <b>Ваш VPN ключ:</b>
<code>{vless_link}</code>

📱 Скопируйте и вставьте в приложение
        """
    )

    await callback.answer()

@dp.callback_query(F.data == "refresh_vless")
async def refresh_vless_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    vless_text = await get_vless_message(user_id)

    try:
        await callback.message.edit_text(
            vless_text,
            reply_markup=get_vless_keyboard(),
            link_preview_options=no_preview()
        )
    except Exception as e:
        logger.warning(f"edit_text failed in refresh_vless: {e}")
        await callback.message.answer(
            vless_text,
            reply_markup=get_vless_keyboard(),
            link_preview_options=no_preview()
        )

    await callback.answer("✅ Конфигурация обновлена")

async def process_payment_check(user_id: int, tariff_key: str, message: types.Message):
    result = await make_api_request(
        "/check-payment",
        method="POST",
        json_data={
            "user_id": str(user_id),
            "tariff": tariff_key
        }
    )

    if not result.get("paid"):
        await message.answer("❌ Оплата не найдена. Попробуйте позже.")
        return

    activate = await make_api_request(
        "/activate-subscription",
        method="POST",
        json_data={
            "user_id": str(user_id),
            "tariff": tariff_key
        }
    )

    if activate.get("error"):
        await message.answer(f"❌ Ошибка: {activate['error']}")
        return

    await message.answer(
        f"""
🎉 <b>Оплата подтверждена!</b>

🚀 Подписка активирована

🔐 Ключ:
<code>{activate.get('vless_key')}</code>
        """
    )

async def run_bot():
    logger.info("🔄 BOT VERSION 2.1 - RAILWAY SAFE + HARDENED")
    logger.info("🤖 Бот ProzillaVPN запускается...")
    logger.info(f"🌐 API сервер: {API_BASE_URL}")
    logger.info(f"🌐 Веб-приложение: {WEB_APP_URL}")
    logger.info("🚀 START POLLING ENTERED")

    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.exception("💥 POLLING CRASHED")
        raise
    finally:
        await shutdown()

async def shutdown():
    logger.info("🧹 Выключение бота...")

    try:
        await bot.session.close()
    except Exception as e:
        logger.warning(f"bot close error: {e}")

    try:
        await http_client.aclose()
    except Exception as e:
        logger.warning(f"http client close error: {e}")

    try:
        await dp.stop_polling()
    except Exception:
        pass

    logger.info("✅ Shutdown completed")


async def main():
    logger.info("🚀 MAIN STARTED")
    await run_bot()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Бот остановлен")