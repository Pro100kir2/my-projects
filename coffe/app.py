import asyncio
import logging
import psycopg2

import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import CommandStart
from dotenv import load_dotenv
import urllib3
import threading
import time
import json
import uuid
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# ======================
# ⚙️ CONFIG
# ======================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")  # положи токен в .env
GIGACHAT_BASIC_KEY=os.getenv("GIGACHAT_BASIC_KEY")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
GIGACHAT_SCOPE = "GIGACHAT_API_PERS"
# ======================
# 📋 FAKE DATA
# ======================
MENU = {
    "☕ Coffee": {
        "Espresso": 2.20,
        "Latte": 3.50,
        "Cappuccino": 3.00
    },
    "🥤 Drinks": {
        "Iced Coffee": 3.00,
        "Tea": 1.80
    },
    "🥐 Snacks": {
        "Croissant": 2.00,
        "Muffin": 2.50
    }
}

FAQ = {
    "🕘 Opening hours": "We are open daily from 8:00 to 22:00",
    "🌱 Vegan options": "Yes! We offer plant-based milk and vegan snacks",
    "📍 Location": "Main campus, Building A, first floor"
}

# user_id -> cart
CART = {}

# ======================
# 🔘 KEYBOARDS
# ======================
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☕ Order coffee", callback_data="order")],
        [InlineKeyboardButton(text="📋 Menu", callback_data="menu")],
        [InlineKeyboardButton(text="🎯 Recommendation", callback_data="recommend")],
        [InlineKeyboardButton(text="💬 Ask Coffee Consultant", callback_data="consult_coffee")],  # новая кнопка
        [InlineKeyboardButton(text="❓ FAQ", callback_data="faq")],
        [InlineKeyboardButton(text="📍 Location", callback_data="location")]
    ])

def menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=cat, callback_data=f"cat:{cat}")]
        for cat in MENU.keys()
    ] + [[InlineKeyboardButton(text="⬅ Back", callback_data="back")]])

def items_keyboard(category):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{item} — ${price}",
            callback_data=f"add:{item}"
        )]
        for item, price in MENU[category].items()
    ] + [
        [InlineKeyboardButton(text="🛒 View cart", callback_data="cart")],
        [InlineKeyboardButton(text="⬅ Back", callback_data="menu")]
    ])

def faq_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=q, callback_data=f"faq:{q}")]
        for q in FAQ.keys()
    ] + [[InlineKeyboardButton(text="⬅ Back", callback_data="back")]])

# ======================
# 🚀 HANDLERS
# ======================
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Welcome to <b>Chinese coffee shops “Luckin Coffee” ☕</b>\n\n"
        "I can help you:\n"
        "• Order coffee\n"
        "• View menu\n"
        "• Get recommendations\n"
        "• Find our campus café",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "back")
async def back(callback: CallbackQuery):
    await callback.message.edit_text(
        "🏠 Main menu",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "menu")
async def show_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "📋 Choose a category:",
        reply_markup=menu_keyboard()
    )

@dp.callback_query(F.data.startswith("cat:"))
async def show_items(callback: CallbackQuery):
    category = callback.data.split(":")[1]
    await callback.message.edit_text(
        f"{category}\nSelect an item:",
        reply_markup=items_keyboard(category)
    )

@dp.callback_query(F.data.startswith("add:"))
async def add_to_cart(callback: CallbackQuery):
    item = callback.data.split(":")[1]
    CART.setdefault(callback.from_user.id, []).append(item)
    await callback.answer(f"{item} added to cart")

@dp.callback_query(F.data == "cart")
async def view_cart(callback: CallbackQuery):
    items = CART.get(callback.from_user.id, [])
    if not items:
        text = "🛒 Your cart is empty"
    else:
        text = "🛒 Your order:\n" + "\n".join(f"• {i}" for i in items)
        text += "\n\n⏱ Pickup in ~7 minutes"
    await callback.message.edit_text(text, reply_markup=main_menu())

@dp.callback_query(F.data == "order")
async def order(callback: CallbackQuery):
    CART[callback.from_user.id] = []
    await callback.message.edit_text(
        "☕ Let's order!\nChoose a category:",
        reply_markup=menu_keyboard()
    )

@dp.callback_query(F.data == "recommend")
async def recommend(callback: CallbackQuery):
    await callback.message.edit_text(
        "🎯 Recommendation of the day:\n\n"
        "☕ <b>Latte</b>\n"
        "Perfect balance of energy and taste!",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "faq")
async def faq(callback: CallbackQuery):
    await callback.message.edit_text(
        "❓ Frequently Asked Questions:",
        reply_markup=faq_keyboard()
    )

@dp.callback_query(F.data.startswith("faq:"))
async def faq_answer(callback: CallbackQuery):
    question = callback.data.split("faq:")[1]
    await callback.message.edit_text(
        f"<b>{question}</b>\n\n{FAQ[question]}",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "location")
