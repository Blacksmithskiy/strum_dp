import os
import json
import asyncio
import random
import io
import logging
import re
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# === ЛОГУВАННЯ ===
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# === НАЛАШТУВАННЯ ===
CHANNEL_USERNAME = "@strum_dp"
SIREN_CHANNEL_USER = "sirena_dp"
MONITOR_THREATS_USER = "hyevuy_dnepr"
MONITOR_SCHEDULE_USER = "dtek_ua" # Тільки офіційний канал

DNIPRO_LAT = 48.46
DNIPRO_LON = 35.04

# === УКРАЇНСЬКІ МІСЯЦІ ===
MONTHS_UA = {
    1: "січня", 2: "лютого", 3: "березня", 4: "квітня", 5: "травня", 6: "червня",
    7: "липня", 8: "серпня", 9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня"
}

# === ЗМІННІ ===
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']

# === МЕДІА (Для дайджестів та тривог) ===
URL_MORNING = "https://arcanavisio.com/wp-content/uploads/2026/01/01_MORNING.jpg"
URL_EVENING = "https://arcanavisio.com/wp-content/uploads/2026/01/02_EVENING.jpg"
URL_TREVOGA = "https://arcanavisio.com/wp-content/uploads/2026/01/07_TREVOGA.jpg"
URL_TREVOGA_STOP = "https://arcanavisio.com/wp-content/uploads/2026/01/08_TREVOGA_STOP.jpg"
URL_EXTRA_START = "https://arcanavisio.com/wp-content/uploads/2026/01/05_EXTRA_GRAFIC.jpg"
URL_EXTRA_STOP = "https://arcanavisio.com/wp-content/uploads/2026/01/06_EXTRA_STOP.jpg"

# === ТЕКСТИ ===
TXT_TREVOGA = "<b>⚠️❗️ УВАГА! ОГОЛОШЕНО ПОВІТРЯНУ ТРИВОГУ.</b>\n\n🏃 <b>ВСІМ ПРОЙТИ В УКРИТТЯ.</b>"
TXT_TREVOGA_STOP = "<b>✅ ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ.</b>"
TXT_EXTRA_START = "<b>⚡❗️УВАГА! ЗАСТОСОВАНІ ЕКСТРЕНІ ВІДКЛЮЧЕННЯ.</b>\n\n<b>ПІД ЧАС ЕКСТРЕНИХ ВІДКЛЮЧЕНЬ ГРАФІКИ НЕ ДІЮТЬ.</b>"
TXT_EXTRA_STOP = "<b>⚡️✔️ ЕКСТРЕНІ ВІДКЛЮЧЕННЯ СВІТЛА СКАСОВАНІ.</b>"

# === ТРИГЕРИ ЗАГРОЗ (ХД) ===
THREAT_TRIGGERS = [
    "бпла", "шахед", "дрон", 
    "балістика", "балистика",
    "вибух", "взрыв",
    "гучно", "громко",
    "ракета", "атака",
    "тривога", "тревога",
    "загроза", "угроза",
    "над містом", "над городом",
    "курс на дніпро", "курсом на дніпро",
    "без загроз", "чисто", "розвідник"
]

# === ФУТЕР ===
FOOTER = """
____

⭐️ <a href="https://t.me/strum_dp">ПІДПИСАТИСЬ НА КАНАЛ</a>
❤️ <a href="https://send.monobank.ua/jar/9gBQ4LTLUa">ПІДТРИМАТИ СЕРВІС</a>

@strum_dp"""

# === ЦИТАТИ ===
BACKUP_MORNING = [
    "Той, хто має «Навіщо» жити, витримає майже будь-яке «Як».",
    "Ми робимо себе або сильними, або нещасними. Кількість зусиль однакова.",
    "Я — не те, що зі мною сталося. Я — те, ким я обираю стати."
]
BACKUP_EVENING = [
    "День завершено. Відпусти турботи, як дерево скидає сухе листя.",
    "Сон — це найкраща медитація.",
    "Навіть найтемніша ніч закінчується світанком. Відпочивай."
]

REAL_SIREN_ID = None
IS_ALARM_ACTIVE = False 
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# === AI ===
def get_ai_quote(mode="morning"):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_KEY}"
    prompt = "Напиши одну коротку, глибоку думку (стоїцизм/психологія) для українців. Українська мова. До 15 слів. Без лапок."
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        r = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=5)
        if r.status_code == 200:
            return r.json()['candidates'][0]['content']['parts'][0]['text'].strip().replace('"', '').replace('*', '')
    except: pass
    return random.choice(BACKUP_MORNING if mode == "morning" else BACKUP_EVENING)

