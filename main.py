import os
import json
import base64
import time
import re
import requests
import asyncio
from datetime import datetime, timedelta
from dateutil import parser
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# === НАЛАШТУВАННЯ ===
MY_PERSONAL_GROUP = "1.1"  
MAIN_ACCOUNT_USERNAME = "@nemovisio" 
CHANNEL_USERNAME = "@strum_dp"
SIREN_CHANNEL_USER = "sirena_dp" 

# === ПЕРЕМЕННЫЕ ===
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']

IMG_SCHEDULE = "https://arcanavisio.com/wp-content/uploads/2026/01/MAIN.jpg"
IMG_UPDATE = "https://arcanavisio.com/wp-content/uploads/2026/01/UPDATE.jpg"
IMG_EMERGENCY = "https://arcanavisio.com/wp-content/uploads/2026/01/EXTRA.jpg"
IMG_ALARM = "https://arcanavisio.com/wp-content/uploads/2026/01/ALARM.jpg"
IMG_ALL_CLEAR = "https://arcanavisio.com/wp-content/uploads/2026/01/REBOUND.jpg"

REGION_KEYWORDS = ['дніпро', 'дтек', 'дтэк', 'днепр', 'область']
EMERGENCY_WORDS = ['екстрені', 'экстренные', 'скасовані', 'отмена']
UPDATE_WORDS = ['зміни', 'оновлення', 'изменения', 'обновление', 'правки']

processing_lock = asyncio.Lock()
REAL_SIREN_ID = None

async def get_tasks_service():
    creds_dict = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('tasks', 'v1', credentials=creds)

def parse_text_all_groups(text):
    schedule = []
    lines = text.split('\n')
    for line in lines:
        line_lower = line.lower().strip()
        # Ищем группы 1.1, 2.1...
        groups = re.findall(r'(\d\.\d)', line_lower)
        if groups:
            # Ищем время (поддерживаем любые тире и разделители)
            times = re.findall(r'(\d{1,2}:\d{2}).*?(\d{1,2}:\d{2})', line_lower)
            if times:
                today = datetime.now().strftime('%Y-%m-%d')
                for gr in groups:
                    # Убеждаемся, что группа - это не часть времени
                    if any(gr in t for t in times[0]): continue
                    for t in times:
                        schedule.append({
                            "group": gr,
                            "start": f"{today}T{t[0]}:00",
                            "end": f"{today}T{t[1]}:00"
                        })
    return schedule

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage())
async def handler(event):
    text = (event.message.message or "").lower()
    chat_id = event.chat_id
    
    # Кто прислал?
    chat_uname = ""
    if event.chat and hasattr(event.chat, 'username') and event.chat.username:
        chat_uname = event.chat.username.lower()

    # === 1. СИРЕНА ===
    is_siren = (chat_id == REAL_SIREN_ID) or (chat_uname == SIREN_CHANNEL_USER)
    if is_siren:
        if "відбій" in text:
            await client.send_message(CHANNEL_USERNAME, "🟢 **ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ!**", file=IMG_ALL_CLEAR)
        elif "тривог" in text or "оголошено" in text:
            await client.send_message(CHANNEL_USERNAME, "🔴 **УВАГА! ПОВІТРЯНА ТРИВОГА!**", file=IMG_ALARM)
        return

    # === 2. ФИЛЬТР ИСТОЧНИКОВ (ДОБАВИЛ ВАС) ===
    allowed = ['dtek_ua', 'avariykaaa', 'naglyadach_dnipro', 'me', 'nemovisio']
    if chat_uname not in allowed and not event.out:
        return

    # === 3. ЭКСТРЕННЫЕ ===
    if any(w in text for w in EMERGENCY_WORDS) and any(k in text for k in REGION_KEYWORDS):
        msg = "🚨 **ЕКСТРЕНІ ВІДКЛЮЧЕННЯ!**"
        await client.send_message(CHANNEL_USERNAME, msg, file=IMG_EMERGENCY)
        return

    # === 4. ГРАФИКИ (ТЕКСТ) ===
    if re.search(r'\d\.\d', text) and re.search(r'\d{1,2}:\d{2}', text):
        schedule = parse_text_all_groups(event.message.message)
        if schedule:
            is_upd = any(w in text for w in UPDATE_WORDS)
            service = await get_tasks_service()
            for entry in schedule:
                start_dt = parser.parse(entry['start'])
                end_dt = parser.parse(entry['end'])
                grp = entry['group']
                
                # Пост в канал
                icon = "🔄" if is_upd else "⚡️"
                msg = f"{icon} **Група {grp}:** {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}"
                await client.send_message(CHANNEL_USERNAME, msg, file=IMG_UPDATE if is_upd else IMG_SCHEDULE)
                
                # Tasks только для 1.1
                if grp == MY_PERSONAL_GROUP:
                    notif = start_dt - timedelta(hours=2, minutes=10)
                    task_title = f"{'🔄' if is_upd else '💡'} Світло (Гр {grp})"
                    task = {'title': task_title, 'notes': f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}", 'due': notif.isoformat() + 'Z'}
                    try: service.tasks().insert(tasklist='@default', body=task).execute()
                    except: pass
            return

async def startup_check():
    global REAL_SIREN_ID
    try:
        await client(JoinChannelRequest(SIREN_CHANNEL_USER))
        entity = await client.get_entity(SIREN_CHANNEL_USER)
        REAL_SIREN_ID = int(f"-100{entity.id}")
        await client.send_message(MAIN_ACCOUNT_USERNAME, "🟢 **STRUM ONLINE**: Доступ для @nemovisio дозволено. Текстовий парсер посилено.")
    except Exception as e:
        await client.send_message(MAIN_ACCOUNT_USERNAME, f"⚠️ Помилка старту: {e}")

with client:
    client.loop.run_until_complete(startup_check())
    client.run_until_disconnected()
