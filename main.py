import os
import json
import asyncio
from datetime import datetime, timedelta
from dateutil import parser
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import google.generativeai as genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Налаштування з секретів GitHub
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']

# Конфігурація
MY_GROUP = "1.1"
SOURCE_CHANNELS = ['dtek_ua', 'avariykaaa']

# Фільтри
REGION_TAG = "дніпропетровщина"
PROVIDER_TAG = "дтек"
IGNORE_PROVIDER = "цек"
NOISE_WORDS = ['вода', 'водоканал', 'труб', 'каналізац', 'опалення']

# Ініціалізація ШІ
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

async def get_tasks_service():
    creds_dict = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('tasks', 'v1', credentials=creds)

async def ask_gemini_about_schedule(photo_path, text):
    # Промпт став суворішим та фокусованим
    prompt = f"""
    Це графік відключень світла. 
    ВАЖЛИВО: Нас цікавить ТІЛЬКИ Дніпропетровська область та ТІЛЬКИ компанія ДТЕК.
    Ігноруй дані для Києва, Одеси, Київщини чи Одещини. Ігноруй компанію ЦЕК.
    Знайди графік для групи {MY_GROUP}.
    Текст поста: {text}
    Поверни відповідь ТІЛЬКИ у форматі JSON: 
    [{{"start": "YYYY-MM-DDTHH:MM:SS", "end": "YYYY-MM-DDTHH:MM:SS"}}]
    Якщо даних для Дніпропетровщини або групи {MY_GROUP} немає, поверни порожній список [].
    """
    img = genai.upload_file(photo_path)
    response = model.generate_content([prompt, img])
    try:
        clean_res = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_res)
    except:
        return []

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def handler(event):
    raw_text = (event.message.message or "").lower()
    
    # 1. Фільтр провайдера та регіону (Первинна перевірка)
    # Якщо це канал DTEK, шукаємо згадку нашої області
    if event.chat.username == 'dtek_ua' and REGION_TAG not in raw_text:
        return

    # Якщо це Аварійка, відсікаємо ЦЕК, якщо немає згадки ДТЕК
    if event.chat.username == 'avariykaaa':
        if IGNORE_PROVIDER in raw_text and PROVIDER_TAG not in raw_text:
            print("📎 Пропускаю пост ЦЕК")
            return

    # 2. Фільтр шуму (вода/ремонти)
    if any(word in raw_text for word in NOISE_WORDS) and PROVIDER_TAG not in raw_text:
        return

    if event.message.photo:
        print(f"📸 Аналізую графік Дніпропетровщини у {event.chat.title}...")
        path = await event.message.download_media()
        
        schedule = await ask_gemini_about_schedule(path, event.message.message)
        os.remove(path)
        
        if schedule:
            service = await get_tasks_service()
            for entry in schedule:
                start_dt = parser.parse(entry['start'])
                end_dt = parser.parse(entry['end'])
                
                # Завдання в Google Tasks
                remind_dt = start_dt - timedelta(minutes=15)
                task = {
                    'title': f"💡 ВІДКЛЮЧЕННЯ (Група {MY_GROUP})",
                    'notes': f"Дніпропетровщина. ДТЕК. З {start_dt.strftime('%H:%M')} до {end_dt.strftime('%H:%M')}",
                    'due': remind_dt.isoformat() + 'Z'
                }
                service.tasks().insert(tasklist='@default', body=task).execute()
                
                # Особисте повідомлення
                time_str = f"з {start_dt.strftime('%H:%M')} до {end_dt.strftime('%H:%M')}"
                dm_text = f"⚡️ **Світла не буде {time_str}** (Дніпропетровщина, ДТЕК), пора зарядити power bank"
                await client.send_message('me', dm_text)
                
                print(f"✅ Сповіщення для групи {MY_GROUP} надіслано")
        else:
            print(f"ℹ️ Пост не містить актуальних графіків для вашої групи.")

print(f"🚀 Агент STRUM на варті. Тільки Дніпропетровщина, тільки ДТЕК, група {MY_GROUP}.")

with client:
    client.run_until_disconnected()
