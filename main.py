import os
import json
import base64
import time
import re
import requests
import asyncio
import random
import io
import logging
from datetime import datetime, timedelta
from dateutil import parser
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# === ЛОГУВАННЯ ===
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

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

# === МЕДІА ===
URL_MORNING = "https://arcanavisio.com/wp-content/uploads/2026/01/01_MORNING.jpg"
URL_EVENING = "https://arcanavisio.com/wp-content/uploads/2026/01/02_EVENING.jpg"
URL_GRAFIC = "https://arcanavisio.com/wp-content/uploads/2026/01/03_GRAFIC.jpg"
URL_NEW_GRAFIC = "https://arcanavisio.com/wp-content/uploads/2026/01/04_NEW-GRAFIC.jpg"
URL_EXTRA_START = "https://arcanavisio.com/wp-content/uploads/2026/01/05_EXTRA_GRAFIC.jpg"
URL_EXTRA_STOP = "https://arcanavisio.com/wp-content/uploads/2026/01/06_EXTRA_STOP.jpg"
URL_TREVOGA = "https://arcanavisio.com/wp-content/uploads/2026/01/07_TREVOGA.jpg"
URL_TREVOGA_STOP = "https://arcanavisio.com/wp-content/uploads/2026/01/08_TREVOGA_STOP.jpg"

# === ТЕКСТИ ===
TXT_TREVOGA = "⚠️❗️ **УВАГА! ОГОЛОШЕНО ПОВІТРЯННУ ТРИВОГУ.**\n\n🏃 **ВСІМ ПРОЙТИ В УКРИТТЯ.**"
TXT_TREVOGA_STOP = "✅ **ВІДБІЙ ПОВІТРЯННОЇ ТРИВОГИ.**"
TXT_EXTRA_START = "⚡❗️**УВАГА! ЗАСТОСОВАНІ ЕКСТРЕНІ ВІДКЛЮЧЕННЯ.**\n\n**ПІД ЧАС ЕКСТРЕНИХ ВІДКЛЮЧЕНЬ ГРАФІКИ НЕ ДІЮТЬ.**"
TXT_EXTRA_STOP = "⚡️✔️ **ЕКСТРЕНІ ВІДКЛЮЧЕННЯ СВІТЛА СКАСОВАНІ.**"

FOOTER = """
______

⭐️ Підписуйтесь та поділіться з родичами і друзями: ⚡️СТРУМ ДНІПРА https://t.me/strum_dp

❤️ ПІДТРИМКА СЕРВІСУ: 🔗 https://send.monobank.ua/jar/9gBQ4LTLUa
______

@strum_dp"""

# === ЗАПАСНІ СПИСКИ (Якщо AI мовчить) ===
BACKUP_MORNING = [
    "Той, хто має «Навіщо» жити, витримає майже будь-яке «Як».",
    "Ми робимо себе або сильними, або нещасними. Кількість зусиль однакова.",
    "Я — не те, що зі мною сталося. Я — те, ким я обираю стати.",
    "Там, де страх, місця немає творчості. Робіть маленькі, але усвідомлені дії.",
    "Найважливіша година — це зараз. Найважливіша людина — та, що поруч.",
    "Коли ззовні шторм, будуй храм всередині. Спокій — це теж зброя."
]

BACKUP_EVENING = [
    "День завершено. Відпусти турботи, як дерево скидає сухе листя.",
    "Сон — це найкраща медитація. (Далай-лама)",
    "Навіть найтемніша ніч закінчується світанком. Відпочивай.",
    "Завтра буде новий день і нові сили. Сьогодні — тиша.",
    "Мир всередині починається тоді, коли ти перестаєш контролювати все ззовні.",
    "Вдихни спокій, видихни напругу. Ти в безпеці своїх думок."
]

processing_lock = asyncio.Lock()
REAL_SIREN_ID = None
IS_ALARM_ACTIVE = False 
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

async def get_tasks_service():
    creds_dict = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('tasks', 'v1', credentials=creds)

