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
MY_PERSONAL_GROUP = "1.1"  
MAIN_ACCOUNT_USERNAME = "@nemovisio" 
CHANNEL_USERNAME = "@strum_dp"
SIREN_CHANNEL_USER = "sirena_dp" # Имя канала для поиска

# === ЗМІННІ ===
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']

# Картинки
IMG_SCHEDULE = "https://arcanavisio.com/wp-content/uploads/2026/01/MAIN.jpg"
IMG_EMERGENCY = "https://arcanavisio.com/wp-content/uploads/2026/01/EXTRA.jpg"
IMG_ALARM = "https://arcanavisio.com/wp-content/uploads/2026/01/ALARM.jpg"
IMG_ALL_CLEAR = "https://arcanavisio.com/wp-content/uploads/2026/01/REBOUND.jpg"

# Каналы (sirena_dp добавляем динамически ниже)
SOURCE_CHANNELS = ['dtek_ua', 'avariykaaa', 'avariykaaa_dnepr_radar', 'me', 'sirena_dp'] 

REGION_TAG = "дніпропетровщина"
EMERGENCY_WORDS = ['екстрені', 'екстрене', 'скасовані графіки']

# Глобальный замок
processing_lock = asyncio.Lock()
# Сюда запишем реальный ID сирены
REAL_SIREN_ID = 0 

async def get_tasks_service():
    creds_dict = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('tasks', 'v1', credentials=creds)

def parse_text_all_groups(text):
    schedule = []
    lines = text.split('\n')
    current_groups = []
    for line in lines:
        line_lower = line.lower().strip()
        found_groups = re.findall(r'[гч][рu].*?(\d\.\d)', line_lower)
        if found_groups: current_groups = found_groups; continue
        if current_groups:
            times = re.findall(r'(\d{1,2}:\d{2}).*?(\d{1,2}:\d{2})', line_lower)
            for t in times:
                start_str, end_str = t
                today = datetime.now().strftime('%Y-%m-%d')
                for gr in current_groups:
                    schedule.append({"group": gr, "start": f"{today}T{start_str}:00", "end": f"{today}T{end_str}:00"})
    return schedule

