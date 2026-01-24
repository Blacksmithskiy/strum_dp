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

# === ЗМІННІ ===
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']

IMG_SCHEDULE = "https://arcanavisio.com/wp-content/uploads/2026/01/MAIN.jpg"
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
        # Шукаємо 1.1, 2.1...
        found_groups = re.findall(r'\b(\d\.\d)\b', line_lower)
        if found_groups:
            # Шукаємо час
            times = re.findall(r'(\d{1,2}:\d{2}).*?(\d{1,2}:\d{2})', line_lower)
            if times:
                today = datetime.now().strftime('%Y-%m-%d')
                for gr in found_groups:
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
    Analyze this schedule image. Find ALL groups (1.1, 1.2, etc).
    Return JSON list: [{{ "group": "1.1", "start": "HH:MM", "end": "HH:MM" }}]
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

    # === 0. АВТО-ВИЗНАЧЕННЯ ID СИРЕНИ (ШПИГУН) ===
    if event.is_private and event.out and event.fwd_from:
         try:
             rid = getattr(event.fwd_from.from_id, 'channel_id', None)
             if rid:
                 global REAL_SIREN_ID
                 REAL_SIREN_ID = int(f"-100{rid}")
         except: pass

    # === 1. ЛОГІКА СИРЕНИ (ПРІОРИТЕТ) ===
    is_siren = False
    # Перевірка по ID
    if REAL_SIREN_ID and chat_id == REAL_SIREN_ID: is_siren = True
    # Перевірка по юзернейму
    if event.chat and hasattr(event.chat, 'username') and event.chat.username:
        if event.chat.username.lower() == SIREN_CHANNEL_USER: is_siren = True
    # Перевірка ручного тесту
    if "test_siren" in text and event.out: is_siren = True
    # Перевірка пересилання
    if event.fwd_from and ("сирена" in text or "тривог" in text): is_siren = True

    if is_siren:
        if "відбій" in text or "отбой" in text:
            await client.send_message(CHANNEL_USERNAME, "🟢 **ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ!**", file=IMG_ALL_CLEAR)
        elif "тривог" in text or "тревога" in text or "укриття" in text:
            await client.send_message(CHANNEL_USERNAME, "🔴 **УВАГА! ПОВІТРЯНА ТРИВОГА!**", file=IMG_ALARM)
        return

    # === 2. ЕКСТРЕНІ ===
    if any(w in text for w in ['екстрені', 'экстренные', 'скасовані', 'отмена']):
        if any(k in text for k in ['дніпро', 'днепр', 'дтек', 'дтэк']):
            msg = "🚨 **ТРИВОГА: ЕКСТРЕНІ ВІДКЛЮЧЕННЯ!**"
            await client.send_message(CHANNEL_USERNAME, msg, file=IMG_EMERGENCY)
            return

    # === 3. ОБРОБКА ТЕКСТУ (ГРАФІКИ) ===
    # Шукаємо наявність груп і часу в тексті
    if re.search(r'\d\.\d', text) and re.search(r'\d{1,2}:\d{2}', text):
        schedule = parse_text_all_groups(event.message.message)
        if schedule:
            service = await get_tasks_service()
            schedule.sort(key=lambda x: x['group'])
            
            # --- ЗМІНА: Збираємо повідомлення ---
            message_lines = []
            
            for entry in schedule:
                # Парсимо час
                try:
                    start_dt = parser.parse(entry['start'])
                    end_dt = parser.parse(entry['end'])
                except: continue
                
                grp = entry['group']
                
                # 1. ДОДАЄМО РЯДОК У СПИСОК (замість відправки)
                message_lines.append(f"⚡️ **Група {grp}:** {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}")

                # 2. ЗАДАЧА В TASKS (ТІЛЬКИ МОЯ ГРУПА) - БЕЗ ЗМІН
                if grp == MY_PERSONAL_GROUP:
                    notif_time = start_dt - timedelta(hours=2, minutes=10)
                    task = {
                        'title': f"💡 СВІТЛО (Гр. {grp})",
                        'notes': f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}",
                        'due': notif_time.isoformat() + 'Z'
                    }
                    try: service.tasks().insert(tasklist='@default', body=task).execute()
                    except: pass
            
            # --- ВІДПРАВЛЯЄМО ОДНЕ ПОВІДОМЛЕННЯ ---
            if message_lines:
                full_message = "\n".join(message_lines)
                try: await client.send_message(CHANNEL_USERNAME, full_message, file=IMG_SCHEDULE)
                except: pass
            return

    # === 4. ОБРОБКА ФОТО (AI) ===
    if event.message.photo:
        async with processing_lock:
            # Тільки якщо це схоже на графік (є слова дтек, дніпро і т.д.) або просто з надійного каналу
            status = await client.send_message(MAIN_ACCOUNT_USERNAME, "🛡 **AI:** Перевіряю фото...")
            path = await event.message.download_media()
            result = await asyncio.to_thread(ask_gemini_all_groups, path, event.message.message)
            os.remove(path)
            
            if isinstance(result, list) and result:
                service = await get_tasks_service()
                schedule = result
                schedule.sort(key=lambda x: x.get('group', ''))
                
                # --- ЗМІНА: Збираємо повідомлення ---
                message_lines = []

                for entry in schedule:
                    try:
                        start_dt = parser.parse(entry['start'])
                        end_dt = parser.parse(entry['end'])
                        grp = entry.get('group', '?')
                    except: continue

                    # Додаємо рядок
                    message_lines.append(f"⚡️ **Група {grp}:** {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}")

                    # Tasks тільки для 1.1 - БЕЗ ЗМІН
                    if grp == MY_PERSONAL_GROUP:
                        notif_time = start_dt - timedelta(hours=2, minutes=10)
                        task = {
                            'title': f"💡 СВІТЛО (Гр. {grp})",
                            'notes': f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}",
                            'due': notif_time.isoformat() + 'Z'
                        }
                        try: service.tasks().insert(tasklist='@default', body=task).execute()
                        except: pass
                
                # Видаляємо статус
                await client.delete_messages(None, status)

                # --- ВІДПРАВЛЯЄМО ОДНЕ ПОВІДОМЛЕННЯ ---
                if message_lines:
                    full_message = "\n".join(message_lines)
                    try: await client.send_message(CHANNEL_USERNAME, full_message, file=IMG_SCHEDULE)
                    except: pass

            else:
                await client.delete_messages(None, status)

async def startup_check():
    global REAL_SIREN_ID
    try:
        await client(JoinChannelRequest(SIREN_CHANNEL_USER))
        entity = await client.get_entity(SIREN_CHANNEL_USER)
        REAL_SIREN_ID = int(f"-100{entity.id}")
        await client.send_message(MAIN_ACCOUNT_USERNAME, f"🟢 **STRUM STABLE:** Систему відновлено (1 msg mode).")
    except:
        await client.send_message(MAIN_ACCOUNT_USERNAME, "⚠️ Авто-пошук сирени не вдався, але ручний режим працює.")

with client:
    client.loop.run_until_complete(startup_check())
    client.run_until_disconnected()
