import os
import re
import json
import asyncio
import logging
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# === 1. НАЛАШТУВАННЯ ===
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

CHANNEL_USERNAME = "@strum_dp"
SIREN_CHANNEL_USER = "sirena_dp"
MONITOR_THREATS_USER = "hyevuy_dnepr"
MONITOR_SCHEDULE_USER = "avariykaaa" # Повернули Аварійку для тексту
DTEK_OFFICIAL = "dtek_ua" # Залишили ДТЕК для офіційних картинок

MY_GROUP = "1.1" # Ваша група

API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']
GEMINI_KEY = os.environ['GEMINI_API_KEY'] # Поки не використовуємо, але хай буде

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# === 2. ФІЛЬТРИ ===
# Суворий фільтр: тільки реальна бойова небезпека
STRICT_THREATS = [
    "ракета", "балістика", "пуск", 
    "бпла", "шахед", "дрон", "мопед",
    "тривога", "відбій"
]

# === 3. GOOGLE TASKS (КАЛЕНДАР) ===
async def create_calendar_tasks(schedule_list):
    """Створює задачі з парсингу тексту"""
    try:
        creds = Credentials.from_authorized_user_info(json.loads(GOOGLE_TOKEN))
        service = build('tasks', 'v1', credentials=creds)
        
        kyiv_tz = ZoneInfo("Europe/Kyiv")
        now = datetime.now(kyiv_tz)

        for item in schedule_list:
            start_str, end_str = item['start'], item['end']
            
            # Визначаємо дату (сьогодні чи завтра)
            # Якщо графік прийшов ввечері (після 20:00), а час ранковий (до 10:00) - це на завтра
            start_dt = datetime.strptime(start_str, "%H:%M").replace(year=now.year, month=now.month, day=now.day, tzinfo=kyiv_tz)
            if now.hour >= 20 and start_dt.hour < 10:
                start_dt += timedelta(days=1)
            
            # Час сповіщення (за 10 хв до початку)
            notify_dt = start_dt - timedelta(minutes=10)
            
            # Якщо час вже минув - не створюємо
            if notify_dt < now:
                continue

            # Конвертація в UTC для Google API (RFC3339)
            due_utc = notify_dt.astimezone(ZoneInfo("UTC")).strftime('%Y-%m-%dT%H:%M:%S.000Z')

            task_body = {
                'title': f"⚡️ СВІТЛО OFF: {start_str}",
                'notes': f"Відключення: {start_str} - {end_str}. Перевірте зарядне.",
                'due': due_utc
            }
            
            service.tasks().insert(tasklist='@default', body=task_body).execute()
            logger.info(f"✅ Задача створена: {start_str} (Сповіщення о {notify_dt.strftime('%H:%M')})")
            
    except Exception as e:
        logger.error(f"Google Tasks Error: {e}")

# === 4. ПАРСИНГ ТЕКСТУ (АВАРІЙКА) ===
def parse_text_schedule(text):
    """
    Парсит формати типу:
    1.1 06:00-14:30, 18:00-24:00;
    Група 1.1: 06:00-10:00
    """
    schedule = []
    # Шукаємо рядок з нашою групою
    # Regex шукає "1.1" а потім часові діапазони
    pattern = re.compile(rf"{re.escape(MY_GROUP)}.*?(\d{{1,2}}:\d{{2}}\s*[-–]\s*\d{{1,2}}:\d{{2}})")
    
    # Розбиваємо на рядки, бо в одному пості багато груп
    lines = text.split('\n')
    for line in lines:
        if MY_GROUP in line:
            # Знаходимо всі часові проміжки в рядку (наприклад: 06:00-14:30 та 18:00-24:00)
            times = re.findall(r'(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})', line)
            for start, end in times:
                # Виправлення 24:00 -> 23:59
                if end == "24:00": end = "23:59"
                schedule.append({'start': start, 'end': end})
    
    return schedule

