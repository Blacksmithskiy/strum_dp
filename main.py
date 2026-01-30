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

# === ЛОГУВАННЯ ===
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# === НАЛАШТУВАННЯ ===
CHANNEL_USERNAME = "@strum_dp"
SIREN_CHANNEL_USER = "sirena_dp"
MONITOR_THREATS_USER = "hyevuy_dnepr"
MONITOR_SCHEDULE_USER = "dtek_ua" # Офіційний канал

DNIPRO_LAT = 48.46
DNIPRO_LON = 35.04

# === ЗМІННІ СЕРЕДОВИЩА ===
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']

# === ІНІЦІАЛІЗАЦІЯ КЛІЄНТА (ВАЖЛИВО: ЗВЕРХУ) ===
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# === МЕДІА ===
URL_MORNING = "https://arcanavisio.com/wp-content/uploads/2026/01/01_MORNING.jpg"
URL_EVENING = "https://arcanavisio.com/wp-content/uploads/2026/01/02_EVENING.jpg"
URL_TREVOGA = "https://arcanavisio.com/wp-content/uploads/2026/01/07_TREVOGA.jpg"
URL_TREVOGA_STOP = "https://arcanavisio.com/wp-content/uploads/2026/01/08_TREVOGA_STOP.jpg"

# === ТЕКСТИ ===
TXT_TREVOGA = "<b>⚠️❗️ УВАГА! ОГОЛОШЕНО ПОВІТРЯНУ ТРИВОГУ.</b>\n\n🏃 <b>ВСІМ ПРОЙТИ В УКРИТТЯ.</b>"
TXT_TREVOGA_STOP = "<b>✅ ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ.</b>"

MONTHS_UA = {1: "січня", 2: "лютого", 3: "березня", 4: "квітня", 5: "травня", 6: "червня", 7: "липня", 8: "серпня", 9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня"}

# === ТРИГЕРИ ЗАГРОЗ ===
THREAT_TRIGGERS = ["бпла", "шахед", "дрон", "балістика", "вибух", "взрыв", "гучно", "ракета", "атака", "тривога", "загроза", "над містом", "курс на дніпро", "без загроз", "чисто", "розвідник"]

# === ФУТЕР ===
FOOTER = """
____

⭐️ <a href="https://t.me/strum_dp">ПІДПИСАТИСЬ НА КАНАЛ</a>
❤️ <a href="https://send.monobank.ua/jar/9gBQ4LTLUa">ПІДТРИМАТИ СЕРВІС</a>

@strum_dp"""

# === ЦИТАТИ ===
BACKUP_MORNING = ["Ми робимо себе або сильними, або нещасними. Кількість зусиль однакова.", "Там, де страх, місця немає творчості.", "Спокій — це теж зброя."]
BACKUP_EVENING = ["День завершено. Відпусти турботи.", "Сон — це найкраща медитація.", "Завтра буде новий день."]

IS_ALARM_ACTIVE = False 
HEADERS = {'User-Agent': 'Mozilla/5.0'}

# === ДОПОМІЖНІ ФУНКЦІЇ ===

def get_ai_quote(mode="morning"):
    # Спроба взяти AI цитату, інакше резерв
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_KEY}"
        payload = {"contents": [{"parts": [{"text": "Напиши одну коротку, глибоку думку (стоїцизм/психологія) для українців. Українська мова. До 15 слів. Без лапок."}]}]}
        r = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=5)
        if r.status_code == 200:
            return r.json()['candidates'][0]['content']['parts'][0]['text'].strip().replace('"', '').replace('*', '')
    except: pass
    return random.choice(BACKUP_MORNING if mode == "morning" else BACKUP_EVENING)

def get_weather():
    for _ in range(2):
        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={DNIPRO_LAT}&longitude={DNIPRO_LON}&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&current=temperature_2m&timezone=Europe%2FKyiv"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200: return r.json()
        except: time.sleep(1)
    return None

