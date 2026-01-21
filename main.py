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

# Ваша група для моніторингу
MY_GROUP = "1.1"
SOURCE_CHANNELS = ['dtek_ua', 'avariykaaa']

# Ініціалізація ШІ
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

async def get_tasks_service():
    creds_dict = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('tasks', 'v1', credentials=creds)

async def ask_gemini_about_schedule(photo_path, text):
    prompt = f"""
    Це графік відключень світла у Дніпрі. Перевір його для групи {MY_GROUP}.
    Текст поста: {text}
    Якщо в тексті або на картинці є час відключення для групи {MY_GROUP} на СЕГОДНЯ або ЗАВТРА, 
    поверни відповідь ТІЛЬКИ у форматі JSON: 
    [{{"start": "YYYY-MM-DDTHH:MM:SS", "end": "YYYY-MM-DDTHH:MM:SS"}}]
    Якщо даних немає, поверни порожній список [].
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
    # Тепер код всередині функції має вірні відступи
    if event.message.photo:
        print(f"📸 Виявлено новий графік у {event.chat.title}. Аналізую...")
        path = await event.message.download_media()
        
        schedule = await ask_gemini_about_schedule(path, event.message.message)
        os.remove(path)
        
        if schedule:
            service = await get_tasks_service()
            for entry in schedule:
                start_dt = parser.parse(entry['start'])
                # Нагадування за 15 хвилин до початку
                remind_dt = start_dt - timedelta(minutes=15)
                
                task = {
                    'title': f"💡 ВІДКЛЮЧЕННЯ (Група {MY_GROUP})",
                    'notes': f"Заплановано з {entry['start']} до {entry['end']}",
                    'due': remind_dt.isoformat() + 'Z'
                }
                service.tasks().insert(tasklist='@default', body=task).execute()
                print(f"✅ Завдання створено на {start_dt}")
        else:
            print(f"ℹ️ У новому пості немає графіків для групи {MY_GROUP}.")

print(f"🚀 ІІ-Агент STRUM запущений. Моніторинг групи {MY_GROUP} активний...")

with client:
    client.run_until_disconnected()
