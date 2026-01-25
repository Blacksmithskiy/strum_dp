import os
import json
import base64
import time
import re
import requests
import asyncio
import random
import io
from datetime import datetime, timedelta
from dateutil import parser
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# === НАЛАШТУВАННЯ ===
MY_PERSONAL_GROUP = "1.1"
MAIN_ACCOUNT_USERNAME = "@nemovisio"
CHANNEL_USERNAME = "@strum_dp"
SIREN_CHANNEL_USER = "sirena_dp"
DNIPRO_LAT = 48.46
DNIPRO_LON = 35.04

# === ЗМІННІ ===
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']

# === МЕДІА (ПОСИЛАННЯ) ===
URL_MORNING = "https://arcanavisio.com/wp-content/uploads/2026/01/01_MORNING.jpg"
URL_EVENING = "https://arcanavisio.com/wp-content/uploads/2026/01/02_EVENING.jpg"
URL_GRAFIC = "https://arcanavisio.com/wp-content/uploads/2026/01/03_GRAFIC.jpg"
URL_NEW_GRAFIC = "https://arcanavisio.com/wp-content/uploads/2026/01/04_NEW-GRAFIC.jpg"
URL_EXTRA_START = "https://arcanavisio.com/wp-content/uploads/2026/01/05_EXTRA_GRAFIC.jpg"
URL_EXTRA_STOP = "https://arcanavisio.com/wp-content/uploads/2026/01/06_EXTRA_STOP.jpg"
URL_TREVOGA = "https://arcanavisio.com/wp-content/uploads/2026/01/07_TREVOGA.jpg"
URL_TREVOGA_STOP = "https://arcanavisio.com/wp-content/uploads/2026/01/08_TREVOGA_STOP.jpg"

# === ТЕКСТИ (З ВІДСТУПАМИ) ===
TXT_TREVOGA = "⚠️❗️ **УВАГА! ОГОЛОШЕНО ПОВІТРЯННУ ТРИВОГУ.**\n\n🏃 **ВСІМ ПРОЙТИ В УКРИТТЯ.**"
TXT_TREVOGA_STOP = "✅ **ВІДБІЙ ПОВІТРЯННОЇ ТРИВОГИ.**"
TXT_EXTRA_START = "⚡❗️**УВАГА! ЗАСТОСОВАНІ ЕКСТРЕНІ ВІДКЛЮЧЕННЯ.**\n\n**ПІД ЧАС ЕКСТРЕНИХ ВІДКЛЮЧЕНЬ ГРАФІКИ НЕ ДІЮТЬ.**"
TXT_EXTRA_STOP = "⚡️✔️ **ЕКСТРЕНІ ВІДКЛЮЧЕННЯ СВІТЛА СКАСОВАНІ.**"

FOOTER = """
___

⭐️ Підписуйтесь та поділіться з родичами і друзями:

⚡СТРУМ ДНІПРА https://t.me/strum_dp

❤️ ПІДТРИМКА СЕРВІСУ:

🔗 https://send.monobank.ua/jar/9gBQ4LTLUa
___

@strum_dp"""

# Мотивація
MOTIVATION = [
    "Сьогодні чудовий день, щоб зробити щось важливе!",
    "Навіть найтемніша ніч закінчується світанком.",
    "Тримаймо стрій! Перемога вже близько.",
    "Твоя енергія заряджає цей світ. Світи яскравіше!",
    "Маленькі кроки ведуть до великих змін.",
    "Вір у себе, як ми віримо в ППО!",
    "Не чекай на світло, будь світлом сам.",
    "Сьогоднішній день — це новий шанс.",
    "Все буде Україна. Головне — не зупинятися.",
    "Зберігай спокій та економ електроенергію.",
    "Світло всередині нас ніколи не згасне."
]

processing_lock = asyncio.Lock()
REAL_SIREN_ID = None
IS_ALARM_ACTIVE = False 

async def get_tasks_service():
    creds_dict = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('tasks', 'v1', credentials=creds)

