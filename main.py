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

# ДОДАНО 'me' ДЛЯ ТЕСТІВ ЧЕРЕЗ ЗБЕРЕЖЕНЕ
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
    print("🤖 Gemini: Починаю аналіз картинки...")
    prompt = f"""
    Це графік відключень світла. 
    Регіон: Дніпропетровщина. Компанія: ДТЕК.
    Знайди час відключення для групи {MY_GROUP}.
    Текст поста: {text}
    Поверни JSON: [{{"start": "YYYY-MM-DDTHH:MM:SS", "end": "YYYY-MM-DDTHH:MM:SS"}}]
    Якщо графіків немає, поверни [].
    """
    try:
        img = genai.upload_file(photo_path)
        response = model.generate_content([prompt, img])
        print(f"🤖 Gemini Відповідь (Сира): {response.text}") # ДИВИМОСЬ ЩО ВІДПОВІВ ШІ
        clean_res = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_res)
    except Exception as e:
        print(f"❌ Gemini Помилка: {e}")
        return []

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def handler(event):
    text = (event.message.message or "").lower()
    chat_title = event.chat.username if event.chat and hasattr(event.chat, 'username') else "Unknown/Me"
    
    print(f"\n📩 ОТРИМАНО ПОВІДОМЛЕННЯ в {chat_title}")
    print(f"📝 Текст (перші 50 симв): {text[:50]}...")

    # 1. ПЕРЕВІРКА ФІЛЬТРІВ (З ЛОГАМИ)
    if chat_title == 'dtek_ua' and REGION_TAG not in text: 
        print(f"⛔️ Ігнор: Немає тегу '{REGION_TAG}'")
        return
    if chat_title == 'avariykaaa':
        if IGNORE_PROVIDER in text and PROVIDER_TAG not in text: 
            print("⛔️ Ігнор: Це провайдер ЦЕК")
            return
    if any(w in text for w in NOISE_WORDS) and PROVIDER_TAG not in text: 
        print("⛔️ Ігнор: Це про воду/труби")
        return

    # 2. РЕЖИМ ТРИВОГИ
    if any(w in text for w in EMERGENCY_WORDS):
        print("🚨 ВИЯВЛЕНО ЕКСТРЕНІ ВІДКЛЮЧЕННЯ!")
        alert_msg = (
            "🚨 **ТРИВОГА: ЕКСТРЕНІ ВІДКЛЮЧЕННЯ!**\n"
            "⚠️ Графіки скасовано.\n🔋 **Зарядіться!**"
        )
        await client.send_message(MAIN_ACCOUNT_USERNAME, alert_msg, file=IMG_EMERGENCY)
        try: await client.send_message(CHANNEL_ID, alert_msg, file=IMG_EMERGENCY)
        except: pass
        try:
            service = await get_tasks_service()
            task = {'title': "🚨 ЕКСТРЕНІ!", 'due': datetime.utcnow().isoformat() + 'Z'}
            service.tasks().insert(tasklist='@default', body=task).execute()
        except: pass
        return

    # 3. ШТАТНИЙ РЕЖИМ
    if event.message.photo:
        print(f"📸 Фото знайдено. Відправляю в Gemini...")
        path = await event.message.download_media()
        schedule = await ask_gemini_about_schedule(path, event.message.message)
        os.remove(path)
        
        if schedule:
            print(f"✅ Графік знайдено: {schedule}")
            service = await get_tasks_service()
            for entry in schedule:
                start_dt = parser.parse(entry['start'])
                end_dt = parser.parse(entry['end'])
                
                # Google Task
                remind_dt = start_dt - timedelta(minutes=15)
                task = {
                    'title': f"💡 ВІДКЛЮЧЕННЯ (Гр. {MY_GROUP})",
                    'notes': f"Час: {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}",
                    'due': remind_dt.isoformat() + 'Z'
                }
                service.tasks().insert(tasklist='@default', body=task).execute()
                print("✅ Завдання створено в Google")
                
                # Повідомлення
                msg = f"⚡️ **Світла не буде з {start_dt.strftime('%H:%M')} до {end_dt.strftime('%H:%M')}**\n(Група {MY_GROUP})."
                await client.send_message(MAIN_ACCOUNT_USERNAME, msg, file=IMG_SCHEDULE)
                try: await client.send_message(CHANNEL_ID, msg, file=IMG_SCHEDULE)
                except: pass
                print("✅ Повідомлення відправлено")
        else:
            print("⚠️ Gemini повернув порожній список (графік не для вашої групи?)")
    else:
        print("ℹ️ У повідомленні немає фото.")

print(f"🚀 STRUM DEBUG: Слухаю {SOURCE_CHANNELS}. Пиши в 'Збережене' для тесту!")
with client:
    client.run_until_disconnected()