async def send_safe(text, img_url=None, file=None):
    # Універсальна відправка: або посилання, або файл, або текст
    try:
        if file:
            return await client.send_message(CHANNEL_USERNAME, text + FOOTER, file=file, parse_mode='html')
        elif img_url:
            response = await asyncio.to_thread(requests.get, img_url, headers=HEADERS, timeout=10)
            if response.status_code == 200:
                f = io.BytesIO(response.content)
                f.name = "img.jpg"
                return await client.send_message(CHANNEL_USERNAME, text + FOOTER, file=f, parse_mode='html')
    except Exception as e:
        logger.error(f"Send media error: {e}")
    
    try:
        return await client.send_message(CHANNEL_USERNAME, text + FOOTER, parse_mode='html')
    except Exception as e:
        logger.error(f"Send text error: {e}")

def format_threat_text(text):
    # Очищення від сміття
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

# === ОБРОБНИКИ ПОДІЙ ===

# 1. ЗАГРОЗИ (ХД)
@client.on(events.NewMessage(chats=MONITOR_THREATS_USER))
async def threat_handler(event):
    text = (event.message.message or "")
    if any(trigger in text.lower() for trigger in THREAT_TRIGGERS):
        try:
            await client.send_message(CHANNEL_USERNAME, format_threat_text(text) + FOOTER, parse_mode='html')
        except: pass

# 2. ГРАФІКИ (ДТЕК ОФІЦІЙНИЙ)
@client.on(events.NewMessage(chats=MONITOR_SCHEDULE_USER))
async def dtek_handler(event):
    text = (event.message.message or "").lower()
    if ("дніпро" in text or "дніпропетровщина" in text) and event.message.photo:
        await process_dtek_image(event.message)

# 3. ОСНОВНИЙ ХЕНДЛЕР (ТЕСТИ, СИРЕНИ, SAVED MESSAGES)
@client.on(events.NewMessage())
async def main_handler(event):
    text = (event.message.message or "").lower()
    chat = await event.get_chat()
    
    # Ігноруємо канали моніторингу (вони обробляються вище)
    if chat and chat.username and chat.username.lower() in [MONITOR_THREATS_USER, MONITOR_SCHEDULE_USER]: return

    # Логіка для вихідних повідомлень (Ваші команди або пересилки в Saved Messages)
    if event.out:
        # КОМАНДИ
        if "test_morning" in text: await send_morning_digest(); return
        if "test_evening" in text: await send_evening_digest(); return
        if "test_weather" in text: await check_weather_alerts(True); return
        
        if "test_siren" in text:
            global IS_ALARM_ACTIVE
            if "відбій" in text or "отбой" in text:
                IS_ALARM_ACTIVE = False
                await send_safe(TXT_TREVOGA_STOP, img_url=URL_TREVOGA_STOP)
            else:
                IS_ALARM_ACTIVE = True
                await send_safe(TXT_TREVOGA, img_url=URL_TREVOGA)
            return
            
        if "test_threat" in text:
            content = event.message.message.replace("test_threat", "").strip() or "Тест загрози"
            await client.send_message(CHANNEL_USERNAME, format_threat_text(content) + FOOTER, parse_mode='html')
            return

        # РУЧНА ПЕРЕСИЛКА ГРАФІКІВ (В Saved Messages)
        # Якщо ви переслали картинку і в ній є слово "графік" або "стабілізаційні"
        if event.message.photo and ("графік" in text or "стабілізаційні" in text or "відключення" in text):
             await process_dtek_image(event.message)
             await event.respond("✅ Графік перехоплено і опубліковано.")

    # СИРЕНА (Автоматична)
    if chat and chat.username == SIREN_CHANNEL_USER:
        if "відбій" in text:
            IS_ALARM_ACTIVE = False
            await send_safe(TXT_TREVOGA_STOP, img_url=URL_TREVOGA_STOP)
        elif "тривог" in text:
            IS_ALARM_ACTIVE = True
            await send_safe(TXT_TREVOGA, img_url=URL_TREVOGA)

