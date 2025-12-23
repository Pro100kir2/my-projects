import asyncio
import psycopg2
import logging
import requests
import time
import threading
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
import urllib3
import uuid
import json
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =======================
# CONFIG
# =======================
BOT_TOKEN = "8358990674:AAFVcffmfCvxBOFsAR2dYXOsJJtUQvmzSLY"
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "postgres",
    "user": "pro100kir2",
    "password": ""
}

GIGACHAT_BASIC_KEY = "OTc2OWFkMjEtZGZkZC00ZGRjLTgyNDctMTMxODliMDY0YTM3OjRiNWFhY2RkLWU0YTktNDNhMy1iNjk5LWU1MTY0NmIxNWM0YQ=="
GIGACHAT_SCOPE = "GIGACHAT_API_PERS"

# =======================
# INIT
# =======================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# =======================
# FSM STATES
# =======================
class SearchStates(StatesGroup):
    waiting_for_query = State()

class ConsultantStates(StatesGroup):
    waiting_for_question = State()

# =======================
# DATABASE CONNECTION
# =======================
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

# =======================
# GIGACHAT TOKEN MANAGEMENT
# =======================
gigachat_token_info = {"access_token": None, "expires_at": 0}

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

# =======================
# DATABASE FUNCTIONS
# =======================
def get_categories():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM categories ORDER BY name;")
    data = cur.fetchall()
    cur.close()
    conn.close()
    return data

