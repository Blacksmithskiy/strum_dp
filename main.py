import os
import re
import time
import json
import asyncio
import random
import io
import logging
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# === 1. НАЛАШТУВАННЯ ТА ІНІЦІАЛІЗАЦІЯ ===
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

CHANNEL_USERNAME = "@strum_dp"
SIREN_CHANNEL_USER = "sirena_dp"
MONITOR_THREATS_USER = "hyevuy_dnepr"
MONITOR_SCHEDULE_USER = "dtek_ua" # Тільки офіційний ДТЕК

API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']

# СТВОРЮЄМО КЛІЄНТА ТУТ (Щоб не було помилок)
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# === 2. КОНСТАНТИ ТА ТЕКСТИ ===
URL_MORNING = "https://arcanavisio.com/wp-content/uploads/2026/01/01_MORNING.jpg"
URL_EVENING = "https://arcanavisio.com/wp-content/uploads/2026/01/02_EVENING.jpg"
URL_TREVOGA = "https://arcanavisio.com/wp-content/uploads/2026/01/07_TREVOGA.jpg"
URL_TREVOGA_STOP = "https://arcanavisio.com/wp-content/uploads/2026/01/08_TREVOGA_STOP.jpg"

TXT_TREVOGA = "<b>⚠️❗️ УВАГА! ОГОЛОШЕНО ПОВІТРЯНУ ТРИВОГУ.</b>\n\n🏃 <b>ВСІМ ПРОЙТИ В УКРИТТЯ.</b>"
TXT_TREVOGA_STOP = "<b>✅ ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ.</b>"

FOOTER = """
____

⭐️ <a href="https://t.me/strum_dp">ПІДПИСАТИСЬ НА КАНАЛ</a>
❤️ <a href="https://send.monobank.ua/jar/9gBQ4LTLUa">ПІДТРИМАТИ СЕРВІС</a>

@strum_dp"""