# === ФУНКЦІЯ ПУБЛІКАЦІЇ ГРАФІКУ ===
async def process_dtek_image(message_obj):
    now = datetime.now(ZoneInfo("Europe/Kyiv"))
    date_str = f"{now.day} {MONTHS_UA.get(now.month, '')}"
    
    caption = (
        f"⚡️ ‼️Дніпропетровщина: графіки відключень на {date_str}\n"
        "▪️В разі змін, будемо оперативно вас інформувати у нашому телеграм-каналі.\n"
        "Підписуйтесь та поділіться, будь ласка, з родичами та друзями.\n"
        "____\n\n"
        "⭐️ <a href=\"https://t.me/strum_dp\">ПІДПИСАТИСЬ НА КАНАЛ</a>\n"
        "❤️ <a href=\"https://send.monobank.ua/jar/9gBQ4LTLUa\">ПІДТРИМАТИ СЕРВІС</a>\n\n"
        "@strum_dp"
    )
    try:
        msg = await client.send_message(CHANNEL_USERNAME, caption, file=message_obj.media, parse_mode='html')
        if msg: await client.pin_message(CHANNEL_USERNAME, msg, notify=True)
    except Exception as e:
        logger.error(f"DTEK Post Error: {e}")

# === ДАЙДЖЕСТИ ТА ТАЙМЕРИ ===
async def send_morning_digest():
    data = await asyncio.to_thread(get_weather)
    w_t = "🌡 Тимчасово недоступна."
    if data:
        d = data['daily']
        w_t = f"🌡 <b>Температура:</b> {d['temperature_2m_min'][0]}°C ... {d['temperature_2m_max'][0]}°C\n☔️ <b>Опади:</b> {d['precipitation_probability_max'][0]}%"
    
    st = "🔴 Тривога активна!" if IS_ALARM_ACTIVE else "🟢 Небо чисте."
    q = await asyncio.to_thread(get_ai_quote, "morning")
    msg = f"<b>☀️ ДОБРОГО РАНКУ, ДНІПРО!</b>\n\n{w_t}\n\n📢 <b>Статус повітряної тривоги:</b> {st}\n\n<blockquote>{q}</blockquote>"
    await send_safe(msg, img_url=URL_MORNING)

async def send_evening_digest():
    data = await asyncio.to_thread(get_weather)
    w_t = "🌡 Тимчасово недоступна."
    if data:
        d = data['daily']
        w_t = f"🌡 <b>Погода на завтра:</b> {d['temperature_2m_min'][1]}°C ... {d['temperature_2m_max'][1]}°C"
    
    q = await asyncio.to_thread(get_ai_quote, "evening")
    msg = f"<b>🌒 НА ДОБРАНІЧ, ДНІПРО!</b>\n\n{w_t}\n\n<blockquote>{q}</blockquote>\n\n🔋 Не забудьте перевірити заряд гаджетів."
    await send_safe(msg, img_url=URL_EVENING)

async def check_weather_alerts(test_mode=False):
    data = await asyncio.to_thread(get_weather)
    if test_mode and data:
        curr = data.get('current', {}).get('temperature_2m', 'N/A')
        await client.send_message(CHANNEL_USERNAME, f"🧪 ТЕСТ ПОГОДИ: {curr}°C")

async def schedule_loop():
    while True:
        now = datetime.now(ZoneInfo("Europe/Kyiv"))
        t_m = now.replace(hour=8, minute=0, second=0)
        if now >= t_m: t_m += timedelta(days=1)
        t_e = now.replace(hour=22, minute=0, second=0)
        if now >= t_e: t_e += timedelta(days=1)
        
        await asyncio.sleep((min(t_m, t_e) - now).total_seconds())
        if min(t_m, t_e) == t_m: await send_morning_digest()
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
    except Exception as e: logger.error(f"Startup Error: {e}")

if __name__ == '__main__':
    client.start()
    client.loop.create_task(schedule_loop())
    client.loop.create_task(check_weather_alerts())
    client.loop.run_until_complete(startup())
    client.run_until_disconnected()
