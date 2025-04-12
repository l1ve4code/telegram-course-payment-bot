import os
import uuid
import asyncio
import sqlite3
import logging
from typing import Optional, List, Tuple

import yookassa
from yookassa import Payment

from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PRODUCTS = {
    "basic": {
        "id": 1,
        "name": "🔥 Основной тариф",
        "price": 6000,
        "description": "Доступ к курсу 'Как найти свою Любовь?', 21 день"
    },
    "individual": {
        "id": 2,
        "name": "💖 Специальный тариф",
        "price": 39000,
        "description": "Доступ к курсу 'Как найти свою Любовь?', 40 дней"
    }
}

BOT_TOKEN = os.getenv('BOT_TOKEN')
YOOKASSA_ID = os.getenv('YOOKASSA_ID')
YOOKASSA_KEY = os.getenv('YOOKASSA_KEY')
YOOKASSA_RETURN_URL = os.getenv('YOOKASSA_RETURN_URL')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')

DATABASE_NAME = "data/bot.db"

yookassa.Configuration.account_id = YOOKASSA_ID
yookassa.Configuration.secret_key = YOOKASSA_KEY

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)


# ========== БАЗА ДАННЫХ ========== #
def init_db():
    os.makedirs("data", exist_ok=True)
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                username TEXT,
                phone TEXT,
                registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                payment_id TEXT UNIQUE,
                payment_status TEXT DEFAULT 'pending',
                amount REAL,
                invoice_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')

        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
    finally:
        if conn is not None:
            conn.close()


init_db()


def execute_db_query(query: str, params: tuple = (), fetch: bool = False):
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        return cursor.fetchall() if fetch else True
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return False
    finally:
        if conn is not None:
            conn.close()


def add_user(user_id: int, username: str, phone: str = None):
    execute_db_query(
        "INSERT OR IGNORE INTO users (user_id, username, phone) VALUES (?, ?, ?)",
        (user_id, username, phone)
    )


def update_user_phone(user_id: int, phone: str):
    execute_db_query(
        "UPDATE users SET phone = ? WHERE user_id = ?",
        (phone, user_id)
    )


def add_payment(user_id: int, payment_id: str, amount: float):
    execute_db_query(
        "INSERT INTO payments (user_id, payment_id, amount) VALUES (?, ?, ?)",
        (user_id, payment_id, amount)
    )


def update_payment_status(payment_id: str, status: str):
    execute_db_query(
        "UPDATE payments SET payment_status = ? WHERE payment_id = ?",
        (status, payment_id)
    )


def get_user_info(user_id: int) -> Optional[Tuple]:
    result = execute_db_query(
        """SELECT u.username, u.phone, 
           p.amount, p.payment_status 
           FROM users u LEFT JOIN payments p ON u.user_id = p.user_id 
           WHERE u.user_id = ?""",
        (user_id,),
        fetch=True
    )
    return result[0] if result else None


def get_all_users() -> List[Tuple]:
    return execute_db_query(
        """SELECT u.user_id, u.username, u.phone, 
           p.amount, p.payment_status 
           FROM users u LEFT JOIN payments p ON u.user_id = p.user_id""",
        fetch=True
    )


def get_stats() -> dict:
    result = execute_db_query(
        "SELECT COUNT(*) FROM users",
        fetch=True
    )
    total_users = result[0][0] if result else 0

    result = execute_db_query(
        "SELECT COUNT(*) FROM payments WHERE payment_status = 'succeeded'",
        fetch=True
    )
    paid_users = result[0][0] if result else 0

    conversion = (paid_users / total_users * 100) if total_users > 0 else 0

    return {
        'total_users': total_users,
        'paid_users': paid_users,
        'conversion': round(conversion, 2)
    }


# ========== YOOKASSA ========== #
def create_payment(product_id: str, chat_id: int):
    product = PRODUCTS.get(product_id)
    if not product:
        raise ValueError("Неизвестный товар")

    id_key = str(uuid.uuid4())
    payment = Payment.create({
        'amount': {
            'value': product["price"],
            'currency': 'RUB'
        },
        'confirmation': {
            'type': 'redirect',
            'return_url': YOOKASSA_RETURN_URL
        },
        'capture': True,
        'metadata': {
            'chat_id': chat_id,
            'product_id': product_id
        },
        'description': product["description"]
    }, id_key)

    return payment.confirmation.confirmation_url, payment.id


def check_payment(payment_id: str):
    payment = Payment.find_one(payment_id)
    return payment.status, payment.metadata


