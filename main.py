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
from zoneinfo import ZoneInfo
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dateutil import parser

# === ЛОГУВАННЯ ===
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# === НАЛАШТУВАННЯ ===
MY_PERSONAL_GROUP = "1.1"
CHANNEL_USERNAME = "@strum_dp"
SIREN_CHANNEL_USER = "sirena_dp"
MONITOR_CHANNEL_USER = "hyevuy_dnepr"
DNIPRO_LAT = 48.46
DNIPRO_LON = 35.04

# === ВАЛІДНІ ГРУПИ ===
VALID_GROUPS = ["1.1", "1.2", "2.1", "2.2", "3.1", "3.2", "4.1", "4.2", "5.1", "5.2", "6.1", "6.2"]

# === ТРИГЕРИ ЗАГРОЗ ===
THREAT_TRIGGERS = [
    "бпла", "шахед", "дрон", 
    "балістика", "балистика",
    "вибух", "взрыв",
    "гучно", "громко",
    "ракета", "атака",
    "тривога", "тревога",
    "загроза", "угроза",
    "над містом", "над городом",
    "курс на дніпро", "курсом на дніпро",
    "без загроз", "чисто", "розвідник"
]

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

# === ТЕКСТИ (HTML) ===
TXT_TREVOGA = "<b>⚠️❗️ УВАГА! ОГОЛОШЕНО ПОВІТРЯНУ ТРИВОГУ.</b>\n\n🏃 <b>ВСІМ ПРОЙТИ В УКРИТТЯ.</b>"
TXT_TREVOGA_STOP = "<b>✅ ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ.</b>"
TXT_EXTRA_START = "<b>⚡❗️УВАГА! ЗАСТОСОВАНІ ЕКСТРЕНІ ВІДКЛЮЧЕННЯ.</b>\n\n<b>ПІД ЧАС ЕКСТРЕНИХ ВІДКЛЮЧЕНЬ ГРАФІКИ НЕ ДІЮТЬ.</b>"
TXT_EXTRA_STOP = "<b>⚡️✔️ ЕКСТРЕНІ ВІДКЛЮЧЕННЯ СВІТЛА СКАСОВАНІ.</b>"

# === ФУТЕР (НОВИЙ) ===
FOOTER = """
____

⭐️ <a href="https://t.me/strum_dp"><b>ПІДПИСУЙТЕСЬ</b></a>
❤️ <a href="https://send.monobank.ua/jar/9gBQ4LTLUa"><b>ПІДТРИМАЙТЕ СЕРВІС</b></a>
____

@strum_dp"""

# === ЦИТАТИ ===
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
    "Сон — це найкраща медитація.",
    "Навіть найтемніша ніч закінчується світанком. Відпочивай.",
    "Завтра буде новий день і нові сили. Сьогодні — тиша.",
    "Мир всередині починається тоді, коли ти перестаєш контролювати все ззовні.",
    "Вдихни спокій, видихни напругу. Ти в безпеці своїх думок."
]

processing_lock = asyncio.Lock()
REAL_SIREN_ID = None
IS_ALARM_ACTIVE = False 
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

async def get_tasks_service():
    creds_dict = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('tasks', 'v1', credentials=creds)

# === ЛОГІКА ЗАГРОЗ (CAPS + EMOJI + УВАГА) ===
def format_threat_text(text):
    t = text.lower()
    emoji = "⚡️"
    is_danger = True

    if any(w in t for w in ["балістика", "балистика", "ракета"]):
        emoji = "🚀"
    elif any(w in t for w in ["бпла", "шахед", "дрон", "мопед"]):
        emoji = "🛩️"
    elif any(w in t for w in ["вибух", "взрыв", "гучно"]):
        emoji = "💥"
    elif "розвідник" in t:
        emoji = "👁️"
    elif any(w in t for w in ["відбій", "чисто", "без загроз"]):
        emoji = "🟢"
        is_danger = False
    elif "загроза" in t:
        emoji = "⚠️"
        
    text_caps = text.upper()
    
    if is_danger:
        return f"{emoji} <b>УВАГА! {text_caps}</b>"
    else:
        return f"{emoji} <b>{text_caps}</b>"