# === 5. ФОРМАТУВАННЯ ТЕКСТУ ===
def clean_message(text):
    # Видалення реклами
    text = re.sub(r"(?i)контент.*@hydneprbot", "", text)
    text = re.sub(r"(?i).*@hydneprbot", "", text)
    for junk in ["надслати новину", "прислать новость", "підписатися", "👉", "https://t.me/avariykaaa"]:
        text = re.sub(f"(?i){re.escape(junk)}", "", text)
    
    text = "\n".join([l.strip() for l in text.split('\n') if l.strip()])
    
    # Емодзі
    t_lower = text.lower()
    emoji = "⚡️"
    if "ракета" in t_lower or "балістика" in t_lower: emoji = "🚀"
    elif "бпла" in t_lower or "шахед" in t_lower: emoji = "🦟"
    elif "тривога" in t_lower: emoji = "⚠️"
    elif "відбій" in t_lower: emoji = "🟢"
    
    # CAPS для коротких
    final_text = f"<b>{text.upper()}</b>" if len(text) < 100 else text
    return f"{emoji} {final_text}"

FOOTER = """
____

⭐️ <a href="https://t.me/strum_dp">ПІДПИСАТИСЬ НА КАНАЛ</a>
❤️ <a href="https://send.monobank.ua/jar/9gBQ4LTLUa">ПІДТРИМАТИ СЕРВІС</a>

@strum_dp"""

# === 6. ХЕНДЛЕРИ ===

# --- ЗАГРОЗИ (Жорсткий фільтр) ---
@client.on(events.NewMessage(chats=MONITOR_THREATS_USER))
async def threat_handler(event):
    text = (event.message.message or "")
    text_lower = text.lower()
    
    # Якщо це реклама або сміття - ігноруємо
    if "hydneprbot" in text_lower: return

    # Перевірка на ключові слова небезпеки
    if any(k in text_lower for k in STRICT_THREATS):
        clean_text = clean_message(text)
        await client.send_message(CHANNEL_USERNAME, clean_text + FOOTER, parse_mode='html')

# --- ГРАФІКИ (ТЕКСТ з Аварійки) ---
@client.on(events.NewMessage(chats=MONITOR_SCHEDULE_USER))
async def schedule_text_handler(event):
    text = (event.message.message or "")
    
    # 1. Перевіряємо, чи це пост з графіком (шукаємо "1.1" і цифри часу)
    if MY_GROUP in text and re.search(r'\d{2}:\d{2}', text):
        logger.info("📝 Знайдено текстовий графік!")
        
        # Парсимо і ставимо задачі
        schedule = parse_text_schedule(text)
        if schedule:
            await create_calendar_tasks(schedule)
            
        # Публікуємо пост (або пересилаємо картинку, якщо вона є з текстом)
        try:
            caption = clean_message(text) + FOOTER
            if event.message.media:
                await client.send_message(CHANNEL_USERNAME, caption, file=event.message.media, parse_mode='html')
            else:
                await client.send_message(CHANNEL_USERNAME, caption, parse_mode='html')
        except Exception as e:
            logger.error(f"Помилка публікації графіку: {e}")

# --- ГРАФІКИ (Картинки з ДТЕК - як резерв або для краси) ---
@client.on(events.NewMessage(chats=DTEK_OFFICIAL))
async def dtek_handler(event):
    text = (event.message.message or "").lower()
    # Якщо ДТЕК дає картинку і там про Дніпро - беремо
    if ("дніпро" in text or "дніпропетровщина" in text) and event.message.photo:
        await client.send_message(CHANNEL_USERNAME, event.message, parse_mode='html') # Пересилаємо як є або з підписом

# --- РУЧНЕ УПРАВЛІННЯ (Saved Messages) ---
@client.on(events.NewMessage())
async def main_handler(event):
    try:
        chat = await event.get_chat()
        if chat and chat.username and chat.username.lower() in [MONITOR_THREATS_USER, MONITOR_SCHEDULE_USER, DTEK_OFFICIAL]: return
    except: pass

    if event.out:
        text = event.message.message
        # Тест парсингу (перешліть текстовий графік собі в обране)
        if MY_GROUP in text and re.search(r'\d{2}:\d{2}', text):
            schedule = parse_text_schedule(text)
            if schedule:
                await create_calendar_tasks(schedule)
                await event.respond(f"✅ Оброблено! Створено {len(schedule)} нагадувань.")
            else:
                await event.respond("❌ Графік не знайдено в тексті.")

async def startup():
    try:
        await client(JoinChannelRequest(MONITOR_THREATS_USER))
        await client(JoinChannelRequest(MONITOR_SCHEDULE_USER))
        logger.info("✅ Бот запущено. Слухаю Аварійку (текст) і ХД (тільки ракети/шахеди).")
    except: pass

if __name__ == '__main__':
    client.start()
    client.loop.run_until_complete(startup())
    client.run_until_disconnected()