def ask_gemini_all_groups(photo_path, text):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent"
    try:
        with open(photo_path, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode("utf-8")
    except: return "FILE_ERROR"

    prompt = f"""
    Analyze this DTEK schedule image.
    Extract time ranges for ALL consumer groups (1.1, 1.2, 2.1, etc).
    Return strictly JSON list: [{{ "group": "1.1", "start": "...", "end": "..." }}]
    Date today: {datetime.now().strftime('%Y-%m-%d')}.
    """
    payload = {"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": image_data}}]}]}
    full_url = f"{url}?key={GEMINI_KEY}"

    for attempt in range(1, 11):
        try:
            response = requests.post(full_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=60)
            if response.status_code == 200:
                try:
                    return json.loads(response.json()['candidates'][0]['content']['parts'][0]['text'].replace('```json', '').replace('```', '').strip())
                except: return [] 
            elif response.status_code == 429: time.sleep(60); continue
            else: time.sleep(10); continue
        except: time.sleep(10)
    return "TIMEOUT"

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def handler(event):
    text = (event.message.message or "").lower()
    # Получаем ID чата откуда пришло
    incoming_chat_id = event.chat_id 
    chat_title = event.chat.username if event.chat and hasattr(event.chat, 'username') else "Unknown"
    
    # ДЕБАГ: Пишем владельцу, если это сообщение от сирены, но мы его не узнали
    # (Раскомментируйте строку ниже, если снова не сработает)
    # if "тривога" in text: await client.send_message(MAIN_ACCOUNT_USERNAME, f"DEBUG: Вижу тривогу от ID: {incoming_chat_id}")

    # === 1. СИРЕНА (ПРОВЕРЯЕМ ПО ID, А НЕ ПО ИМЕНИ) ===
    is_siren = (incoming_chat_id == REAL_SIREN_ID) or (chat_title == SIREN_CHANNEL_USER) or ("test_siren" in text and chat_title == "me")
    
    if is_siren:
        if "тривога" in text:
            msg = "🔴 **УВАГА! ПОВІТРЯНА ТРИВОГА!**\n\nВсім пройти в укриття!"
            await client.send_message(CHANNEL_USERNAME, msg, file=IMG_ALARM)
        elif "відбій" in text:
            msg = "🟢 **ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ!**"
            await client.send_message(CHANNEL_USERNAME, msg, file=IMG_ALL_CLEAR)
        return

    # === 2. ЕКСТРЕНІ ===
    if any(w in text for w in EMERGENCY_WORDS):
        msg = "🚨 **ТРИВОГА: ЕКСТРЕНІ ВІДКЛЮЧЕННЯ!**"
        await client.send_message(MAIN_ACCOUNT_USERNAME, msg, file=IMG_EMERGENCY)
        try: await client.send_message(CHANNEL_USERNAME, msg, file=IMG_EMERGENCY)
        except: pass
        return

    # Фильтры
    if chat_title == 'dtek_ua' and REGION_TAG not in text: return
    if chat_title == 'avariykaaa' and 'цек' in text: return 

    # === 3. ТЕКСТ (ВСЕ ГРУППЫ) ===
    if (re.search(r'\d\.\d', text)) and (re.search(r'\d{1,2}:\d{2}', text)):
        schedule = parse_text_all_groups(event.message.message)
        if schedule:
            await client.send_message(MAIN_ACCOUNT_USERNAME, f"⚡️ **Текст:** Знайдено {len(schedule)} груп.")
            service = await get_tasks_service()
            schedule.sort(key=lambda x: x['group'])
            for entry in schedule:
                start_dt = parser.parse(entry['start'])
                end_dt = parser.parse(entry['end'])
                grp = entry['group']
                if grp == MY_PERSONAL_GROUP:
                    notif_time = start_dt - timedelta(hours=2) - timedelta(minutes=10)
                    task = {'title': f"💡 СВЕТА НЕ БУДЕТ (Гр. {grp})", 'notes': f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}", 'due': notif_time.isoformat() + 'Z'}
                    try: service.tasks().insert(tasklist='@default', body=task).execute()
                    except: pass
                msg = f"⚡️ **Група {grp}:** Світла не буде з {start_dt.strftime('%H:%M')} до {end_dt.strftime('%H:%M')}"
                try: await client.send_message(CHANNEL_USERNAME, msg, file=IMG_SCHEDULE)
                except: pass
            return

    # === 4. ФОТО (ВСЕ ГРУППЫ) ===
    if event.message.photo:
        if processing_lock.locked(): await client.send_message(MAIN_ACCOUNT_USERNAME, "⏳ **Черга:** Чекаю...")
        async with processing_lock:
            status_msg = await client.send_message(MAIN_ACCOUNT_USERNAME, "🛡 **Gemini:** Аналізую...")
            path = await event.message.download_media()
            result = await asyncio.to_thread(ask_gemini_all_groups, path, event.message.message)
            os.remove(path)
            if isinstance(result, list):
                if schedule := result:
                    service = await get_tasks_service()
                    schedule.sort(key=lambda x: x['group'])
                    for entry in schedule:
                        start_dt = parser.parse(entry['start'])
                        end_dt = parser.parse(entry['end'])
                        grp = entry.get('group', '?')
                        if grp == MY_PERSONAL_GROUP:
                            notif_time = start_dt - timedelta(hours=2) - timedelta(minutes=10)
                            task = {'title': f"💡 СВЕТА НЕ БУДЕТ (Гр. {grp})", 'notes': f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}", 'due': notif_time.isoformat() + 'Z'}
                            try: service.tasks().insert(tasklist='@default', body=task).execute()
                            except: pass
                        msg = f"⚡️ **Група {grp}:** Світла не буде з {start_dt.strftime('%H:%M')} до {end_dt.strftime('%H:%M')}"
                        try: await client.send_message(CHANNEL_USERNAME, msg, file=IMG_SCHEDULE)
                        except: pass
                    await client.delete_messages(None, status_msg)
                else: await client.edit_message(status_msg, "✅ **Чисто:** Не бачу графіків.")
            else: await client.edit_message(status_msg, f"❌ **Помилка:** {str(result)}")

# === АВТО-ОПРЕДЕЛЕНИЕ ID СИРЕНЫ ===
async def startup_check():
    global REAL_SIREN_ID
    try:
        # Пытаемся найти канал по имени
        siren_entity = await client.get_entity(SIREN_CHANNEL_USER)
        REAL_SIREN_ID = siren_entity.id
        await client.send_message(MAIN_ACCOUNT_USERNAME, f"🟢 **STRUM:** Канал сирени знайдено!\nID: `{REAL_SIREN_ID}`\nТепер я його не пропущу.")
    except Exception as e:
        await client.send_message(MAIN_ACCOUNT_USERNAME, f"⚠️ **УВАГА:** Не можу знайти канал {SIREN_CHANNEL_USER}.\nПереконайтеся, що ви на нього підписані!\nПомилка: {e}")

with client:
    client.loop.run_until_complete(startup_check())
    client.run_until_disconnected()