# === ГЕНЕРАТОР ДУМОК (AI) ===
def get_ai_quote(mode="morning"):
    """
    mode="morning" -> Сила, дія, стоїцизм.
    mode="evening" -> Спокій, рефлексія, відновлення.
    """
    logger.info(f"Generating AI quote for: {mode}")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_KEY}"
    
    if mode == "morning":
        prompt = """
        Напиши одну коротку, глибоку та підтримуючу думку для українців на ранок.
        Теми: внутрішня сила, дія, стоїцизм, віра в себе (Юнг, Франкл, Марк Аврелій).
        Вимоги: Без банальностей. До 15 слів. Українська мова. Без лапок.
        """
        backup_list = BACKUP_MORNING
    else:
        prompt = """
        Напиши одну коротку, глибоку та заспокійливу думку для українців на вечір перед сном.
        Теми: відпускання дня, спокій, тиша, відновлення, надія на завтра, мудрість ночі.
        Вимоги: М'який тон. До 15 слів. Українська мова. Без лапок.
        """
        backup_list = BACKUP_EVENING
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        r = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
        if r.status_code == 200:
            text = r.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            text = text.replace('"', '').replace('*', '')
            logger.info(f"AI Quote ({mode}): {text}")
            return text
    except Exception as e:
        logger.error(f"Quote generation failed: {e}")
    
    return random.choice(backup_list)

# === ПОГОДА ===
def get_weather(is_tomorrow=False):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={DNIPRO_LAT}&longitude={DNIPRO_LON}&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&current=temperature_2m,wind_speed_10m&timezone=Europe%2FKyiv"
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200: return r.json()
        except: time.sleep(2)
    return None

