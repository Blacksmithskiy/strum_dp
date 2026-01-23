import os
import json
import base64
import requests
import asyncio
from datetime import datetime, timedelta
from dateutil import parser
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# === ВАШІ НАЛАШТУВАННЯ ===
MY_GROUP = "1.1"
MAIN_ACCOUNT_USERNAME = "@nemovisio" 
CHANNEL_ID = "@strum_dp"             

# === ВІЗУАЛІЗАЦІЯ ===
IMG_SCHEDULE = "https://arcanavisio.com/wp-content/uploads/2026/01/MAIN.jpg"
IMG_EMERGENCY = "https://arcanavisio.com/wp-content/uploads/2026/01/EXTRA.jpg"

# === СИСТЕМНІ ЗМІННІ ===
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']

SOURCE_CHANNELS = ['dtek_ua', 'avariykaaa', 'me'] 
REGION_TAG = "дніпропетровщина"
PROVIDER_TAG = "дтек"
IGNORE_PROVIDER = "цек"
NOISE_WORDS = ['вода', 'водоканал', 'труб', 'каналізац', 'опалення']
EMERGENCY_WORDS = ['екстрені', 'екстрене', 'скасовані графіки']

async def get_tasks_service():
    creds_dict = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('tasks', 'v1', credentials=creds)

# 🔥 ТОЧКОВИЙ УДАР ПО ЄДИНІЙ РОБОЧІЙ МОДЕЛІ
def ask_gemini_v2(photo_path, text):
    print("🤖 Gemini: Використовую модель 2.0 Flash Exp...")
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent"
    
    try:
        with open(photo_path, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode("utf-8")

        prompt = f"""
        Проанализируй этот график отключений света (ДТЕК, Днепропетровщина).
        Найди время отключения ТОЛЬКО для группы {MY_GROUP}.
        Текст поста: {text}
        Верни JSON список: [{{"start": "YYYY-MM-DDTHH:MM:SS", "end": "YYYY-MM-DDTHH:MM:SS"}}]
        Дата сегодня: {datetime.now().strftime('%Y-%m-%d')}.
        Если графиков для группы {MY_GROUP} нет, верни [].
        """
        
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {
                        "mime_type": "image/jpeg",
                        "data": image_data
                    }}
                ]
            }]
        }
        
        # Додаємо таймаут, щоб не зависало
        response = requests.post(f"{url}?key={GEMINI_KEY}", json=payload, headers={'Content-Type': 'application/json'}, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            if 'candidates' in result and 'content' in result['candidates'][0]:
                raw_text = result['candidates'][0]['content']['parts'][0]['text']
                clean_res = raw_text.replace('```json', '').replace('```', '').strip()
                return json.loads(clean_res)
        elif response.status_code == 429:
            print("⏳ Google просить почекати (429 Quota). Спробую наступного разу.")
            return []
        else:
            print(f"❌ Помилка API: {response.text}")
            return []

    except Exception as e:
        print(f"❌ Збій запиту: {e}")
        return []

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def handler(event):
    text = (event.message.message or "").lower()
    chat_title = event.chat.username if event.chat and hasattr(event.chat, 'username') else "Unknown/Me"
    
    print(f"\n📩 ОТРИМАНО: {chat_title}")

    if chat_title == 'dtek_ua' and REGION_TAG not in text: return
    if chat_title == 'avariykaaa' and IGNORE_PROVIDER in text: return
    if any(w in text for w in NOISE_WORDS) and PROVIDER_TAG not in text: return

    if any(w in text for w in EMERGENCY_WORDS):
        msg = "🚨 **ТРИВОГА: ЕКСТРЕНІ ВІДКЛЮЧЕННЯ!**"
        await client.send_message(MAIN_ACCOUNT_USERNAME, msg, file=IMG_EMERGENCY)
        return

    if event.message.photo:
        print(f"📸 Аналізую через Gemini 2.0...")
        path = await event.message.download_media()
        schedule = await asyncio.to_thread(ask_gemini_v2, path, event.message.message)
        os.remove(path)
        
        if schedule:
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
                try: await client.send_message(CHANNEL_ID, msg, file=IMG_SCHEDULE)
                except: pass

async def startup_check():
    try: await client.send_message(MAIN_ACCOUNT_USERNAME, "🟢 **GEMINI 2.0 ACTIVE**\nМодель знайдено. Працюю.")
    except: pass

with client:
    client.loop.run_until_complete(startup_check())
    client.run_until_disconnected()