# ========== HANDLERS ========== #
@router.message(Command(commands=['start']))
async def start_handler(message: Message):
    user = message.from_user
    add_user(user.id, user.username)

    welcome_message = """
🌟 *Добро пожаловать в бот для оплаты курса* 🌟

*«Как встретить Свою любовь?»*  

> _"Любовь — это не поиск идеального человека, а создание идеальных отношений."_  
> — © Джон Готтман

Этот бот предназначен исключительно для оплаты курса. После успешной оплаты с вами свяжутся организаторы курса для предоставления доступа.

Для продолжения поделитесь своим номером телефона:
    """

    markup = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Поделиться номером", request_contact=True)]
        ],
        resize_keyboard=True
    )

    await message.answer(welcome_message, reply_markup=markup, parse_mode="Markdown")


@router.message(F.contact)
async def contact_handler(message: Message):
    user = message.from_user
    contact = message.contact

    if contact.user_id != user.id:
        await message.answer("Пожалуйста, поделитесь своим номером телефона.")
        return

    update_user_phone(user.id, contact.phone_number)
    await message.answer(
        "✅ Спасибо! Теперь вы можете оформить доступ к курсу.\n\n"
        "Чтобы получить доступ к курсу, нажмите /buy",
        reply_markup=types.ReplyKeyboardRemove()
    )


@router.message(Command(commands=['buy']))
async def buy_handler(message: Message):
    user = message.from_user

    user_info = get_user_info(user.id)
    if not user_info or not user_info[1]:
        await message.answer("Сначала поделитесь номером телефона!")
        return

    builder = InlineKeyboardBuilder()
    for product_id, product in PRODUCTS.items():
        builder.add(types.InlineKeyboardButton(
            text=f"{product['name']} - {product['price']}₽",
            callback_data=f"product_{product_id}"
        ))
    builder.adjust(1)

    await message.answer(
        "🎁 Выберите товар для покупки:",
        reply_markup=builder.as_markup()
    )


@router.callback_query(lambda c: c.data.startswith('product_'))
async def product_selection_handler(callback: types.CallbackQuery):
    product_id = callback.data.split('_')[1]
    product = PRODUCTS.get(product_id)

    if not product:
        await callback.answer("Товар не найден")
        return

    payment_url, payment_id = create_payment(product_id, callback.message.chat.id)
    add_payment(callback.from_user.id, payment_id, product["price"])

    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text='💳 Оплатить',
        url=payment_url
    ))

    await callback.message.edit_text(
        f"🔹 *{product['name']}*\n\n"
        f"*Цена:* {product['price']}₽\n"
        f"*Описание:* {product['description']}\n\n"
        "Ссылка для оплаты:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(Command('stats'))
async def stats_handler(message: Message):
    command_args = message.text.split()[1:] if len(message.text.split()) > 1 else []

    if not command_args or command_args[0] != ADMIN_PASSWORD:
        await message.answer("Неверный пароль!")
        return

    stats = get_stats()
    await message.answer(
        "📊 *Статистика*\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"💰 Оплативших курс: {stats['paid_users']}\n"
        f"📈 Конверсия: {stats['conversion']}%",
        parse_mode="Markdown"
    )


@router.message(Command('users'))
async def users_handler(message: Message):
    command_args = message.text.split()[1:] if len(message.text.split()) > 1 else []

    if not command_args or command_args[0] != ADMIN_PASSWORD:
        await message.answer("Неверный пароль!")
        return

    users = get_all_users()
    if not users:
        await message.answer("Нет данных о пользователях.")
        return

    response = "📋 <b>Список пользователей</b>\n\n"
    for user in users:
        user_id, username, phone, amount, status = user
        response += (
            f"👤 <b>ID:</b> {user_id}\n"
            f"├ <b>Логин:</b> @{username or '—'}\n"
            f"├ <b>Телефон:</b> {phone or '—'}\n"
            f"├ <b>Сумма:</b> {amount or '—'} руб.\n"
            f"└ <b>Статус:</b> {status or '—'}\n\n"
        )

    for i in range(0, len(response), 4000):
        await message.answer(response[i:i + 4000], parse_mode="HTML")


# ========== BACKGROUND TASKS ========== #
async def check_payments_task():
    while True:
        try:
            pending_payments = execute_db_query(
                "SELECT payment_id FROM payments WHERE payment_status = 'pending'",
                fetch=True
            )

            for (payment_id,) in (pending_payments or []):
                status, metadata = check_payment(payment_id)

                update_payment_status(payment_id, status)

                if status == 'succeeded' and metadata.get('chat_id'):
                    await bot.send_message(
                        metadata['chat_id'],
                        "🎉 *Ваш платеж подтвержден!*\n\n"
                        "Спасибо за покупку! Организаторы курса свяжутся с вами "
                        "в ближайшее время для предоставления доступа.",
                        parse_mode="Markdown"
                    )

        except Exception as e:
            logger.error(f"Error in payment check task: {e}")

        await asyncio.sleep(300)


# ========== MAIN ========== #
async def main():
    asyncio.create_task(check_payments_task())
    await dp.start_polling(bot, skip_updates=False)


if __name__ == '__main__':
    asyncio.run(main())