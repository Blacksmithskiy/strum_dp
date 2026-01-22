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

# === НАЛАШТУВАННЯ ===
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']

# === ВАШІ ДАНІ ===
MY_GROUP = "1.1"
MAIN_ACCOUNT_USERNAME = "@nemovisio"  # 👈 Впишіть сюди нік ОСНОВНОГО акаунту
CHANNEL_ID = "@strum_dp"               # 👈 Канал для публікації

SOURCE_CHANNELS = ['dtek_ua', 'avariykaaa']
REGION_TAG = "дніпропетровщина"
PROVIDER_TAG = "дтек"
IGNORE_PROVIDER = "цек"
NOISE_WORDS = ['вода', 'водоканал', 'труб', 'каналізац', 'опалення']

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

async def get_tasks_service():
    creds_dict = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('tasks', 'v1', credentials=creds)

async def ask_gemini_about_schedule(photo_path, text):
    prompt = f"""
    Це графік відключень світла. 
    Регіон: Дніпропетровщина. Компанія: ДТЕК.
    Знайди час відключення для групи {MY_GROUP}.
    Текст поста: {text}
    Поверни JSON: [{{"start": "YYYY-MM-DDTHH:MM:SS", "end": "YYYY-MM-DDTHH:MM:SS"}}]
    Якщо графіків немає або це не Дніпро - поверни [].
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
    text = (event.message.message or "").lower()
    
    # ФІЛЬТРИ
    if event.chat.username == 'dtek_ua' and REGION_TAG not in text: return
    if event.chat.username == 'avariykaaa':
        if IGNORE_PROVIDER in text and PROVIDER_TAG not in text: return
    if any(w in text for w in NOISE_WORDS) and PROVIDER_TAG not in text: return

    if event.message.photo:
        print(f"📸 Аналіз для каналу {CHANNEL_ID} та групи {MY_GROUP}...")
        path = await event.message.download_media()
        schedule = await ask_gemini_about_schedule(path, event.message.message)
        os.remove(path)
        
        if schedule:
            service = await get_tasks_service()
            for entry in schedule:
                start_dt = parser.parse(entry['start'])
                end_dt = parser.parse(entry['end'])
                
                # 1. Google Task
                remind_dt = start_dt - timedelta(minutes=15)
                task = {
                    'title': f"💡 ВІДКЛЮЧЕННЯ (Гр. {MY_GROUP})",
                    'notes': f"Див. канал {CHANNEL_ID}. Час: {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}",
                    'due': remind_dt.isoformat() + 'Z'
                }
                service.tasks().insert(tasklist='@default', body=task).execute()
                
                # Текст повідомлення
                msg = f"⚡️ **Увага! Світла не буде з {start_dt.strftime('%H:%M')} до {end_dt.strftime('%H:%M')}**\n(Дніпропетровщина, Група {MY_GROUP}).\n\n🔋 *Поставте гаджети на зарядку.*"

                # 2. Особисте повідомлення (Вам)
                await client.send_message(MAIN_ACCOUNT_USERNAME, msg)
                
                # 3. Пост у Канал (@strum_dp)
                try:
                    await client.send_message(CHANNEL_ID, msg)
                    print(f"✅ Пост опубліковано в {CHANNEL_ID}")
                except Exception as e:
                    print(f"⚠️ Помилка публікації в канал (перевірте адмінку): {e}")

print(f"🚀 STRUM: Моніторинг активний. Ціль: {MAIN_ACCOUNT_USERNAME} та {CHANNEL_ID}")
with client:
    client.run_until_disconnected()