def get_products_by_category(cat_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT title, description, price, image_url, avito_url, sizes
        FROM products
        WHERE category_id = %s
        ORDER BY id DESC;
    """, (cat_id,))
    data = cur.fetchall()
    cur.close()
    conn.close()
    return data

def search_products(query):
    conn = get_conn()
    cur = conn.cursor()
    like_query = f"%{query}%"
    cur.execute("""
        SELECT title, description, price, image_url, avito_url, sizes
        FROM products
        WHERE title ILIKE %s OR description ILIKE %s
        ORDER BY id DESC
        LIMIT 10;
    """, (like_query, like_query))
    data = cur.fetchall()
    cur.close()
    conn.close()
    return data

def get_all_products_for_llm():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT title, description, price FROM products ORDER BY id DESC LIMIT 30;")
    data = cur.fetchall()
    cur.close()
    conn.close()
    return data

# =======================
# KEYBOARDS
# =======================
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 Categories", callback_data="categories")],
        [InlineKeyboardButton(text="🔍 Search product", callback_data="search")],
        [InlineKeyboardButton(text="💬 Ask consultant", callback_data="consultant")]
    ])

def categories_kb():
    buttons = [[InlineKeyboardButton(text=name, callback_data=f"cat_{cid}")] for cid, name in get_categories()]
    buttons.append([InlineKeyboardButton(text="⬅️ Back", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def product_kb(url):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔗 Open on Avito", url=url)]])

# =======================
# HANDLERS
# =======================
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("👋 Welcome to the showroom!\nI will help you find clothes and answer your questions.",
                         reply_markup=main_menu())

@dp.callback_query(F.data == "back")
async def back(callback: CallbackQuery):
    await callback.message.answer("Main menu:", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "categories")
async def categories(callback: CallbackQuery):
    await callback.message.answer("📂 Select a category:", reply_markup=categories_kb())
    await callback.answer()

@dp.callback_query(F.data.startswith("cat_"))
async def show_products(callback: CallbackQuery):
    cat_id = int(callback.data.split("_")[1])
    products = get_products_by_category(cat_id)
    if not products:
        await callback.message.answer("❌ No products found")
        await callback.answer()
        return
    for title, desc, price, image, url, sizes in products:
        text = f"🛍 <b>{title}</b>\n💰 {price} ₽\n📏 Sizes: {sizes if sizes else '—'}\n\n{desc[:700] if desc else ''}"
        if image:
            await bot.send_photo(callback.message.chat.id, photo=image, caption=text, parse_mode="HTML", reply_markup=product_kb(url))
        else:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=product_kb(url))
    await callback.answer()

# =======================
# SEARCH HANDLERS
# =======================
@dp.callback_query(F.data == "search")
async def search_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🔍 Enter the product name to search:")
    await state.set_state(SearchStates.waiting_for_query)
    await callback.answer()

@dp.message(SearchStates.waiting_for_query)
async def search_handler(message: Message, state: FSMContext):
    query = message.text.strip()
    results = search_products(query)
    if not results:
        await message.answer("❌ No products found")
        await state.clear()
        return
    for title, desc, price, image, url, sizes in results:
        text = f"🛍 <b>{title}</b>\n💰 {price} ₽\n📏 Sizes: {sizes if sizes else '—'}\n\n{desc[:500] if desc else ''}"
        if image:
            await message.answer_photo(photo=image, caption=text, parse_mode="HTML", reply_markup=product_kb(url))
        else:
            await message.answer(text, parse_mode="HTML", reply_markup=product_kb(url))
    await state.clear()

# =======================
# CONSULTANT HANDLERS
# =======================
@dp.callback_query(F.data == "consultant")
async def consultant_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("💬 Ask a question to the consultant.\nI will answer based on available products.")
    await state.set_state(ConsultantStates.waiting_for_question)
    await callback.answer()


def call_gigachat_model(user_text, system_text="You are a professional showroom consultant. Answer based ONLY on the product list below."):
    access_token = get_gigachat_token()
    if not access_token:
        return "❌ No token available"

    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    headers = {"Content-Type": "application/json", "Accept": "application/json", "Authorization": f"Bearer {access_token}"}
    payload = {
        "model": "GigaChat-2",
        "messages": [{"role": "system", "content": system_text}, {"role": "user", "content": user_text}],
        "stream": False,
        "update_interval": 0
    }

    try:
        r = requests.post(url, headers=headers, json=payload, verify=False)
        if r.status_code == 401:
            logging.info("Token expired, refreshing...")
            access_token = refresh_gigachat_token()
            if not access_token:
                return "❌ Failed to refresh token"
            headers["Authorization"] = f"Bearer {access_token}"
            r = requests.post(url, headers=headers, json=payload, verify=False)

        r.raise_for_status()
        data = r.json()
        return data['choices'][0]['message']['content']
    except Exception as e:
        logging.error(f"⚠ GigaChat request failed: {e}")
        return f"❌ {e}"

@dp.message(ConsultantStates.waiting_for_question)
async def consultant_answer(message: Message, state: FSMContext):
    products = get_all_products_for_llm()
    context = "\n".join([f"- {t} | {p} ₽ | {d[:200] if d else ''}" for t, d, p in products])
    prompt = f"""
You are a showroom consultant.
Answer ONLY based on the product list below.
Do NOT invent products.

Products:
{context}

Customer question:
{message.text}
"""
    answer = call_gigachat_model(prompt)
    await message.answer(f"🧑‍💼 Consultant:\n{answer}")
    await state.clear()

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

def update_token_in_db(new_token):
    """Обновляет токен в БД"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO gigachat_token (access_token) VALUES (%s);", (new_token,))
    conn.commit()
    cur.close()
    conn.close()
    logging.info("🔄 GigaChat token updated in DB")

def init_gigachat_token():
    """Запрашивает новый токен и сохраняет его в памяти и БД"""
    logging.info("🔹 Forcing GigaChat token refresh...")
    token = refresh_gigachat_token()
    if not token:
        logging.error("❌ Failed to initialize GigaChat token")
    else:
        logging.info(f"✅ GigaChat token initialized: {token[:10]}...")
    return token

def get_gigachat_token():
    """Получает свежий токен (удаляет старый и запрашивает новый)"""
    return refresh_gigachat_token()


# =======================
# RUN
# =======================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    init_gigachat_token()
    asyncio.run(main())