async def location(callback: CallbackQuery):
    await callback.message.edit_text(
        "📍 <b>Campus Café Location</b>\n\n"
        "Main campus\nBuilding A, first floor",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

import requests
from langdetect import detect

# =======================
# GIGACHAT TOKEN MANAGEMENT
# =======================
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "postgres",
    "user": "pro100kir2",
    "password": ""
}

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

# =======================
# TOKEN TABLE
# =======================
# SQL для создания таблицы:
# CREATE TABLE gigachat_token (
#     id SERIAL PRIMARY KEY,
#     access_token TEXT,
#     updated_at TIMESTAMP DEFAULT NOW()
# );

def fetch_token_from_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT access_token FROM gigachat_token ORDER BY updated_at DESC LIMIT 1;")
    token = cur.fetchone()
    cur.close()
    conn.close()
    return token[0] if token else None

def update_token_in_db(new_token):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO gigachat_token (access_token) VALUES (%s);", (new_token,))
    conn.commit()
    cur.close()
    conn.close()
    logging.info("🔄 GigaChat token updated in DB")

gigachat_token_info = {"access_token": None, "expires_at": 0}

def get_gigachat_token():
    """Каждый раз обновляем токен, даже если он существует"""
    return refresh_gigachat_token()  # Принудительно обновляем токен

def refresh_gigachat_token():
    """Запрашивает новый токен и сохраняет его в памяти и БД"""
    now = time.time()

    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    payload = {'scope': GIGACHAT_SCOPE}
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'RqUID': str(uuid.uuid4()),
        'Authorization': f'Basic {GIGACHAT_BASIC_KEY}'
    }

    try:
        r = requests.post(url, headers=headers, data=payload, verify=False)
        r.raise_for_status()
        data = r.json()
        access_token = data.get("access_token")
        expires_in = data.get("expires_in", 200)

        if access_token:
            # Очистка старого токена из БД
            clear_old_token_from_db()

            # Обновляем токен в памяти и БД
            gigachat_token_info["access_token"] = access_token
            gigachat_token_info["expires_at"] = now + expires_in
            update_token_in_db(access_token)

            logging.info("✅ GigaChat token refreshed")
            return access_token
    except Exception as e:
        logging.error(f"⚠ Failed to refresh token: {e}")
        return None

def clear_old_token_from_db():
    """Удаляет старый токен из БД"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM gigachat_token;")
    conn.commit()
    cur.close()
    conn.close()
    logging.info("🔄 Old GigaChat token cleared from DB")

def init_gigachat_token():
    """Запрашивает новый токен и сохраняет его в памяти и БД"""
    logging.info("🔹 Forcing GigaChat token refresh...")
    token = refresh_gigachat_token()
    if not token:
        logging.error("❌ Failed to initialize GigaChat token")
    else:
        logging.info(f"✅ GigaChat token initialized: {token[:10]}...")
    return token
def call_gigachat_model(user_text, system_text="You are a professional coffee consultant. Answer in English based ONLY on coffee drinks and café items."):
    access_token = get_gigachat_token()  # Токен обновляется каждый раз
    if not access_token:
        logging.error("⚠ No GigaChat token available")
        return "❌ No token available"

    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    payload = {
        "model": "GigaChat-2",
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text}
        ],
        "stream": False,
        "update_interval": 0
    }

    logging.info(f"🌐 Sending request to GigaChat: {url}")
    logging.info(f"Headers: {headers}")
    logging.info(f"Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")

    try:
        response = requests.post(url, headers=headers, json=payload, verify=False)
        logging.info(f"HTTP status: {response.status_code}")
        logging.info(f"Response text: {response.text}")

        response.raise_for_status()  # выбросит исключение, если код ответа не 2xx
        data = response.json()
        # В новой версии API ответ лежит в choices[0]['message']['content']
        answer = data['choices'][0]['message']['content']
        return answer
    except requests.RequestException as e:
        logging.error(f"⚠ RequestException: {e}")
        return f"❌ RequestException: {e}"
    except KeyError:
        logging.error(f"⚠ Unexpected response format: {response.text}")
        return f"❌ Unexpected response format: {response.text}"


def token_updater():
    """Фоновый поток для обновления токена каждые 27,5 минут"""
    while True:
        try:
            get_gigachat_token()
        except Exception as e:
            logging.error(f"⚠ Failed to update token: {e}")
        time.sleep(1650)

# Запускаем фоновый поток
threading.Thread(target=token_updater, daemon=True).start()

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

class CoffeeConsultantStates(StatesGroup):
    waiting_for_question = State()


@dp.callback_query(F.data == "consult_coffee")
async def coffee_consult(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "💬 Ask a question to the coffee consultant:\nI will answer based on our menu and café offerings."
    )
    await state.set_state(CoffeeConsultantStates.waiting_for_question)
    await callback.answer()


@dp.message(CoffeeConsultantStates.waiting_for_question)
async def coffee_answer(message: Message, state: FSMContext):
    answer = call_gigachat_model(message.text)
    await message.answer(f"☕ Coffee Consultant:\n{answer}")
    await state.clear()

# ======================
# ▶️ START BOT
# ======================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    init_gigachat_token()
    asyncio.run(main())
