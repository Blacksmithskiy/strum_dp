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

# Настройки из секретов GitHub
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']

# Конфигурация
MY_GROUP = "1.1"
SOURCE_CHANNELS = ['dtek_ua', 'avariykaaa']

# Инициализация ИИ
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

async def get_tasks_service():
    creds_dict = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('tasks', 'v1', credentials=creds)

async def ask_gemini_about_schedule(photo_path, text):
    prompt = f"""
    Это график отключений света. Проверь его для группы {MY_GROUP}.
    Текст поста: {text}
    Если в тексте или на картинке есть время отключения для группы {MY_GROUP} на СЕГОДНЯ или ЗАВТРА, 
    верни ответ ТОЛЬКО в формате JSON: 
    [{{"start": "YYYY-MM-DDTHH:MM:SS", "end": "YYYY-MM-DDTHH:MM:SS"}}]
    Если данных нет, верни пустой список [].
    """
    img = genai.upload_file(photo_path)
    response = model.generate_content([prompt, img])
    try:
        # Убираем возможные кавычки markdown из ответа
        clean_res = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_res)
    except:
        return []

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def handler(event):
    if event.message.photo:
        print(f"📸 Вижу новый график в {event.chat.title}...")
        path = await event.message.download_media()
        
        schedule = await ask_gemini_about_schedule(path, event.message.message)
        os.remove(path)
        
        if schedule:
            service = await get_tasks_service()
            for entry in schedule:
                start_dt = parser.parse(entry['start'])
                remind_dt = start_dt - timedelta(minutes=15)
                
                task = {
                    'title': f"💡 ОТКЛЮЧЕНИЕ СВЕТА (Группа {MY_GROUP})",
                    'notes': f"С {entry['start']} до {entry['end']}",
                    'due': remind_dt.isoformat() + 'Z'
                }
                service.tasks().insert(tasklist='@default', body=task).execute()
                print(f"✅ Задача создана на {start_dt}")

print("🚀 ИИ-Агент запущен и следит за группой 1.1...")
with client:
    client.run_until_disconnected()