# === БЕЗПЕЧНА ВІДПРАВКА (ЯК ФОТО) ===
async def send_safe(text, img_url):
    try:
        response = await asyncio.to_thread(requests.get, img_url)
        if response.status_code == 200:
            photo_file = io.BytesIO(response.content)
            photo_file.name = "image.jpg"
            await client.send_message(CHANNEL_USERNAME, text + FOOTER, file=photo_file)
        else:
            await client.send_message(CHANNEL_USERNAME, text + FOOTER)
    except Exception as e:
        print(f"Send Error: {e}")
        try: await client.send_message(CHANNEL_USERNAME, text + FOOTER)
        except: pass

# === 1. РАНОК (08:00) ===
async def morning_loop():
    while True:
        now = datetime.now()
        target = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now >= target: target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        
        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={DNIPRO_LAT}&longitude={DNIPRO_LON}&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Europe%2FKyiv"
            w = requests.get(url).json().get('daily', {})
            t_min, t_max = w['temperature_2m_min'][0], w['temperature_2m_max'][0]
            rain = w['precipitation_probability_max'][0]
            
            w_text = f"🌡 **Температура:** {t_min}°C ... {t_max}°C\n☔️ **Опади:** {'Можливі' if rain > 50 else 'Малоймовірні'} ({rain}%)"
            status = "🔴 Тривога активна!" if IS_ALARM_ACTIVE else "🟢 Небо чисте."
            quote = random.choice(MOTIVATION)
            
            msg = f"☀️ **ДОБРОГО РАНКУ, ДНІПРО!**\n\n{w_text}\n\n📢 **Статус:** {status}\n\n💬 _{quote}_"
            await send_safe(msg, URL_MORNING)
        except: pass
        await asyncio.sleep(60)

# === 2. ВЕЧІР (22:00) ===
async def evening_loop():
    while True:
        now = datetime.now()
        target = now.replace(hour=22, minute=0, second=0, microsecond=0)
        if now >= target: target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        
        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={DNIPRO_LAT}&longitude={DNIPRO_LON}&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Europe%2FKyiv"
            w = requests.get(url).json().get('daily', {})
            t_min, t_max = w['temperature_2m_min'][1], w['temperature_2m_max'][1]
            
            msg = f"🌒 **НА ДОБРАНІЧ, ДНІПРО!**\n\n🌡 **Погода на завтра:** {t_min}°C ... {t_max}°C\n\n🔋 Не забудьте перевірити заряд гаджетів."
            await send_safe(msg, URL_EVENING)
        except: pass
        await asyncio.sleep(60)

# === ПАРСЕР ===
def parse_schedule(text):
    schedule = []
    for line in text.split('\n'):
        line = line.lower().strip()
        groups = re.findall(r'\b(\d\.\d)\b', line)
        times = re.findall(r'(\d{1,2}:\d{2}).*?(\d{1,2}:\d{2})', line)
        if groups and times:
            today = datetime.now().strftime('%Y-%m-%d')
            for gr in groups:
                if gr in [t[0] for t in times] or gr in [t[1] for t in times]: continue
                for t in times:
                    schedule.append({"group": gr, "start": f"{today}T{t[0]}:00", "end": f"{today}T{t[1]}:00"})
    return schedule