# === AI ===
def get_ai_quote(mode="morning"):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_KEY}"
    prompt = "Напиши одну коротку, глибоку думку (стоїцизм/психологія) для українців. Українська мова. До 15 слів. Без лапок."
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        r = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=5)
        if r.status_code == 200:
            return r.json()['candidates'][0]['content']['parts'][0]['text'].strip().replace('"', '').replace('*', '')
    except: pass
    return random.choice(BACKUP_MORNING if mode == "morning" else BACKUP_EVENING)

# === ПОГОДА ===
def get_weather():
    url = f"https://api.open-meteo.com/v1/forecast?latitude={DNIPRO_LAT}&longitude={DNIPRO_LON}&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&current=temperature_2m,wind_speed_10m&timezone=Europe%2FKyiv"
    for _ in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200: return r.json()
        except: time.sleep(2)
    return None

# === ВІДПРАВКА ===
async def send_safe(text, img_url):
    try:
        response = await asyncio.to_thread(requests.get, img_url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            photo_file = io.BytesIO(response.content)
            photo_file.name = "image.jpg"
            return await client.send_message(CHANNEL_USERNAME, text + FOOTER, file=photo_file, parse_mode='html')
    except Exception as e:
        logger.warning(f"Image download failed: {e}")
    
    try:
        return await client.send_message(CHANNEL_USERNAME, text + FOOTER, parse_mode='html')
    except Exception as e:
        logger.error(f"Text send failed: {e}")
        return None

# === ДАЙДЖЕСТИ ===
async def send_morning_digest():
    logger.info("Digest: Morning")
    data = await asyncio.to_thread(get_weather)
    w_text = "🌡 <b>Погода:</b> Тимчасово недоступна."
    if data:
        d = data['daily']
        w_text = f"🌡 <b>Температура:</b> {d['temperature_2m_min'][0]}°C ... {d['temperature_2m_max'][0]}°C\n☔️ <b>Опади:</b> {d['precipitation_probability_max'][0]}%"
    
    status = "🔴 Тривога активна!" if IS_ALARM_ACTIVE else "🟢 Небо чисте."
    quote = await asyncio.to_thread(get_ai_quote, "morning")
    msg = f"<b>☀️ ДОБРОГО РАНКУ, ДНІПРО!</b>\n\n{w_text}\n\n📢 <b>Статус повітряної тривоги:</b> {status}\n\n<blockquote>{quote}</blockquote>"
    await send_safe(msg, URL_MORNING)

async def send_evening_digest():
    logger.info("Digest: Evening")
    data = await asyncio.to_thread(get_weather)
    w_text = "🌡 <b>Погода на завтра:</b> Дані оновлюються."
    if data:
        d = data['daily']
        w_text = f"🌡 <b>Погода на завтра:</b> {d['temperature_2m_min'][1]}°C ... {d['temperature_2m_max'][1]}°C"

    quote = await asyncio.to_thread(get_ai_quote, "evening")
    msg = f"<b>🌒 НА ДОБРАНІЧ, ДНІПРО!</b>\n\n{w_text}\n\n<blockquote>{quote}</blockquote>\n\n🔋 Не забудьте перевірити заряд гаджетів."
    await send_safe(msg, URL_EVENING)

# === МОНІТОР АЛЕРТІВ ===
async def check_weather_alerts(test_mode=False):
    data = await asyncio.to_thread(get_weather)
    if not data: 
        if test_mode: await client.send_message(CHANNEL_USERNAME, "⚠️ Помилка погоди.", parse_mode='html')
        return
    curr = data.get('current', {})
    alerts = []
    if curr.get('temperature_2m', 0) < -10: alerts.append(f"🥶 <b>СИЛЬНИЙ МОРОЗ: {curr['temperature_2m']}°C!</b>")
    if curr.get('wind_speed_10m', 0) > 15: alerts.append(f"💨 <b>ШТОРМОВИЙ ВІТЕР: {curr['wind_speed_10m']} м/с!</b>")
    
    if test_mode:
        await client.send_message(CHANNEL_USERNAME, f"🧪 <b>ТЕСТ ПОГОДИ:</b> {curr.get('temperature_2m')}°C", parse_mode='html')
    elif alerts:
        await client.send_message(CHANNEL_USERNAME, "\n".join(alerts) + FOOTER, parse_mode='html')

# === ТАЙМЕРИ ===
async def schedule_loop():
    logger.info("Scheduler Started")
    while True:
        now = datetime.now(ZoneInfo("Europe/Kyiv"))
        t_m = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now >= t_m: t_m += timedelta(days=1)
        t_e = now.replace(hour=22, minute=0, second=0, microsecond=0)
        if now >= t_e: t_e += timedelta(days=1)
        
        next_evt = min(t_m, t_e)
        secs = (next_evt - now).total_seconds()
        
        if secs < 3600 or now.minute == 0:
            logger.info(f"Next post in {int(secs)}s")
        
        await asyncio.sleep(secs)
        
        if next_evt == t_m: await send_morning_digest()
        else: await send_evening_digest()
        
        await asyncio.sleep(60)

# === ПАРСЕР ===
def parse_schedule(text):
    schedule = []
    today = datetime.now().strftime('%Y-%m-%d')
    lines = text.split('\n')
    current_groups = []
    
    group_pattern = r'\b([1-6]\.[1-2])\b'
    time_pattern = r'(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})'
    
    for line in lines:
        line = line.strip().lower()
        if not line: continue
        
        groups_in_line = re.findall(group_pattern, line)
        times_in_line = re.findall(time_pattern, line)
        
        if groups_in_line:
            current_groups = groups_in_line
            if times_in_line:
                for grp in groups_in_line:
                    for t in times_in_line:
                        end_t = t[1].replace("24:00", "23:59")
                        schedule.append({"group": grp, "start": f"{today}T{t[0]}:00", "end": f"{today}T{end_t}:00"})
        elif times_in_line and current_groups:
            for grp in current_groups:
                for t in times_in_line:
                    end_t = t[1].replace("24:00", "23:59")
                    schedule.append({"group": grp, "start": f"{today}T{t[0]}:00", "end": f"{today}T{end_t}:00"})
    return schedule

def ask_gemini_schedule(photo_path):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_KEY}"
    try:
        with open(photo_path, "rb") as f: img = base64.b64encode(f.read()).decode("utf-8")
        prompt = "Extract schedule. JSON: [{\"group\": \"1.1\", \"start\": \"HH:MM\", \"end\": \"HH:MM\"}]"
        payload = {"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": img}}]}]}
        r = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=15)
        return json.loads(r.json()['candidates'][0]['content']['parts'][0]['text'].replace('```json', '').replace('```', '').strip())
    except: return []

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# === 1. МОНІТОРИНГ ЗАГРОЗ ===
@client.on(events.NewMessage(chats=MONITOR_CHANNEL_USER))
async def threat_handler(event):
    text = (event.message.message or "")
    text_lower = text.lower()
    
    if any(trigger in text_lower for trigger in THREAT_TRIGGERS):
        try:
            formatted_text = format_threat_text(text)
            await client.send_message(CHANNEL_USERNAME, formatted_text + FOOTER, parse_mode='html')
            logger.info(f"Threat alert reposted: {text[:30]}...")
        except Exception as e:
            logger.error(f"Threat repost failed: {e}")

