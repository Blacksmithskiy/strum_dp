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

# === ВАШІ НАЛАШТУВАННЯ ===
MY_GROUP = "1.1"
MAIN_ACCOUNT_USERNAME = "@nemovisio"  # Ваш основний акаунт
CHANNEL_ID = "@strum_dp"              # Ваш канал

# === ВІЗУАЛІЗАЦІЯ (ВАШІ КАРТИНКИ) ===
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
    
    # 1. ФІЛЬТРИ
    if event.chat.username == 'dtek_ua' and REGION_TAG not in text: return
    if event.chat.username == 'avariykaaa':
        if IGNORE_PROVIDER in text and PROVIDER_TAG not in text: return
    if any(w in text for w in NOISE_WORDS) and PROVIDER_TAG not in text: return

    # 2. РЕЖИМ ТРИВОГИ (ЧЕРВОНА КАРТИНКА)
    if any(w in text for w in EMERGENCY_WORDS):
        print("🚨 ВИЯВЛЕНО ЕКСТРЕНІ ВІДКЛЮЧЕННЯ!")
        alert_msg = (
            "🚨 **ТРИВОГА: ЕКСТРЕНІ ВІДКЛЮЧЕННЯ!**\n\n"
            "⚠️ Дніпропетровщина: Графіки наразі НЕ діють.\n"
            "⚡️ Світло може зникнути в будь-який момент.\n"
            "🔋 **Терміново зарядіть телефони та павербанки!**"
        )
        
        # Розсилка з картинкою IMG_EMERGENCY
        await client.send_message(MAIN_ACCOUNT_USERNAME, alert_msg, file=IMG_EMERGENCY)
        try:
            await client.send_message(CHANNEL_ID, alert_msg, file=IMG_EMERGENCY)
        except Exception as e:
            print(f"Помилка публікації в канал: {e}")
        
        # Google Task
        try:
            service = await get_tasks_service()
            task = {
                'title': "🚨 ЕКСТРЕНІ ВІДКЛЮЧЕННЯ!",
                'notes': "Графіки скасовано. Зарядити пристрої.",
                'due': datetime.utcnow().isoformat() + 'Z'
            }
            service.tasks().insert(tasklist='@default', body=task).execute()
        except: pass
        
        return

    # 3. ШТАТНИЙ РЕЖИМ (СИНЯ КАРТИНКА)
    if event.message.photo:
        print(f"📸 Аналіз графіка для {CHANNEL_ID}...")
        path = await event.message.download_media()
        schedule = await ask_gemini_about_schedule(path, event.message.message)
        os.remove(path)
        
        if schedule:
            service = await get_tasks_service()
            for entry in schedule:
                start_dt = parser.parse(entry['start'])
                end_dt = parser.parse(entry['end'])
                
                # Google Task
                remind_dt = start_dt - timedelta(minutes=15)
                task = {
                    'title': f"💡 ВІДКЛЮЧЕННЯ (Гр. {MY_GROUP})",
                    'notes': f"Див. {CHANNEL_ID}. Час: {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}",
                    'due': remind_dt.isoformat() + 'Z'
                }
                service.tasks().insert(tasklist='@default', body=task).execute()
                
                # Повідомлення з картинкою IMG_SCHEDULE
                msg = f"⚡️ **Світла не буде з {start_dt.strftime('%H:%M')} до {end_dt.strftime('%H:%M')}**\n(Група {MY_GROUP}).\n\n🔋 *Поставте гаджети на зарядку.*"
                
                await client.send_message(MAIN_ACCOUNT_USERNAME, msg, file=IMG_SCHEDULE)
                try:
                    await client.send_message(CHANNEL_ID, msg, file=IMG_SCHEDULE)
                except: pass

print(f"🚀 STRUM: Активний. Ціль: {MAIN_ACCOUNT_USERNAME}")
with client:
    client.run_until_disconnected()