def ask_gemini(photo_path):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_KEY}"
    try:
        with open(photo_path, "rb") as f: img = base64.b64encode(f.read()).decode("utf-8")
        payload = {"contents": [{"parts": [{"text": "Extract schedule. JSON: [{\"group\": \"1.1\", \"start\": \"HH:MM\", \"end\": \"HH:MM\"}]"}, {"inline_data": {"mime_type": "image/jpeg", "data": img}}]}]}
        r = requests.post(url, json=payload, headers={'Content-Type': 'application/json'})
        return json.loads(r.json()['candidates'][0]['content']['parts'][0]['text'].replace('```json', '').replace('```', '').strip())
    except: return []

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage())
async def handler(event):
    text = (event.message.message or "").lower()
    chat_id = event.chat_id
    global IS_ALARM_ACTIVE

    # === СИРЕНА ===
    is_siren = False
    if REAL_SIREN_ID and chat_id == REAL_SIREN_ID: is_siren = True
    if event.chat and getattr(event.chat, 'username', '').lower() == SIREN_CHANNEL_USER: is_siren = True
    if "test_siren" in text and event.out: is_siren = True
    if event.fwd_from and ("сирена" in text or "тривог" in text): is_siren = True

    if is_siren:
        if "відбій" in text or "отбой" in text:
            IS_ALARM_ACTIVE = False
            await send_safe(TXT_TREVOGA_STOP, URL_TREVOGA_STOP)
        elif "тривог" in text or "тревога" in text:
            IS_ALARM_ACTIVE = True
            await send_safe(TXT_TREVOGA, URL_TREVOGA)
        return

    # === ЕКСТРЕНІ ===
    if any(w in text for w in ['екстрені', 'экстренные']) and any(w in text for w in ['скасовані', 'отмена']):
        if any(w in text for w in ['дніпро', 'днепр', 'дтек', 'дтэк']):
            await send_safe(TXT_EXTRA_STOP, URL_EXTRA_STOP)
            return

    if any(w in text for w in ['екстрені', 'экстренные']):
        if any(w in text for w in ['дніпро', 'днепр', 'дтек', 'дтэк']):
            await send_safe(TXT_EXTRA_START, URL_EXTRA_START)
            return

    # === ГРАФІКИ ===
    schedule = []
    if re.search(r'\d\.\d', text) and re.search(r'\d{1,2}:\d{2}', text):
        schedule = parse_schedule(event.message.message)
    elif event.message.photo:
        async with processing_lock:
            try:
                path = await event.message.download_media()
                schedule = await asyncio.to_thread(ask_gemini, path)
                os.remove(path)
            except: pass

    if schedule and isinstance(schedule, list):
        service = await get_tasks_service()
        schedule.sort(key=lambda x: x.get('group', ''))
        
        is_update = any(w in text for w in ['зміни', 'оновлення', 'изменения', 'обновление', 'новые'])
        date_now = datetime.now().strftime('%d.%m.%Y')
        
        if is_update:
            header = f"⚡️✔️ **ОНОВЛЕННЯ ГРАФІКІВ ВІДКЛЮЧЕНЬ СВІТЛА.**\n📅 **На {date_now}**"
            img_url = URL_NEW_GRAFIC
        else:
            header = f"⚡️📌 **ГРАФІКИ ВІДКЛЮЧЕНЬ СВІТЛА.**\n📅 **На {date_now}**"
            img_url = URL_GRAFIC

        msg_lines = [header, ""]
        prev_grp = None
        
        for entry in schedule:
            try:
                start = parser.parse(entry['start'])
                end = parser.parse(entry['end'])
                grp = entry.get('group', '?')
                
                main_grp = grp.split('.')[0] if '.' in grp else grp
                if prev_grp and main_grp != prev_grp: msg_lines.append("➖➖➖➖➖➖➖➖")
                prev_grp = main_grp
                
                # Компактне виділення 1.1
                if grp == MY_PERSONAL_GROUP:
                    msg_lines.append(f"👉 🏠 **Гр. {grp}:** {start.strftime('%H:%M')} - {end.strftime('%H:%M')} 👈")
                else:
                    msg_lines.append(f"🔹 **Гр. {grp}:** {start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
                
                # Tasks (тільки 1.1)
                if grp == MY_PERSONAL_GROUP:
                    notif = start - timedelta(hours=2, minutes=10)
                    task = {'title': f"💡 СВІТЛО (Гр. {grp})", 'notes': f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}", 'due': notif.isoformat() + 'Z'}
                    try: service.tasks().insert(tasklist='@default', body=task).execute()
                    except: pass
            except: continue
        
        if len(msg_lines) > 2:
            await send_safe("\n".join(msg_lines), img_url)

async def startup():
    global REAL_SIREN_ID
    try:
        await client(JoinChannelRequest(SIREN_CHANNEL_USER))
        e = await client.get_entity(SIREN_CHANNEL_USER)
        REAL_SIREN_ID = int(f"-100{e.id}")
        print("✅ Bot Started.")
    except: pass

if __name__ == '__main__':
    client.start()
    client.loop.create_task(morning_loop())
    client.loop.create_task(evening_loop())
    client.loop.run_until_complete(startup())
    client.run_until_disconnected()
