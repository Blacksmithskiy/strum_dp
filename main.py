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
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# === НАСТРОЙКИ ===
MY_GROUP = "1.1"
MAIN_ACCOUNT_USERNAME = "@nemovisio" 
CHANNEL_USERNAME = "@strum_dp"

# === ПЕРЕМЕННЫЕ ===
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']

IMG_SCHEDULE = "https://arcanavisio.com/wp-content/uploads/2026/01/MAIN.jpg"
IMG_EMERGENCY = "https://arcanavisio.com/wp-content/uploads/2026/01/EXTRA.jpg"

SOURCE_CHANNELS = ['dtek_ua', 'avariykaaa', 'avariykaaa_dnepr_radar', 'me'] 
REGION_TAG = "дніпропетровщина"
EMERGENCY_WORDS = ['екстрені', 'екстрене', 'скасовані графіки']

# Глобальный замок
processing_lock = asyncio.Lock()

async def get_tasks_service():
    creds_dict = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('tasks', 'v1', credentials=creds)

# === ТЕКСТОВЫЙ ПАРСЕР ===
def parse_text_schedule(text):
    print("⚡️ Текстовый режим: Ищу группу 1.1...")
    schedule = []
    lines = text.split('\n')
    is_my_group = False
    
    for line in lines:
        line = line.lower().strip()
        if ("група 1.1" in line or "группа 1.1" in line or "черга 1.1" in line) and "1.2" not in line:
            is_my_group = True
            continue
        if ("група" in line or "группа" in line or "черга" in line) and "1.1" not in line and is_my_group:
            is_my_group = False
            continue
            
        if is_my_group:
            times = re.findall(r'(\d{1,2}:\d{2}).*?(\d{1,2}:\d{2})', line)
            for t in times:
                start_str, end_str = t
                today = datetime.now().strftime('%Y-%m-%d')
                schedule.append({
                    "start": f"{today}T{start_str}:00",
                    "end": f"{today}T{end_str}:00"
                })
    return schedule