# === ПОГОДА ===
def get_weather():
    url = f"https://api.open-meteo.com/v1/forecast?latitude={DNIPRO_LAT}&longitude={DNIPRO_LON}&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&current=temperature_2m,wind_speed_10m&timezone=Europe%2FKyiv"
    for _ in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200: return r.json()
        except: time.sleep(2)
    return None

# === ВІДПРАВКА ===
async def send_safe(text, img_url):
    try:
        response = await asyncio.to_thread(requests.get, img_url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            photo_file = io.BytesIO(response.content)
            photo_file.name = "image.jpg"
            return await client.send_message(CHANNEL_USERNAME, text + FOOTER, file=photo_file, parse_mode='html')
    except Exception as e:
        logger.warning(f"Image download failed: {e}")
    try:
        return await client.send_message(CHANNEL_USERNAME, text + FOOTER, parse_mode='html')
    except Exception as e:
        logger.error(f"Text send failed: {e}")
        return None

# === ДАЙДЖЕСТИ ===
async def send_morning_digest():
    data = await asyncio.to_thread(get_weather)
    w_text = "🌡 <b>Погода:</b> Тимчасово недоступна."
    if data:
        d = data['daily']
        w_text = f"🌡 <b>Температура:</b> {d['temperature_2m_min'][0]}°C ... {d['temperature_2m_max'][0]}°C\n☔️ <b>Опади:</b> {d['precipitation_probability_max'][0]}%"
    
    status = "🔴 Тривога активна!" if IS_ALARM_ACTIVE else "🟢 Небо чисте."
    quote = await asyncio.to_thread(get_ai_quote, "morning")
    msg = f"<b>☀️ ДОБРОГО РАНКУ, ДНІПРО!</b>\n\n{w_text}\n\n📢 <b>Статус повітряної тривоги:</b> {status}\n\n<blockquote>{quote}</blockquote>"
    await send_safe(msg, URL_MORNING)

async def send_evening_digest():
    data = await asyncio.to_thread(get_weather)
    w_text = "🌡 <b>Погода на завтра:</b> Дані оновлюються."
    if data:
        d = data['daily']
        w_text = f"🌡 <b>Погода на завтра:</b> {d['temperature_2m_min'][1]}°C ... {d['temperature_2m_max'][1]}°C"

    quote = await asyncio.to_thread(get_ai_quote, "evening")
    msg = f"<b>🌒 НА ДОБРАНІЧ, ДНІПРО!</b>\n\n{w_text}\n\n<blockquote>{quote}</blockquote>\n\n🔋 Не забудьте перевірити заряд гаджетів."
    await send_safe(msg, URL_EVENING)

# === МОНІТОР АЛЕРТІВ ===
async def check_weather_alerts(test_mode=False):
    data = await asyncio.to_thread(get_weather)
    if not data: 
        if test_mode: await client.send_message(CHANNEL_USERNAME, "⚠️ Помилка погоди.", parse_mode='html')
        return
    curr = data.get('current', {})
    if test_mode:
        await client.send_message(CHANNEL_USERNAME, f"🧪 <b>ТЕСТ ПОГОДИ:</b> {curr.get('temperature_2m')}°C", parse_mode='html')

# === ФОРМАТУВАННЯ ЗАГРОЗ ===
def format_threat_text(text):
    text = re.sub(r"(?i)контент.*@hydneprbot", "", text)
    text = re.sub(r"(?i).*@hydneprbot", "", text)
    junk = ["надслати новину", "прислать новость", "підписатися", "👉"]
    for j in junk: text = re.sub(f"(?i){re.escape(j)}", "", text)
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

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# === 1. ОБРОБКА ГРАФІКІВ (ДТЕК) ===
@client.on(events.NewMessage(chats=MONITOR_SCHEDULE_USER))
async def dtek_handler(event):
    text = (event.message.message or "").lower()
    
    # Фільтр: Тільки якщо це стосується Дніпропетровщини
    if "дніпро" in text or "дніпропетровщина" in text:
        if event.message.photo:
            # Формуємо дату (сьогоднішня)
            now = datetime.now(ZoneInfo("Europe/Kyiv"))
            day = now.day
            month_name = MONTHS_UA.get(now.month, "")
            
            # Ваш шаблон тексту
            caption = (
                f"⚡️ ‼️Дніпропетровщина: графіки відключень на {day} {month_name}\n"
                "▪️В разі змін, будемо оперативно вас інформувати у нашому телеграм-каналі.\n"
                "Підписуйтесь та поділіться, будь ласка, з родичами та друзями.\n"
                "____\n\n"
                "⭐️ <a href=\"https://t.me/strum_dp\">ПІДПИСАТИСЬ НА КАНАЛ</a>\n"
                "❤️ <a href=\"https://send.monobank.ua/jar/9gBQ4LTLUa\">ПІДТРИМАТИ СЕРВІС</a>\n\n"
                "@strum_dp"
            )
            
            try:
                # Пересилаємо тільки фото з новим підписом
                msg = await client.send_message(CHANNEL_USERNAME, caption, file=event.message.media, parse_mode='html')
                if msg:
                    await client.pin_message(CHANNEL_USERNAME, msg, notify=True)
                    logger.info(f"✅ DTEK Schedule posted for {day} {month_name}")
            except Exception as e:
                logger.error(f"Failed to post DTEK schedule: {e}")

# === 2. ОБРОБКА ЗАГРОЗ (ХД) ===
@client.on(events.NewMessage(chats=MONITOR_THREATS_USER))
async def threat_handler(event):
    text = (event.message.message or "")
    text_lower = text.lower()
    
    if any(trigger in text_lower for trigger in THREAT_TRIGGERS):
        try:
            formatted_text = format_threat_text(text)
            await client.send_message(CHANNEL_USERNAME, formatted_text + FOOTER, parse_mode='html')
        except Exception as e:
            logger.error(f"Threat repost failed: {e}")

# === 3. СИСТЕМА (СИРЕНИ, ТЕСТИ, ТАЙМЕРИ) ===
@client.on(events.NewMessage())
async def main_handler(event):
    try:
        chat = await event.get_chat()
        username = chat.username.lower() if chat and hasattr(chat, 'username') and chat.username else ""
        if username in [MONITOR_THREATS_USER.lower(), MONITOR_SCHEDULE_USER.lower()]: return
    except: username = ""
    
    text = (event.message.message or "").lower()
    
    # ТЕСТИ
    if event.out:
        if "test_morning" in text: await send_morning_digest(); return
        if "test_evening" in text: await send_evening_digest(); return
        if "test_weather" in text: await check_weather_alerts(test_mode=True); return
        if "test_siren" in text:
            global IS_ALARM_ACTIVE
            if "відбій" in text or "отбой" in text:
                IS_ALARM_ACTIVE = False
                await send_safe(TXT_TREVOGA_STOP, URL_TREVOGA_STOP)
            else:
                IS_ALARM_ACTIVE = True
                await send_safe(TXT_TREVOGA, URL_TREVOGA)
            return

    # СИРЕНА
    is_siren = False
    if REAL_SIREN_ID and event.chat_id == REAL_SIREN_ID: is_siren = True
    if username == SIREN_CHANNEL_USER: is_siren = True
    
    if is_siren:
        if "відбій" in text or "отбой" in text:
            IS_ALARM_ACTIVE = False
            await send_safe(TXT_TREVOGA_STOP, URL_TREVOGA_STOP)
        elif "тривог" in text or "тревога" in text:
            IS_ALARM_ACTIVE = True
            await send_safe(TXT_TREVOGA, URL_TREVOGA)
        return

    # ЕКСТРЕНІ (Ручні команди)
    if "екстрені" in text or "экстренные" in text:
        if "скасовані" in text or "отмена" in text:
            await send_safe(TXT_EXTRA_STOP, URL_EXTRA_STOP)
        else:
            await send_safe(TXT_EXTRA_START, URL_EXTRA_START)
        return

async def schedule_loop():
    while True:
        now = datetime.now(ZoneInfo("Europe/Kyiv"))
        t_m = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now >= t_m: t_m += timedelta(days=1)
        t_e = now.replace(hour=22, minute=0, second=0, microsecond=0)
        if now >= t_e: t_e += timedelta(days=1)
        next_evt = min(t_m, t_e)
        await asyncio.sleep((next_evt - now).total_seconds())
        if next_evt == t_m: await send_morning_digest()
        else: await send_evening_digest()
        await asyncio.sleep(60)

async def startup():
    global REAL_SIREN_ID
    try:
        await client(JoinChannelRequest(SIREN_CHANNEL_USER))
        e = await client.get_entity(SIREN_CHANNEL_USER)
        REAL_SIREN_ID = int(f"-100{e.id}")
        await client(JoinChannelRequest(MONITOR_THREATS_USER))
        await client(JoinChannelRequest(MONITOR_SCHEDULE_USER))
        logger.info("✅ Bot Started.")
    except Exception as e:
        logger.error(f"Startup Error: {e}")

if __name__ == '__main__':
    client.start()
    client.loop.create_task(schedule_loop())
    client.loop.create_task(check_weather_alerts())
    client.loop.run_until_complete(startup())
    client.run_until_disconnected()