# === 2. ОСНОВНИЙ ОБРОБНИК ===
@client.on(events.NewMessage())
async def main_handler(event):
    try:
        chat = await event.get_chat()
        username = chat.username.lower() if chat and hasattr(chat, 'username') and chat.username else ""
        if username == MONITOR_CHANNEL_USER.lower(): return
    except: username = ""
    
    text = (event.message.message or "").lower()
    
    # === ТЕСТИ ===
    if event.out:
        if "test_morning" in text:
            await event.respond("🌅 Тест ранку...")
            await send_morning_digest()
            return
        if "test_evening" in text:
            await event.respond("🌙 Тест вечора...")
            await send_evening_digest()
            return
        if "test_weather" in text:
            await event.respond("💨 Тест погоди...")
            await check_weather_alerts(test_mode=True)
            return
        if "test_siren" in text:
            global IS_ALARM_ACTIVE
            if "відбій" in text or "отбой" in text or "stop" in text:
                IS_ALARM_ACTIVE = False
                await send_safe(TXT_TREVOGA_STOP, URL_TREVOGA_STOP)
                await event.respond("✅ Тест: Відбій")
            else: # start / тривога
                IS_ALARM_ACTIVE = True
                await send_safe(TXT_TREVOGA, URL_TREVOGA)
                await event.respond("⚠️ Тест: Тривога")
            return
        if "test_threat" in text:
            content = event.message.message.replace("test_threat", "").strip()
            if not content: content = "Тестова загроза: БпЛА в напрямку Дніпра"
            formatted = format_threat_text(content)
            await client.send_message(CHANNEL_USERNAME, formatted + FOOTER, parse_mode='html')
            await event.respond(f"🧨 Тест загрози відправлено: {content}")
            return

    # === СИРЕНА ===
    is_siren = False
    if REAL_SIREN_ID and event.chat_id == REAL_SIREN_ID: is_siren = True
    if username == SIREN_CHANNEL_USER: is_siren = True
    
    if is_siren:
        if "відбій" in text or "отбой" in text:
            IS_ALARM_ACTIVE = False
            await send_safe(TXT_TREVOGA_STOP, URL_TREVOGA_STOP)
        elif "тривог" in text or "тревога" in text:
            IS_ALARM_ACTIVE = True
            await send_safe(TXT_TREVOGA, URL_TREVOGA)
        return

    # === ЕКСТРЕНІ ===
    if "екстрені" in text or "экстренные" in text:
        if "скасовані" in text or "отмена" in text:
            await send_safe(TXT_EXTRA_STOP, URL_EXTRA_STOP)
        else:
            await send_safe(TXT_EXTRA_START, URL_EXTRA_START)
        return

    # === ГРАФІКИ ===
    schedule = []
    if re.search(r'[1-6]\.[1-2]', text) and re.search(r'\d{1,2}:\d{2}', text):
        if event.out or event.is_private:
             schedule = parse_schedule(event.message.message)
    elif event.message.photo:
        if event.out or event.is_private:
            async with processing_lock:
                try:
                    path = await event.message.download_media()
                    schedule = await asyncio.to_thread(ask_gemini_schedule, path)
                    os.remove(path)
                except: pass

    # === ПУБЛІКАЦІЯ ===
    if schedule and isinstance(schedule, list):
        service = await get_tasks_service()
        schedule.sort(key=lambda x: x.get('group', ''))
        
        is_update = any(w in text for w in ['зміни', 'оновлення', 'корегування', 'изменения'])
        date_now = datetime.now().strftime('%d.%m.%Y')
        
        header = f"<b>⚡️✔️ ОНОВЛЕННЯ ГРАФІКІВ.</b>\n📅 <b>На {date_now}</b>" if is_update else f"<b>⚡️📌 ГРАФІКИ ВІДКЛЮЧЕНЬ.</b>\n📅 <b>На {date_now}</b>"
        img_url = URL_NEW_GRAFIC if is_update else URL_GRAFIC

        msg_lines = [header, ""]
        prev_grp = None
        has_valid = False
        
        for entry in schedule:
            try:
                grp = entry.get('group', '?').strip()
                if grp not in VALID_GROUPS: continue 
                
                has_valid = True
                if entry['end'].endswith("T24:00:00"):
                     entry['end'] = entry['end'].replace("T24:00:00", "T23:59:00")

                start = parser.parse(entry['start'])
                end = parser.parse(entry['end'])
                
                if prev_grp and grp != prev_grp: 
                    msg_lines.append("➖➖➖➖➖➖➖➖")
                prev_grp = grp
                
                msg_lines.append(f"🔹 <b>Гр. {grp}:</b> {start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
                
                if grp == MY_PERSONAL_GROUP:
                    try:
                        notif = start - timedelta(hours=2, minutes=10)
                        task = {'title': f"💡 СВІТЛО (Гр. {grp})", 'notes': f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}", 'due': notif.isoformat() + 'Z'}
                        service.tasks().insert(tasklist='@default', body=task).execute()
                    except: pass

            except: continue
        
        if has_valid:
            msg = await send_safe("\n".join(msg_lines), img_url)
            if msg:
                try:
                    await client.pin_message(CHANNEL_USERNAME, msg, notify=True)
                except: pass

async def startup():
    global REAL_SIREN_ID
    try:
        await client(JoinChannelRequest(SIREN_CHANNEL_USER))
        e = await client.get_entity(SIREN_CHANNEL_USER)
        REAL_SIREN_ID = int(f"-100{e.id}")
        
        await client(JoinChannelRequest(MONITOR_CHANNEL_USER))
        
        logger.info("✅ Bot Started.")
    except Exception as e:
        logger.error(f"Startup Error: {e}")

if __name__ == '__main__':
    client.start()
    client.loop.create_task(schedule_loop())
    client.loop.create_task(check_weather_alerts())
    client.loop.run_until_complete(startup())
    client.run_until_disconnected()
