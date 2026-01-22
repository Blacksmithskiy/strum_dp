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

# === НАСТРОЙКИ (НЕ МЕНЯТЬ) ===
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']

# === ВАШИ ЛИЧНЫЕ НАСТРОЙКИ ===
MY_GROUP = "1.1" 
# 👇 ВПИШИТЕ СЮДА ЮЗЕРНЕЙМ ВАШЕГО ОСНОВНОГО АККАУНТА (куда слать отчеты)
MAIN_ACCOUNT_USERNAME = "@nemovisio"  

SOURCE_CHANNELS = ['dtek_ua', 'avariykaaa']
REGION_TAG = "дніпропетровщина"
PROVIDER_TAG = "дтек"
IGNORE_PROVIDER = "цек"
NOISE_WORDS = ['вода', 'водоканал', 'труб', 'каналізац', 'опалення']

# Инициализация ИИ
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

async def get_tasks_service():
    creds_dict = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('tasks', 'v1', credentials=creds)

async def ask_gemini_about_schedule(photo_path, text):
    prompt = f"""
    Это график отключений света. Нас интересует ТІЛЬКИ Днепропетровская область и ТІЛЬКИ ДТЕК.
    Игнорируй Киев, Одессу, ЦЕК.
    Найди ячейки для группы {MY_GROUP}.
    Текст поста: {text}
    Верни JSON: [{{"start": "YYYY-MM-DDTHH:MM:SS", "end": "YYYY-MM-DDTHH:MM:SS"}}]
    Если данных нет, верни [].
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
    
    # ФИЛЬТРЫ: Только Днепр, Только ДТЕК, Без воды/труб
    if event.chat.username == 'dtek_ua' and REGION_TAG not in text: return
    if event.chat.username == 'avariykaaa':
        if IGNORE_PROVIDER in text and PROVIDER_TAG not in text: return
    if any(w in text for w in NOISE_WORDS) and PROVIDER_TAG not in text: return

    if event.message.photo:
        print(f"📸 Анализ графика для {MY_GROUP}...")
        path = await event.message.download_media()
        schedule = await ask_gemini_about_schedule(path, event.message.message)
        os.remove(path)
        
        if schedule:
            service = await get_tasks_service()
            for entry in schedule:
                start_dt = parser.parse(entry['start'])
                end_dt = parser.parse(entry['end'])
                
                # 1. Задача в Google
                remind_dt = start_dt - timedelta(minutes=15)
                task = {
                    'title': f"💡 ОТКЛЮЧЕНИЕ (Гр. {MY_GROUP})",
                    'notes': f"ДТЕК. {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}",
                    'due': remind_dt.isoformat() + 'Z'
                }
                service.tasks().insert(tasklist='@default', body=task).execute()
                
                # 2. Сообщение в Личку Основному Аккаунту
                msg = f"⚡️ **Світла не буде з {start_dt.strftime('%H:%M')} до {end_dt.strftime('%H:%M')}**, пора зарядити power bank"
                await client.send_message(MAIN_ACCOUNT_USERNAME, msg)
                print(f"✅ Уведомление отправлено на {MAIN_ACCOUNT_USERNAME}")

print(f"🚀 Агент запущен на Втором аккаунте. Следит за {MY_GROUP} для {MAIN_ACCOUNT_USERNAME}")
with client:
    client.run_until_disconnected()