# === ВІДПРАВКА ===
async def send_safe(text, img_url):
    try:
        response = await asyncio.to_thread(requests.get, img_url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            photo_file = io.BytesIO(response.content)
            photo_file.name = "image.jpg"
            await client.send_message(CHANNEL_USERNAME, text + FOOTER, file=photo_file)
        else:
            await client.send_message(CHANNEL_USERNAME, text + FOOTER)
    except: 
        try: await client.send_message(CHANNEL_USERNAME, text + FOOTER)
        except: pass

# === ДАЙДЖЕСТИ ===
async def send_morning_digest():
    logger.info("Morning Digest Triggered")
    data = await asyncio.to_thread(get_weather)
    
    if data:
        t_min = data['daily']['temperature_2m_min'][0]
        t_max = data['daily']['temperature_2m_max'][0]
        rain = data['daily']['precipitation_probability_max'][0]
        w_text = f"🌡 **Температура:** {t_min}°C ... {t_max}°C\n☔️ **Опади:** {'Можливі' if rain > 50 else 'Малоймовірні'} ({rain}%)"
    else:
        w_text = "🌡 **Погода:** Тимчасово недоступна."

    status = "🔴 Тривога активна!" if IS_ALARM_ACTIVE else "🟢 Небо чисте."
    
    # AI РАНОК
    quote = await asyncio.to_thread(get_ai_quote, "morning")
    
    msg = f"☀️ **ДОБРОГО РАНКУ, ДНІПРО!**\n\n{w_text}\n\n📢 **Статус:** {status}\n\n💬 _{quote}_"
    await send_safe(msg, URL_MORNING)

async def send_evening_digest():
    logger.info("Evening Digest Triggered")
    data = await asyncio.to_thread(get_weather)

    if data:
        t_min = data['daily']['temperature_2m_min'][1] # Завтра
        t_max = data['daily']['temperature_2m_max'][1]
        w_text = f"🌡 **Погода на завтра:** {t_min}°C ... {t_max}°C"
    else:
        w_text = "🌡 **Погода на завтра:** Дані оновлюються."

    # AI ВЕЧІР
    quote = await asyncio.to_thread(get_ai_quote, "evening")

    msg = f"🌒 **НА ДОБРАНІЧ, ДНІПРО!**\n\n{w_text}\n\n💬 _{quote}_\n\n🔋 Не забудьте перевірити заряд гаджетів."
    await send_safe(msg, URL_EVENING)

# === МОНІТОР АЛЕРТІВ ===
async def check_weather_alerts(test_mode=False):
    data = await asyncio.to_thread(get_weather)
    if not data: 
        if test_mode: await client.send_message(CHANNEL_USERNAME, "⚠️ Не вдалося отримати дані погоди.")
        return

    curr = data.get('current', {})
    temp = curr.get('temperature_2m', 0)
    wind = curr.get('wind_speed_10m', 0)
    
    alerts = []
    if temp < -10: alerts.append(f"🥶 **СИЛЬНИЙ МОРОЗ: {temp}°C!**")
    if temp > 30: alerts.append(f"🥵 **СИЛЬНА СПЕКА: {temp}°C!**")
    if wind > 15: alerts.append(f"💨 **ШТОРМОВИЙ ВІТЕР: {wind} м/с!**")
    
    if test_mode:
        test_msg = f"🧪 **ТЕСТ ПОГОДИ:**\n🌡 Температура: {temp}°C\n💨 Вітер: {wind} м/с"
        if alerts: test_msg += "\n\n⚠️ **АЛЕРТИ:**\n" + "\n".join(alerts)
        else: test_msg += "\n\n✅ Алертів немає."
        await client.send_message(CHANNEL_USERNAME, test_msg)
    elif alerts:
        await client.send_message(CHANNEL_USERNAME, "\n".join(alerts) + FOOTER)

# === ТАЙМЕРИ ===
async def morning_loop():
    while True:
        now = datetime.now()
        target = now.replace(hour5, minute=0, second=0, microsecond=0)
        if now >= target: target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        await send_morning_digest()
        await asyncio.sleep(60)

async def evening_loop():
    while True:
        now = datetime.now()
        target = now.replace(hour=20, minute=0, second=0, microsecond=0)
        if now >= target: target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        await send_evening_digest()
        await asyncio.sleep(60)

async def weather_loop():
    while True:
        await check_weather_alerts(test_mode=False)
        await asyncio.sleep(1800) 

# === ПАРСЕР ТА AI ДЛЯ ГРАФІКІВ ===
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

def ask_gemini_schedule(photo_path):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_KEY}"
    try:
        with open(photo_path, "rb") as f: img = base64.b64encode(f.read()).decode("utf-8")
        payload = {"contents": [{"parts": [{"text": "Extract schedule. JSON: [{\"group\": \"1.1\", \"start\": \"HH:MM\", \"end\": \"HH:MM\"}]"}, {"inline_data": {"mime_type": "image/jpeg", "data": img}}]}]}
        r = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=15)
        return json.loads(r.json()['candidates'][0]['content']['parts'][0]['text'].replace('```json', '').replace('```', '').strip())
    except: return []

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage())
async def handler(event):
    text = (event.message.message or "").lower()
    chat_id = event.chat_id
    global IS_ALARM_ACTIVE

    # === ТЕСТИ ===
    if event.out:
        if "test_morning" in text:
            await event.respond("🌅 Тестую ранок...")
            await send_morning_digest()
            return
        if "test_evening" in text:
            await event.respond("🌙 Тестую вечір...")
            await send_evening_digest()
            return
        if "test_weather" in text:
            await event.respond("💨 Тестую погоду...")
            await check_weather_alerts(test_mode=True)
            return

    # === СИРЕНА ===
    is_siren = False
    if REAL_SIREN_ID and chat_id == REAL_SIREN_ID: is_siren = True
    if (getattr(event.chat, 'username', '') or '').lower() == SIREN_CHANNEL_USER: is_siren = True
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
                schedule = await asyncio.to_thread(ask_gemini_schedule, path)
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
                
                if grp == MY_PERSONAL_GROUP:
                    msg_lines.append(f"👉 🏠 **Гр. {grp}:** {start.strftime('%H:%M')} - {end.strftime('%H:%M')} 👈")
                else:
                    msg_lines.append(f"🔹 **Гр. {grp}:** {start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
                
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
        logger.info("✅ Bot Started.")
    except: pass

if __name__ == '__main__':
    client.start()
    client.loop.create_task(morning_loop())
    client.loop.create_task(evening_loop())
    client.loop.create_task(weather_loop())
    client.loop.run_until_complete(startup())
    client.run_until_disconnected()

