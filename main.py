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

# === НАСТРОЙКИ ===
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
        groups = re.findall(r'\b(\d\.\d)\b', line_lower)
        if groups:
            times = re.findall(r'(\d{1,2}:\d{2}).*?(\d{1,2}:\d{2})', line_lower)
            if times:
                today = datetime.now().strftime('%Y-%m-%d')
                for gr in groups:
                    if gr in [t[0] for t in times] or gr in [t[1] for t in times]: continue
                    for t in times:
                        schedule.append({
                            "group": gr,
                            "start": f"{today}T{t[0]}:00",
                            "end": f"{today}T{t[1]}:00"
                        })
    return schedule

def ask_gemini_all_groups(photo_path, text):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent"
    try:
        with open(photo_path, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode("utf-8")
    except: return "FILE_ERROR"
    prompt = f"""
    Analyze schedule. Find ALL groups. Return JSON list: [{{ "group": "1.1", "start": "HH:MM", "end": "HH:MM" }}]
    Date today: {datetime.now().strftime('%Y-%m-%d')}.
    """
    payload = {"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": image_data}}]}]}
    full_url = f"{url}?key={GEMINI_KEY}"
    for attempt in range(1, 6):
        try:
            response = requests.post(full_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=60)
            if response.status_code == 200:
                try: return json.loads(response.json()['candidates'][0]['content']['parts'][0]['text'].replace('```json', '').replace('```', '').strip())
                except: return [] 
            elif response.status_code == 429: time.sleep(30); continue
            else: time.sleep(5); continue
        except: time.sleep(5)
    return "TIMEOUT"

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage())
async def handler(event):
    text = (event.message.message or "").lower()
    chat_id = event.chat_id
    
    # === 1. СИРЕНА ===
    is_siren = False
    if REAL_SIREN_ID and chat_id == REAL_SIREN_ID: is_siren = True
    if event.chat and hasattr(event.chat, 'username') and event.chat.username:
        if event.chat.username.lower() == SIREN_CHANNEL_USER: is_siren = True
    if "test_siren" in text and event.out: is_siren = True
    if event.fwd_from and ("сирена" in text or "тривог" in text): is_siren = True

    if is_siren:
        if "відбій" in text or "отбой" in text:
            await client.send_message(CHANNEL_USERNAME, "🟢 **ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ!**", file=IMG_ALL_CLEAR)
        elif "тривог" in text or "тревога" in text or "укриття" in text:
            await client.send_message(CHANNEL_USERNAME, "🔴 **УВАГА! ПОВІТРЯНА ТРИВОГА!**", file=IMG_ALARM)
        return

    # === 2. ЭКСТРЕННЫЕ ===
    if any(w in text for w in ['екстрені', 'экстренные', 'скасовані', 'отмена']):
        if any(k in text for k in ['дніпро', 'днепр', 'дтек', 'дтэк']):
            msg = "🚨 **ТРИВОГА: ЕКСТРЕНІ ВІДКЛЮЧЕННЯ!**"
            await client.send_message(CHANNEL_USERNAME, msg, file=IMG_EMERGENCY)
            return

    # === 3. ЕДИНЫЙ ПОСТ ДЛЯ ГРАФИКОВ (ТЕКСТ) ===
    if re.search(r'\d\.\d', text) and re.search(r'\d{1,2}:\d{2}', text):
        schedule = parse_text_all_groups(event.message.message)
        if schedule:
            service = await get_tasks_service()
            schedule.sort(key=lambda x: x['group'])
            
            # Заголовок
            is_update = any(w in text for w in ['зміни', 'оновлення', 'изменения', 'обновление'])
            header = "🔄 **ОНОВЛЕННЯ ГРАФІКУ:**" if is_update else "⚡️ **ГРАФІК ВІДКЛЮЧЕНЬ:**"
            img_to_use = IMG_UPDATE if is_update else IMG_SCHEDULE
            
            # Формируем тело сообщения
            msg_lines = [header, ""]
            
            for entry in schedule:
                try:
                    start_dt = parser.parse(entry['start'])
                    end_dt = parser.parse(entry['end'])
                except: continue
                
                grp = entry['group']
                time_str = f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}"
                
                # Добавляем строку в общее сообщение
                msg_lines.append(f"🔹 **Гр. {grp}:** {time_str}")

                # ЗАДАЧА В TASKS (ТОЛЬКО ДЛЯ 1.1)
                if grp == MY_PERSONAL_GROUP:
                    notif_time = start_dt - timedelta(hours=2, minutes=10)
                    task_title = f"{'🔄' if is_update else '💡'} СВІТЛО (Гр. {grp})"
                    task = {
                        'title': task_title,
                        'notes': time_str,
                        'due': notif_time.isoformat() + 'Z'
                    }
                    try: service.tasks().insert(tasklist='@default', body=task).execute()
                    except: pass
            
            # Отправляем ОДИН раз
            full_message = "\n".join(msg_lines)
            await client.send_message(CHANNEL_USERNAME, full_message, file=img_to_use)
            return

    # === 4. ЕДИНЫЙ ПОСТ ДЛЯ ГРАФИКОВ (ФОТО) ===
    if event.message.photo:
        async with processing_lock:
            try: await client.send_read_acknowledge(event.chat_id)
            except: pass
            
            path = await event.message.download_media()
            result = await asyncio.to_thread(ask_gemini_all_groups, path, event.message.message)
            os.remove(path)
