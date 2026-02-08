import os
import re
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

# === 1. НАСТРОЙКИ ===
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

CHANNEL_USERNAME = "@strum_dp"
SIREN_CHANNEL_USER = "sirena_dp"
MONITOR_THREATS_USER = "hyevuy_dnepr"
MONITOR_SCHEDULE_USER = "avariykaaa" 
DTEK_OFFICIAL = "dtek_ua"

MY_GROUP = "1.1" # Ваша группа

API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']
GEMINI_KEY = os.environ['GEMINI_API_KEY']

# Создаем клиента сразу
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# === 2. КОНСТАНТЫ ===
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

# Строгий фильтр угроз
STRICT_THREATS = ["ракета", "балістика", "пуск", "бпла", "шахед", "дрон", "тривога", "відбій", "загроза"]
MONTHS_UA = {1: "січня", 2: "лютого", 3: "березня", 4: "квітня", 5: "травня", 6: "червня", 7: "липня", 8: "серпня", 9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня"}
IS_ALARM_ACTIVE = False 

# === 3. GOOGLE TASKS ===
async def create_calendar_tasks(schedule_list):
    """Создает задачи"""
    try:
        creds = Credentials.from_authorized_user_info(json.loads(GOOGLE_TOKEN))
        service = build('tasks', 'v1', credentials=creds)
        
        kyiv_tz = ZoneInfo("Europe/Kyiv")
        now = datetime.now(kyiv_tz)

        count = 0
        for item in schedule_list:
            start_str, end_str = item['start'], item['end']
            
            # Определяем дату
            start_dt = datetime.strptime(start_str, "%H:%M").replace(year=now.year, month=now.month, day=now.day, tzinfo=kyiv_tz)
            
            # Если время в графике (например 02:00) меньше текущего времени (20:00), то это график на завтра
            if start_dt.hour < now.hour and now.hour > 18:
                start_dt += timedelta(days=1)
            # Если время уже прошло сегодня, не создаем задачу
            elif start_dt < now:
                continue

            # Время для API (UTC)
            due_utc = start_dt.astimezone(ZoneInfo("UTC")).strftime('%Y-%m-%dT%H:%M:%S.000Z')

            task_body = {
                'title': f"⚡️ ОТКЛЮЧЕНИЕ {start_str}",
                'notes': f"Группа {MY_GROUP}. Свет отключат с {start_str} до {end_str}.",
                'due': due_utc
            }
            
            service.tasks().insert(tasklist='@default', body=task_body).execute()
            count += 1
        
        logger.info(f"✅ Создано {count} задач в Google Tasks")
            
    except Exception as e:
        logger.error(f"Google Tasks Error: {e}")

# === 4. ОБРАБОТКА ТЕКСТА ===
def clean_message(text):
    # Замена тире на стандартные
    text = text.replace("—", "-").replace("–", "-")
    
    # Удаление рекламы
    text = re.sub(r"(?i)контент.*@hydneprbot", "", text)
    text = re.sub(r"(?i).*@hydneprbot", "", text)
    for junk in ["надслати новину", "прислать новость", "підписатися", "👉", "https://t.me/avariykaaa"]:
        text = re.sub(f"(?i){re.escape(junk)}", "", text)
    
    return "\n".join([l.strip() for l in text.split('\n') if l.strip()])

def parse_text_schedule(text):
    """Парсит время для группы 1.1"""
    schedule = []
    text = text.replace("—", "-").replace("–", "-") # Нормализация тире
    
    # Ищем строки, где есть 1.1
    lines = text.split('\n')
    for line in lines:
        if MY_GROUP in line:
            # Ищем время вида 00:00-00:00
            times = re.findall(r'(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})', line)
            for start, end in times:
                if end == "24:00": end = "23:59"
                schedule.append({'start': start, 'end': end})
    return schedule

def format_threat_text(text):
    clean = clean_message(text)
    t_lower = clean.lower()
    emoji = "⚡️"
    if "ракета" in t_lower or "балістика" in t_lower: emoji = "🚀"
    elif "бпла" in t_lower or "шахед" in t_lower: emoji = "🦟"
    elif "тривога" in t_lower: emoji = "⚠️"
    elif "відбій" in t_lower: emoji = "🟢"
    
    final_text = f"<b>{clean.upper()}</b>" if len(clean) < 100 else clean
    return f"{emoji} {final_text}"

# === 5. ОТПРАВКА ===
async def send_safe(text, img_url=None):
    try:
        if img_url:
            r = await asyncio.to_thread(requests.get, img_url, timeout=10)
            if r.status_code == 200:
                f = io.BytesIO(r.content)
                f.name = "img.jpg"
                return await client.send_message(CHANNEL_USERNAME, text + FOOTER, file=f, parse_mode='html')
    except Exception as e:
        logger.error(f"Error sending media: {e}")
    
    return await client.send_message(CHANNEL_USERNAME, text + FOOTER, parse_mode='html')

def get_weather():
    try:
        url = "https://api.open-meteo.com/v1/forecast?latitude=48.46&longitude=35.04&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&current=temperature_2m&timezone=Europe%2FKyiv"
        return requests.get(url, timeout=10).json()
    except: return None

def get_ai_quote(mode):
    # Генератор цитат (чтобы не зависеть от AI)
    quotes = [
        "Темрява не може затьмарити наше внутрішнє світло.",
        "Спокій — це найсильніший щит.",
        "Кожен світанок дарує нову надію.",
        "Ми сильніші, ніж думаємо.",
        "Світло завжди перемагає."
    ]
    return random.choice(quotes)

async def send_digest(mode):
    logger.info(f"Preparing {mode} digest...")
    data = await asyncio.to_thread(get_weather)
    w_txt = "🌡 Погода тимчасово недоступна"
    
    if data:
        d = data['daily']
        if mode == "morning":
            w_txt = f"🌡 Температура: {d['temperature_2m_min'][0]}...{d['temperature_2m_max'][0]}°C\n☔️ Опади: {d['precipitation_probability_max'][0]}%"
        else:
            w_txt = f"🌡 Завтра: {d['temperature_2m_min'][1]}...{d['temperature_2m_max'][1]}°C"
    
    q = get_ai_quote(mode)
    if mode == "morning":
        st = "🔴 Тривога активна!" if IS_ALARM_ACTIVE else "🟢 Небо чисте."
        msg = f"<b>☀️ ДОБРОГО РАНКУ, ДНІПРО!</b>\n\n{w_txt}\n📢 Стан: {st}\n\n<blockquote>{q}</blockquote>"
        await send_safe(msg, URL_MORNING)
    else:
        msg = f"<b>🌒 НА ДОБРАНІЧ, ДНІПРО!</b>\n\n{w_txt}\n\n<blockquote>{q}</blockquote>\n\n🔋 Не забудьте зарядити гаджети."
        await send_safe(msg, URL_EVENING)
    logger.info(f"{mode} digest sent.")

# === 6. ХЕНДЛЕРЫ ===

@client.on(events.NewMessage(chats=MONITOR_THREATS_USER))
async def threat_handler(event):
    text = (event.message.message or "")
    text_lower = text.lower()
    
    if "hydneprbot" in text_lower: return # Игнор рекламы

    if any(k in text_lower for k in STRICT_THREATS):
        logger.info(f"⚠️ THREAT DETECTED: {text[:20]}...")
        clean = clean_message(text)
        await client.send_message(CHANNEL_USERNAME, format_threat_text(clean) + FOOTER, parse_mode='html')

@client.on(events.NewMessage(chats=MONITOR_SCHEDULE_USER))
async def schedule_text_handler(event):
    text = (event.message.message or "")
    
    # Проверка на наличие группы 1.1 и времени в тексте
    if MY_GROUP in text and re.search(r'\d{1,2}:\d{2}', text):
        logger.info("📝 SCHEDULE FOUND in Avariyka!")
        
        # 1. Задачи
        schedule = parse_text_schedule(text)
        if schedule:
            await create_calendar_tasks(schedule)
        
        # 2. Публикация
        try:
            caption = clean_message(text) + FOOTER
            if event.message.media:
                await client.send_message(CHANNEL_USERNAME, caption, file=event.message.media, parse_mode='html')
            else:
                await client.send_message(CHANNEL_USERNAME, caption, parse_mode='html')
            logger.info("✅ Schedule posted.")
        except Exception as e:
            logger.error(f"Post error: {e}")

@client.on(events.NewMessage(chats=DTEK_OFFICIAL))
async def dtek_handler(event):
    # Офиц. ДТЕК: берем только картинки с упоминанием области
    text = (event.message.message or "").lower()
    if ("дніпро" in text or "дніпропетровщина" in text) and event.message.photo:
        logger.info("⚡️ DTEK Official Post Detected")
        await client.send_message(CHANNEL_USERNAME, event.message)

@client.on(events.NewMessage())
async def main_handler(event):
    # Хендлер для тестов (личные сообщения или Избранное)
    try:
        chat = await event.get_chat()
        if chat and chat.username and chat.username.lower() in [MONITOR_THREATS_USER, MONITOR_SCHEDULE_USER, DTEK_OFFICIAL]: return
    except: pass

    if event.out:
        text = event.message.message or ""
        if "test_morning" in text:
            await event.respond("Test Morning...")
            await send_digest("morning")
        elif "test_evening" in text:
            await event.respond("Test Evening...")
            await send_digest("evening")
        elif "test_threat" in text:
            await event.respond("Test Threat...")
            t = text.replace("test_threat", "").strip() or "Ракетна небезпека"
            await client.send_message(CHANNEL_USERNAME, format_threat_text(t) + FOOTER, parse_mode='html')

    # Сирена (автомат)
    if chat and chat.username == SIREN_CHANNEL_USER:
        global IS_ALARM_ACTIVE
        text = event.message.message.lower()
        if "відбій" in text:
            IS_ALARM_ACTIVE = False
            await send_safe(TXT_TREVOGA_STOP, URL_TREVOGA_STOP)
        elif "тривог" in text:
            IS_ALARM_ACTIVE = True
            await send_safe(TXT_TREVOGA, URL_TREVOGA)

# === 7. ЗАПУСК ===
async def scheduler():
    logger.info("🕒 Scheduler initiated...")
    while True:
        now = datetime.now(ZoneInfo("Europe/Kyiv"))
        
        # Вычисляем время до 8:00 утра
        target_morning = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now >= target_morning: target_morning += timedelta(days=1)
        
        # Вычисляем время до 22:00 вечера
        target_evening = now.replace(hour=22, minute=0, second=0, microsecond=0)
        if now >= target_evening: target_evening += timedelta(days=1)
        
        # Ближайшее событие
        next_event = min(target_morning, target_evening)
        sleep_seconds = (next_event - now).total_seconds()
        
        logger.info(f"💤 Sleeping {int(sleep_seconds)}s until {next_event.strftime('%H:%M')}")
        await asyncio.sleep(sleep_seconds)
        
        # Выполняем действие
        if next_event.hour == 8:
            await send_digest("morning")
        else:
            await send_digest("evening")
            
        await asyncio.sleep(60) # Ждем минуту, чтобы не сработать дважды

async def startup():
    try:
        # Обновляем список диалогов, чтобы точно видеть каналы
        await client(JoinChannelRequest(MONITOR_THREATS_USER))
        await client(JoinChannelRequest(MONITOR_SCHEDULE_USER))
        logger.info("✅ BOT STARTED. LISTENING...")
    except Exception as e:
        logger.error(f"Startup warning: {e}")

if __name__ == '__main__':
    client.start()
    client.loop.create_task(scheduler())
    client.loop.run_until_complete(startup())
    client.run_until_disconnected()
