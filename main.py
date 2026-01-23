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

# === ВАШІ НАЛАШТУВАННЯ ===
MY_GROUP = "1.1"
MAIN_ACCOUNT_USERNAME = "@nemovisio" 
CHANNEL_USERNAME = "@strum_dp"

# === СИСТЕМНІ ЗМІННІ ===
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']

# === ВІЗУАЛІЗАЦІЯ ===
IMG_SCHEDULE = "https://arcanavisio.com/wp-content/uploads/2026/01/MAIN.jpg"
IMG_EMERGENCY = "https://arcanavisio.com/wp-content/uploads/2026/01/EXTRA.jpg"

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

def ask_gemini_smart(photo_path, text):
    # ПОВНІ АДРЕСИ (Stable v1 та Beta v1beta)
    urls_to_try = [
        # 1. Основна стабільна (Flash 1.5) - v1
        "https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent",
        # 2. Новіша стабільна (Flash 1.5-002) - v1beta
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-002:generateContent",
        # 3. Стара надійна (Pro Vision) - v1
        "https://generativelanguage.googleapis.com/v1/models/gemini-pro-vision:generateContent",
        # 4. Експериментальна (2.0) - v1beta
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent"
    ]
    
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

    last_error = ""

    for url in urls_to_try:
        # Витягуємо назву моделі для логів
        model_name = "Unknown"
        if "gemini-1.5-flash" in url: model_name = "Flash 1.5 (Stable)"
        if "gemini-1.5-flash-002" in url: model_name = "Flash 002 (Beta)"
        if "gemini-pro-vision" in url: model_name = "Pro Vision (Legacy)"
        if "gemini-2.0" in url: model_name = "Flash 2.0 (Exp)"

        full_url = f"{url}?key={GEMINI_KEY}"
        
        for attempt in range(2):
            try:
                #print(f"👉 Пробую: {model_name}...") # (Можна розкоментувати для дебагу)
                response = requests.post(full_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=30)
                
                if response.status_code == 200:
                    try:
                        result = response.json()
                        if 'candidates' in result and result['candidates']:
                            raw_text = result['candidates'][0]['content']['parts'][0]['text']
                            clean_res = raw_text.replace('```json', '').replace('```', '').strip()
                            parsed = json.loads(clean_res)
                            return parsed # УСПІХ!
                        else:
                            return [] # Пуста відповідь (немає графіків)
                    except Exception as e:
                        return f"PARSE_ERROR: {raw_text}"
                elif response.status_code == 429:
                    time.sleep(5) # Чекаємо і пробуємо ту ж модель
                    continue
                else:
                    last_error = f"{model_name}: HTTP {response.status_code}"
                    break # Ця модель не працює, йдемо до наступної
            except Exception as e:
                last_error = str(e)
                break
    return f"ALL_FAILED. Ost error: {last_error}"

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def handler(event):
    text = (event.message.message or "").lower()
    chat_title = event.chat.username if event.chat and hasattr(event.chat, 'username') else "Unknown/Me"
    
    # Фільтри
    if chat_title == 'dtek_ua' and REGION_TAG not in text: return
    if chat_title == 'avariykaaa' and IGNORE_PROVIDER in text: return
    if any(w in text for w in NOISE_WORDS) and PROVIDER_TAG not in text: return

    # ЕКСТРЕНІ
    if any(w in text for w in EMERGENCY_WORDS):
        msg = "🚨 **ТРИВОГА: ЕКСТРЕНІ ВІДКЛЮЧЕННЯ!**"
        await client.send_message(MAIN_ACCOUNT_USERNAME, msg, file=IMG_EMERGENCY)
        try: await client.send_message(CHANNEL_USERNAME, msg, file=IMG_EMERGENCY)
        except: pass
        return

    # ГРАФІКИ
    if event.message.photo:
        status_msg = await client.send_message(MAIN_ACCOUNT_USERNAME, "🧐 **Бачу графік.** Пробую різні моделі AI...")
        
        path = await event.message.download_media()
        result = await asyncio.to_thread(ask_gemini_smart, path, event.message.message)
        os.remove(path)
        
        if isinstance(result, list):
            if not result:
                await client.edit_message(status_msg, "✅ **Аналіз завершено:** Графік розпізнано, але для **Групи 1.1** відключень не знайдено.")
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
        else:
            await client.edit_message(status_msg, f"❌ **Все ще помилка:**\n`{str(result)}`\nСпробуйте пізніше або перевірте ключ.")

async def startup_check():
    try: await client.send_message(MAIN_ACCOUNT_USERNAME, "🟢 **STRUM FINAL:** Алгоритм пошуку API оновлено.")
    except: pass

with client:
    client.loop.run_until_complete(startup_check())
    client.run_until_disconnected()