THREAT_TRIGGERS = ["бпла", "шахед", "дрон", "балістика", "вибух", "взрыв", "гучно", "ракета", "атака", "тривога", "загроза", "над містом", "курс на дніпро", "без загроз", "чисто", "розвідник"]
MONTHS_UA = {1: "січня", 2: "лютого", 3: "березня", 4: "квітня", 5: "травня", 6: "червня", 7: "липня", 8: "серпня", 9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня"}
IS_ALARM_ACTIVE = False 

# === 3. ФУНКЦІЇ ===

def format_threat_text(text):
    # Видалення сміття
    text = re.sub(r"(?i)контент.*@hydneprbot", "", text)
    text = re.sub(r"(?i).*@hydneprbot", "", text)
    for junk in ["надслати новину", "прислать новость", "підписатися", "👉"]:
        text = re.sub(f"(?i){re.escape(junk)}", "", text)
    text = "\n".join([l.strip() for l in text.split('\n') if l.strip()])
    
    t_lower = text.lower()
    emoji = "⚡️"
    if any(w in t_lower for w in ["балістика", "ракета"]): emoji = "🚀"
    elif any(w in t_lower for w in ["бпла", "шахед", "дрон"]): emoji = "🦟"
    elif any(w in t_lower for w in ["вибух", "гучно"]): emoji = "💥"
    elif "розвідник" in t_lower: emoji = "👁️"
    elif any(w in t_lower for w in ["відбій", "чисто", "без загроз"]): emoji = "🟢"
    elif "загроза" in t_lower: emoji = "⚠️"
        
    final_text = f"<b>{text.upper()}</b>" if len(text) < 60 else text
    return f"{emoji} {final_text}"

async def process_dtek_image(message_obj):
    # Функція публікації графіку
    now = datetime.now(ZoneInfo("Europe/Kyiv"))
    date_str = f"{now.day} {MONTHS_UA.get(now.month, '')}"
    caption = (
        f"⚡️ ‼️Дніпропетровщина: графіки відключень на {date_str}\n"
        "▪️В разі змін, будемо оперативно вас інформувати у нашому телеграм-каналі.\n"
        "Підписуйтесь та поділіться, будь ласка, з родичами та друзями.\n" + FOOTER
    )
    try:
        msg = await client.send_message(CHANNEL_USERNAME, caption, file=message_obj.media, parse_mode='html')
        if msg: await client.pin_message(CHANNEL_USERNAME, msg, notify=True)
        logger.info("✅ Графік опубліковано")
    except Exception as e:
        logger.error(f"Помилка графіку: {e}")

async def send_safe(text, img_url=None):
    try:
        if img_url:
            r = await asyncio.to_thread(requests.get, img_url, timeout=10)
            if r.status_code == 200:
                f = io.BytesIO(r.content)
                f.name = "img.jpg"
                return await client.send_message(CHANNEL_USERNAME, text + FOOTER, file=f, parse_mode='html')
    except: pass
    return await client.send_message(CHANNEL_USERNAME, text + FOOTER, parse_mode='html')

def get_weather():
    try:
        url = "https://api.open-meteo.com/v1/forecast?latitude=48.46&longitude=35.04&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&current=temperature_2m&timezone=Europe%2FKyiv"
        return requests.get(url, timeout=10).json()
    except: return None

def get_ai_quote(mode):
    # Спрощена заглушка, щоб не перевантажувати код (або поверніть AI якщо треба)
    quotes = ["Ми робимо себе сильними.", "Спокій — це зброя.", "Завтра буде новий день."]
    return random.choice(quotes)

async def send_digest(mode):
    data = await asyncio.to_thread(get_weather)
    w_txt = "🌡 Погода недоступна"
    if data:
        d = data['daily']
        w_txt = f"🌡 Темп: {d['temperature_2m_min'][0]}...{d['temperature_2m_max'][0]}°C, Опади: {d['precipitation_probability_max'][0]}%"
    
    q = get_ai_quote(mode)
    if mode == "morning":
        st = "🔴 Тривога!" if IS_ALARM_ACTIVE else "🟢 Тиша."
        msg = f"<b>☀️ ДОБРОГО РАНКУ!</b>\n\n{w_txt}\n📢 Стан: {st}\n\n<blockquote>{q}</blockquote>"
        await send_safe(msg, URL_MORNING)
    else:
        msg = f"<b>🌒 НА ДОБРАНІЧ!</b>\n\n{w_txt}\n\n<blockquote>{q}</blockquote>"
        await send_safe(msg, URL_EVENING)

# === 4. ХЕНДЛЕРИ (ОБРОБНИКИ) ===

# --- ЗАГРОЗИ (ХД) ---
@client.on(events.NewMessage(chats=MONITOR_THREATS_USER))
async def threat_handler(event):
    text = (event.message.message or "")
    if any(k in text.lower() for k in THREAT_TRIGGERS):
        await client.send_message(CHANNEL_USERNAME, format_threat_text(text) + FOOTER, parse_mode='html')

# --- ГРАФІКИ (ДТЕК ОФІЦІЙНИЙ) ---
@client.on(events.NewMessage(chats=MONITOR_SCHEDULE_USER))
async def dtek_handler(event):
    text = (event.message.message or "").lower()
    if ("дніпро" in text or "дніпропетровщина" in text) and event.message.photo:
        await process_dtek_image(event.message)

# --- ГОЛОВНИЙ (ВИБРАНЕ + КОМАНДИ) ---
@client.on(events.NewMessage())
async def main_handler(event):
    text = (event.message.message or "").lower()
    
    # Фільтр: не реагувати на канали моніторингу тут (вони мають свої хендлери)
    try:
        chat = await event.get_chat()
        if chat and chat.username and chat.username.lower() in [MONITOR_THREATS_USER, MONITOR_SCHEDULE_USER]: return
    except: pass

    if event.out: # Це повідомлення ВІД ВАС (в тому числі в Saved Messages)
        # Команди
        if "test_morning" in text: await send_digest("morning"); return
        if "test_evening" in text: await send_digest("evening"); return
        if "test_threat" in text:
            raw = event.message.message.replace("test_threat", "").strip() or "Тест"
            await client.send_message(CHANNEL_USERNAME, format_threat_text(raw) + FOOTER, parse_mode='html')
            return
        
        # Пересилка ГРАФІКІВ (Вручну в Вибране)
        # Якщо ви переслали картинку і там є ключові слова
        if event.message.photo and any(k in text for k in ["графік", "відключен", "світл", "дтек"]):
            await process_dtek_image(event.message)
            await event.respond("✅ Графік опубліковано!")
            return

    # Сирена
    if chat and chat.username == SIREN_CHANNEL_USER:
        global IS_ALARM_ACTIVE
        if "відбій" in text:
            IS_ALARM_ACTIVE = False
            await send_safe(TXT_TREVOGA_STOP, URL_TREVOGA_STOP)
        elif "тривог" in text:
            IS_ALARM_ACTIVE = True
            await send_safe(TXT_TREVOGA, URL_TREVOGA)

# === 5. ЗАПУСК ===
async def schedule_loop():
    while True:
        now = datetime.now(ZoneInfo("Europe/Kyiv"))
        # Спрощена логіка таймера для надійності
        if now.hour == 8 and now.minute == 0: await send_digest("morning"); await asyncio.sleep(61)
        elif now.hour == 22 and now.minute == 0: await send_digest("evening"); await asyncio.sleep(61)
        await asyncio.sleep(10)

async def startup():
    try:
        await client(JoinChannelRequest(SIREN_CHANNEL_USER))
        await client(JoinChannelRequest(MONITOR_THREATS_USER))
        await client(JoinChannelRequest(MONITOR_SCHEDULE_USER))
        logger.info("✅ Bot Started Successfully.")
    except Exception as e: logger.error(f"Startup warning: {e}")

if __name__ == '__main__':
    client.start()
    client.loop.create_task(schedule_loop())
    client.loop.run_until_complete(startup())
    client.run_until_disconnected()
