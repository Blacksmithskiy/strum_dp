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
IMG_UPDATE = "https://arcanavisio.com/wp-content/uploads/2026/01/UPDATE.jpg" # (Якщо немає - використає звичайну)
IMG_EMERGENCY = "https://arcanavisio.com/wp-content/uploads/2026/01/EXTRA.jpg"
IMG_ALARM = "https://arcanavisio.com/wp-content/uploads/2026/01/ALARM.jpg"
IMG_ALL_CLEAR = "https://arcanavisio.com/wp-content/uploads/2026/01/REBOUND.jpg"

# === СЛОВНИКИ (UA + RU) ===
# 1. Регіон (щоб розуміти, що це про нас)
REGION_KEYWORDS = [
    'дніпропетровщина', 'дніпро', 'дтек',  # UA
    'днепропетровщина', 'днепр', 'дтэк', 'днепропетровская' # RU
]

# 2. Екстрені відключення
EMERGENCY_WORDS = [
    'екстрені', 'екстрене', 'скасовані графіки', # UA
    'экстренные', 'экстренное', 'отмена графиков' # RU
]

# 3. Слова-маркери змін (для заголовка 🔄)
UPDATE_WORDS = [
    'зміни', 'оновлення', 'змінено', 'оновлено', 'корегування', # UA
    'изменения', 'обновление', 'корректировка', 'меняется', 'правки' # RU
]

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
        # Шукаємо цифри 1.1, 2.1...
        found_groups = re.findall(r'\b(\d\.\d)\b', line_lower)
        
        if found_groups:
            # Шукаємо час (12:00 - 14:00)
            times = re.findall(r'(\d{1,2}:\d{2}).*?(\d{1,2}:\d{2})', line_lower)
            if times:
                today = datetime.now().strftime('%Y-%m-%d')
                for gr in found_groups:
                    # Фільтр помилкових спрацювань (коли група = час)
                    if gr in [t[0] for t in times] or gr in [t[1] for t in times]: continue
                    
                    for t in times:
                        start_str, end_str = t
                        schedule.append({
                            "group": gr,
                            "start": f"{today}T{start_str}:00",
                            "end": f"{today}T{end_str}:00"
                        })
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
                try: return json.loads(response.json()['candidates'][0]['content']['parts'][0]['text'].replace('```json', '').replace('```', '').strip())
                except: return [] 
            elif response.status_code == 429: time.sleep(60); continue
            else: time.sleep(10); continue
        except: time.sleep(10)
    return "TIMEOUT"

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage())
async def handler(event):
    text = (event.message.message or "").lower()
    chat_id = event.chat_id
    
    # === 0. ШПИГУН ===
    if event.is_private and event.out and event.fwd_from:
        if event.fwd_from.from_id:
             try:
                 rid = getattr(event.fwd_from.from_id, 'channel_id', None)
                 if rid: 
                     global REAL_SIREN_ID
                     REAL_SIREN_ID = int(f"-100{rid}")
             except: pass

    # === 1. ТЕСТ СИРЕНИ ===
    if "test_siren" in text and event.out:
        if "тривог" in text:
            await client.send_message("me", "✅ Тест ТРИВОГИ...")
            await client.send_message(CHANNEL_USERNAME, "🔴 **УВАГА! ПОВІТРЯНА ТРИВОГА!**", file=IMG_ALARM)
        elif "відбій" in text:
            await client.send_message("me", "✅ Тест ВІДБОЮ...")
            await client.send_message(CHANNEL_USERNAME, "🟢 **ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ!**", file=IMG_ALL_CLEAR)
        return

    # === 2. РЕАЛЬНА СИРЕНА ===
    is_siren_source = False
    if REAL_SIREN_ID and chat_id == REAL_SIREN_ID: is_siren_source = True
    if not is_siren_source and event.chat and hasattr(event.chat, 'username') and event.chat.username:
        if event.chat.username.lower() == SIREN_CHANNEL_USER: is_siren_source = True
    if event.fwd_from and ("сирена" in text or "тривог" in text or "відбій" in text): is_siren_source = True

    if is_siren_source:
        if "відбій" in text:
            await client.send_message(CHANNEL_USERNAME, "🟢 **ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ!**", file=IMG_ALL_CLEAR)
        elif "тривог" in text or "оголошено" in text:
            await client.send_message(CHANNEL_USERNAME, "🔴 **УВАГА! ПОВІТРЯНА ТРИВОГА!**\n\nВсім пройти в укриття!", file=IMG_ALARM)
        return

    # Фільтри каналів
    allowed_channels = ['dtek_ua', 'avariykaaa', 'avariykaaa_dnepr_radar', 'me']
    chat_uname = ""
    if event.chat and hasattr(event.chat, 'username') and event.chat.username:
        chat_uname = event.chat.username.lower()
    
    if not is_siren_source and chat_uname not in allowed_channels: return 
    
    # Фільтр регіону (оновлений)
    # Якщо це офіційний канал ДТЕК - перевіряємо, чи згадується Дніпро/Область (UA/RU)
    if chat_uname == 'dtek_ua':
        if not any(k in text for k in REGION_KEYWORDS): return

    # === 3. ЕКСТРЕНІ ===
    if any(w in text for w in EMERGENCY_WORDS):
        msg = "🚨 **ТРИВОГА: ЕКСТРЕНІ ВІДКЛЮЧЕННЯ!**\n(Экстренные отключения)"
        await client.send_message(MAIN_ACCOUNT_USERNAME, msg, file=IMG_EMERGENCY)
        try: await client.send_message(CHANNEL_USERNAME, msg, file=IMG_EMERGENCY)
        except: pass
        return

    # === 4. ТЕКСТ (З ПІДТРИМКОЮ RU) ===
    if (re.search(r'\d\.\d', text)) and (re.search(r'\d{1,2}:\d{2}', text)):
        schedule = parse_text_all_groups(event.message.message)
        
        # Перевіряємо слова-маркери змін (UA + RU)
        is_update = any(w in text for w in UPDATE_WORDS)
        header_icon = "🔄" if is_update else "⚡️"
        header_text = "**ОНОВЛЕННЯ ГРАФІКУ:**" if is_update else "**Графік відключень:**"
        
        if schedule:
            await client.send_message(MAIN_ACCOUNT_USERNAME, f"{header_icon} **Текст:** Знайдено {len(schedule)} груп (Зміни: {is_update})")
            service = await get_tasks_service()
            schedule.sort(key=lambda x: x['group'])
            
            for entry in schedule:
                start_dt = parser.parse(entry['start'])
                end_dt = parser.parse(entry['end'])
                grp = entry['group']
                
                # Google Tasks (Тільки моя група)
                if grp == MY_PERSONAL_GROUP:
                    notif_time = start_dt - timedelta(hours=2) - timedelta(minutes=10)
                    task_title = f"🔄 ИЗМЕНЕНИЕ: Света не будет" if is_update else f"💡 СВЕТА НЕ БУДЕТ"
                    task = {'title': f"{task_title} (Гр. {grp})", 'notes': f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}", 'due': notif_time.isoformat() + 'Z'}
                    try: service.tasks().insert(tasklist='@default', body=task).execute()
                    except: pass
                
                # Telegram Post
                msg = f"{header_icon} {header_text}\n**Група {grp}:** {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}"
                try: await client.send_message(CHANNEL_USERNAME, msg, file=IMG_SCHEDULE)
                except: pass
            return

    # === 5. ФОТО ===
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
                            task = {'title': f"💡 СВЕТА НЕ БУДЕТ (Гр. {grp})", 'notes': f
