import os
import json
import base64
import time
import requests
import asyncio
from datetime import datetime, timedelta
from dateutil import parser
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# === НАЛАШТУВАННЯ ===
MY_GROUP = "1.1"
MAIN_ACCOUNT_USERNAME = "@nemovisio" 
CHANNEL_USERNAME = "@strum_dp"

# === ЗМІННІ ===
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']

IMG_SCHEDULE = "https://arcanavisio.com/wp-content/uploads/2026/01/MAIN.jpg"
IMG_EMERGENCY = "https://arcanavisio.com/wp-content/uploads/2026/01/EXTRA.jpg"

SOURCE_CHANNELS = ['dtek_ua', 'avariykaaa', 'me'] 
REGION_TAG = "дніпропетровщина"
PROVIDER_TAG = "дтек"
NOISE_WORDS = ['вода', 'водоканал', 'труб', 'каналізац', 'опалення']
EMERGENCY_WORDS = ['екстрені', 'екстрене', 'скасовані графіки']

# Глобальний замок для черги
processing_lock = asyncio.Lock()

async def get_tasks_service():
    creds_dict = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('tasks', 'v1', credentials=creds)

def ask_gemini_persistent(photo_path, text):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent"
    
    try:
        with open(photo_path, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode("utf-8")
    except: return "FILE_ERROR"

    prompt = f"""
    Look at this image. Is this a power outage schedule for DTEK Dnipropetrovsk?
    If NO, return JSON: []
    If YES, find time ranges ONLY for Group {MY_GROUP}.
    Return strictly JSON: [{{"start": "YYYY-MM-DDTHH:MM:SS", "end": "YYYY-MM-DDTHH:MM:SS"}}]
    Date today: {datetime.now().strftime('%Y-%m-%d')}.
    Context text: {text}
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": image_data}}]}]}
    full_url = f"{url}?key={GEMINI_KEY}"

    # 10 СПРОБ (Це дасть нам до 10 хвилин наполегливості)
    for attempt in range(1, 11):
        try:
            print(f"🔄 Спроба {attempt}/10...")
            response = requests.post(full_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=60)
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    raw_text = result['candidates'][0]['content']['parts'][0]['text']
                    clean_res = raw_text.replace('```json', '').replace('```', '').strip()
                    return json.loads(clean_res)
                except: return [] 
            
            elif response.status_code == 429:
                print(f"⏳ Перегрів (429). Чекаю 60 сек...")
                time.sleep(60) # Чекаємо повну хвилину
                continue
            
            else:
                print(f"Помилка {response.status_code}")
                time.sleep(10)
                continue
                
        except Exception as e:
            time.sleep(10)
            continue

    return "TIMEOUT"

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def handler(event):
    text = (event.message.message or "").lower()
    chat_title = event.chat.username if event.chat and hasattr(event.chat, 'username') else "Unknown/Me"
    
    if chat_title == 'dtek_ua' and REGION_TAG not in text: return
    if chat_title == 'avariykaaa' and 'цек' in text: return 
    if any(w in text for w in NOISE_WORDS) and PROVIDER_TAG not in text: return

    if any(w in text for w in EMERGENCY_WORDS):
        msg = "🚨 **ТРИВОГА: ЕКСТРЕНІ ВІДКЛЮЧЕННЯ!**"
        await client.send_message(MAIN_ACCOUNT_USERNAME, msg, file=IMG_EMERGENCY)
        try: await client.send_message(CHANNEL_USERNAME, msg, file=IMG_EMERGENCY)
        except: pass
        return

    if event.message.photo:
        # Перевірка черги
        if processing_lock.locked():
            await client.send_message(MAIN_ACCOUNT_USERNAME, "⏳ **В черзі:** Попередній графік ще обробляється. Я повідомлю, коли звільнюсь.")
        
        async with processing_lock:
            status_msg = await client.send_message(MAIN_ACCOUNT_USERNAME, "🛡 **Gemini 2.0:** Аналізую... (Це може зайняти час через ліміти Google)")
            
            path = await event.message.download_media()
            result = await asyncio.to_thread(ask_gemini_persistent, path, event.message.message)
            os.remove(path)
            
            if isinstance(result, list):
                if not result:
                    await client.edit_message(status_msg, "✅ **Чисто:** Графік розпізнано, ваша група зі світлом.")
                else:
                    schedule = result
                    service = await get_tasks_service()
                    for entry in schedule:
                        start_dt = parser.parse(entry['start'])
                        end_dt = parser.parse(entry['end'])
                        task = {
                            'title': f"💡 СВІТЛА НЕ БУДЕ (Гр. {MY_GROUP})",
                            'notes': f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}",
                            'due': (start_dt - timedelta(minutes=15)).isoformat() + 'Z'
                        }
                        try: service.tasks().insert(tasklist='@default', body=task).execute()
                        except: pass
                        
                        msg = f"⚡️ **Світла не буде з {start_dt.strftime('%H:%M')} до {end_dt.strftime('%H:%M')}**\n(Група {MY_GROUP})."
                        await client.send_message(MAIN_ACCOUNT_USERNAME, msg, file=IMG_SCHEDULE)
                        try: await client.send_message(CHANNEL_USERNAME, msg, file=IMG_SCHEDULE)
                        except: pass
                    await client.delete_messages(None, status_msg)
            elif result == "TIMEOUT":
                 await client.edit_message(status_msg, "❌ **Ліміт Google:** На жаль, сервер перевантажений (429) більше 10 хвилин. Спробуйте пізніше.")
            else:
                await client.edit_message(status_msg, f"❌ **Збій:** {str(result)}")

async def startup_check():
    try: await client.send_message(MAIN_ACCOUNT_USERNAME, "🟢 **STRUM:** Режим 'Бронетранспортер' (60сек/10спроб) увімкнено.")
    except: pass

with client:
    client.loop.run_until_complete(startup_check())
    client.run_until_disconnected()