# === AI GEMINI (РЕЗЕРВ) ===
def ask_gemini_persistent(photo_path, text):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent"
    try:
        with open(photo_path, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode("utf-8")
    except: return "FILE_ERROR"

    prompt = f"""
    Analyze this DTEK schedule image.
    Find time ranges ONLY for Group {MY_GROUP}.
    Return strictly JSON: [{{"start": "YYYY-MM-DDTHH:MM:SS", "end": "YYYY-MM-DDTHH:MM:SS"}}]
    Date today: {datetime.now().strftime('%Y-%m-%d')}.
    """
    payload = {"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": image_data}}]}]}
    full_url = f"{url}?key={GEMINI_KEY}"

    for attempt in range(1, 11):
        try:
            response = requests.post(full_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=60)
            if response.status_code == 200:
                try:
                    result = response.json()
                    clean = result['candidates'][0]['content']['parts'][0]['text'].replace('```json', '').replace('```', '').strip()
                    return json.loads(clean)
                except: return [] 
            elif response.status_code == 429:
                time.sleep(60)
                continue
            else:
                time.sleep(10)
                continue
        except: time.sleep(10)
    return "TIMEOUT"

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def handler(event):
    text = (event.message.message or "").lower()
    chat_title = event.chat.username if event.chat and hasattr(event.chat, 'username') else "Unknown/Me"
    
    # 1. ЕКСТРЕНІ
    if any(w in text for w in EMERGENCY_WORDS):
        msg = "🚨 **ТРИВОГА: ЕКСТРЕНІ ВІДКЛЮЧЕННЯ!**"
        await client.send_message(MAIN_ACCOUNT_USERNAME, msg, file=IMG_EMERGENCY)
        try: await client.send_message(CHANNEL_USERNAME, msg, file=IMG_EMERGENCY)
        except: pass
        return

    # 2. ТЕКСТОВЫЙ РЕЖИМ
    if ("1.1" in text) and (re.search(r'\d{1,2}:\d{2}', text)):
        schedule = parse_text_schedule(event.message.message)
        if schedule:
            await client.send_message(MAIN_ACCOUNT_USERNAME, "⚡️ **Текстовый режим:** График найден.")
            service = await get_tasks_service()
            for entry in schedule:
                start_dt = parser.parse(entry['start'])
                end_dt = parser.parse(entry['end'])
                
                # === ИСПРАВЛЕНИЕ ВРЕМЕНИ ДЛЯ TASKS ===
                # Отнимаем 2 часа (Киев-UTC) и 10 минут (Напоминание)
                notification_time = start_dt - timedelta(hours=2) - timedelta(minutes=10)
                
                task = {
                    'title': f"💡 СВЕТА НЕ БУДЕТ (Гр. {MY_GROUP})",
                    'notes': f"Время: {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}",
                    'due': notification_time.isoformat() + 'Z' # Z = UTC
                }
                try: service.tasks().insert(tasklist='@default', body=task).execute()
                except: pass
                
                msg = f"⚡️ **Світла не буде з {start_dt.strftime('%H:%M')} до {end_dt.strftime('%H:%M')}**\n(Група {MY_GROUP})."
                await client.send_message(MAIN_ACCOUNT_USERNAME, msg, file=IMG_SCHEDULE)
                try: await client.send_message(CHANNEL_USERNAME, msg, file=IMG_SCHEDULE)
                except: pass
            return

    # 3. ФОТО РЕЖИМ (AI)
    if event.message.photo:
        if processing_lock.locked():
            await client.send_message(MAIN_ACCOUNT_USERNAME, "⏳ **Очередь:** Жду, пока обработается прошлый график...")
        
        async with processing_lock:
            status_msg = await client.send_message(MAIN_ACCOUNT_USERNAME, "🛡 **Gemini:** Анализирую фото...")
            path = await event.message.download_media()
            result = await asyncio.to_thread(ask_gemini_persistent, path, event.message.message)
            os.remove(path)
            
            if isinstance(result, list):
                if schedule := result:
                    service = await get_tasks_service()
                    for entry in schedule:
                        start_dt = parser.parse(entry['start'])
                        end_dt = parser.parse(entry['end'])
                        
                        # === ИСПРАВЛЕНИЕ ВРЕМЕНИ ДЛЯ TASKS ===
                        # Отнимаем 2 часа (Киев-UTC) и 10 минут (Напоминание)
                        notification_time = start_dt - timedelta(hours=2) - timedelta(minutes=10)

                        task = {
                            'title': f"💡 СВЕТА НЕ БУДЕТ (Гр. {MY_GROUP})",
                            'notes': f"Время: {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}",
                            'due': notification_time.isoformat() + 'Z'
                        }
                        try: service.tasks().insert(tasklist='@default', body=task).execute()
                        except: pass
                        
                        msg = f"⚡️ **Світла не буде з {start_dt.strftime('%H:%M')} до {end_dt.strftime('%H:%M')}**\n(Група {MY_GROUP})."
                        await client.send_message(MAIN_ACCOUNT_USERNAME, msg, file=IMG_SCHEDULE)
                        try: await client.send_message(CHANNEL_USERNAME, msg, file=IMG_SCHEDULE)
                        except: pass
                    await client.delete_messages(None, status_msg)
                else:
                     await client.edit_message(status_msg, "✅ **Чисто:** Вашей группы нет в графике.")
            else:
                await client.edit_message(status_msg, f"❌ **Ошибка:** {str(result)}")

async def startup_check():
    try: await client.send_message(MAIN_ACCOUNT_USERNAME, "🟢 **STRUM FIXED:** Время напоминаний исправлено (-10 мин).")
    except: pass

with client:
    client.loop.run_until_complete(startup_check())
    client.run_until_disconnected()
