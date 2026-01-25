import os
import json
import base64
import time
import re
import requests
import asyncio
import random
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

# === МЕДІА (НОВІ ПОСИЛАННЯ) ===
IMG_MORNING = "https://arcanavisio.com/wp-content/uploads/2026/01/01_MORNING.jpg"
IMG_EVENING = "https://arcanavisio.com/wp-content/uploads/2026/01/02_EVENING.jpg"
IMG_GRAFIC = "https://arcanavisio.com/wp-content/uploads/2026/01/03_GRAFIC.jpg"
IMG_NEW_GRAFIC = "https://arcanavisio.com/wp-content/uploads/2026/01/04_NEW-GRAFIC.jpg"
IMG_EXTRA_START = "https://arcanavisio.com/wp-content/uploads/2026/01/05_EXTRA_GRAFIC.jpg"
IMG_EXTRA_STOP = "https://arcanavisio.com/wp-content/uploads/2026/01/06_EXTRA_STOP.jpg"
IMG_TREVOGA = "https://arcanavisio.com/wp-content/uploads/2026/01/07_TREVOGA.jpg"
IMG_TREVOGA_STOP = "https://arcanavisio.com/wp-content/uploads/2026/01/08_TREVOGA_STOP.jpg"

# === ТЕКСТИ ===
TEXT_TREVOGA = "⚠️❗️ **УВАГА! ОГОЛОШЕНО ПОВІТРЯННУ ТРИВОГУ.**\n🏃 **ВСІМ ПРОЙТИ В УКРИТТЯ.**"
TEXT_TREVOGA_STOP = "✅ **ВІДБІЙ ПОВІТРЯННОЇ ТРИВОГИ.**"
TEXT_EXTRA_START = "⚡❗️ **УВАГА! ЗАСТОСОВАНІ ЕКСТРЕНІ ВІДКЛЮЧЕННЯ.**\n**ПІД ЧАС ЕКСТРЕНИХ ВІДКЛЮЧЕНЬ ГРАФІКИ НЕ ДІЮТЬ.**"
TEXT_EXTRA_STOP = "⚡️✔️ **ЕКСТРЕНІ ВІДКЛЮЧЕННЯ СВІТЛА СКАСОВАНІ.**"

FOOTER_TEXT = """
___

⭐️ Підписуйтесь та поділіться з родичами і друзями:
⚡СТРУМ ДНІПРА https://t.me/strum_dp

❤️ ПІДТРИМКА СЕРВІСУ:
🔗 https://send.monobank.ua/jar/9gBQ4LTLUa
___

@strum_dp"""

# Мотивація (для ранкових постів)
MOTIVATION_QUOTES = [
    "Сьогодні чудовий день, щоб зробити щось важливе!",
    "Навіть найтемніша ніч закінчується світанком.",
    "Тримаймо стрій! Перемога вже близько.",
    "Твоя енергія заряджає цей світ. Світи яскравіше!",
    "Маленькі кроки ведуть до великих змін.",
    "Вір у себе, як ми віримо в ППО!",
    "Не чекай на світло, будь світлом сам.",
    "Сьогоднішній день — це новий шанс.",
    "Кава, віра в ЗСУ та гарний настрій — рецепт твого дня.",
    "Усміхнись, тобі це личить!",
    "Все буде Україна. Головне — не зупинятися.",
    "Зберігай спокій та економ електроенергію.",
    "Ти здатен на більше, ніж думаєш.",
    "Нехай цей день принесе лише добрі новини.",
    "Світло всередині нас ніколи не згасне."
]

processing_lock = asyncio.Lock()
REAL_SIREN_ID = None
IS_ALARM_ACTIVE = False 

async def get_tasks_service():
    creds_dict = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('tasks', 'v1', credentials=creds)

# === 1. РАНКОВИЙ ДАЙДЖЕСТ (08:00) ===
async def morning_digest_loop():
    while True:
        now = datetime.now()
        target = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now >= target: target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        
        try:
            # Погода
            url = f"https://api.open-meteo.com/v1/forecast?latitude={DNIPRO_LAT}&longitude={DNIPRO_LON}&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Europe%2FKyiv"
            w = requests.get(url).json().get('daily', {})
            t_min, t_max = w['temperature_2m_min'][0], w['temperature_2m_max'][0]
            rain = w['precipitation_probability_max'][0]
            
            w_text = f"🌡 **Температура:** {t_min}°C ... {t_max}°C"
            w_text += f"\n☔️ **Опади:** {'Висока ймовірність' if rain > 50 else 'Малоймовірні'} ({rain}%)"
            
            siren_status = "🔴 Тривога активна!" if IS_ALARM_ACTIVE else "🟢 Небо чисте."
            quote = random.choice(MOTIVATION_QUOTES)
            
            msg = f"☀️ **ДОБРОГО РАНКУ, ДНІПРО!**\n\n{w_text}\n\n📢 **Статус:** {siren_status}\n\n💬 _{quote}_\n{FOOTER_TEXT}"
            await client.send_message(CHANNEL_USERNAME, msg, file=IMG_MORNING)
        except Exception as e: print(f"Morning Error: {e}")
        await asyncio.sleep(60)

# === 2. ВЕЧІРНІЙ ДАЙДЖЕСТ (22:00) ===
async def evening_digest_loop():
    while True:
        now = datetime.now()
        target = now.replace(hour=22, minute=0, second=0, microsecond=0)
        if now >= target: target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        
        try:
            # Погода на завтра
            url = f"https://api.open-meteo.com/v1/forecast?latitude={DNIPRO_LAT}&longitude={DNIPRO_LON}&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Europe%2FKyiv"
            w = requests.get(url).json().get('daily', {})
            t_min, t_max = w['temperature_2m_min'][1], w['temperature_2m_max'][1]
            rain = w['precipitation_probability_max'][1]
            
            w_text = f"🌡 **Завтра:** {t_min}°C ... {t_max}°C"
            w_text += f"\n☔️ **Опади:** {'Беріть парасольку' if rain > 50 else 'Без істотних опадів'}"
            
            msg = f"🌒 **НА ДОБРАНІЧ, ДНІПРО!**\n\n{w_text}\n\n🔋 Не забудьте перевірити заряд гаджетів.\nТихої ночі! ✨\n{FOOTER_TEXT}"
            await client.send_message(CHANNEL_USERNAME, msg, file=IMG_EVENING)
        except Exception as e: print(f"Evening Error: {e}")
        await asyncio.sleep(60)

# === 3. ПОГОДНИЙ МОНІТОР ===
async def weather_monitor_loop():
    last_temp = None
    warned_types = []
    while True:
        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={DNIPRO_LAT}&longitude={DNIPRO_LON}&current=temperature_2m,wind_speed_10m&timezone=Europe%2FKyiv"
            data = requests.get(url).json().get('current', {})
            temp = data.get('temperature_2m', 0)
            wind = data.get('wind_speed_10m', 0)
            
            alerts = []
            # Мороз / Спека
            if temp < -10 and 'temp' not in warned_types:
                alerts.append(f"🥶 **УВАГА: СИЛЬНИЙ МОРОЗ ({temp}°C)!**")
                warned_types.append('temp')
            elif temp > 30 and 'temp' not in warned_types:
                alerts.append(f"🥵 **УВАГА: СИЛЬНА СПЕКА ({temp}°C)!**")
                warned_types.append('temp')
            elif -10 <= temp <= 30 and 'temp' in warned_types:
                warned_types.remove('temp')
                
            # Вітер
            if wind > 15 and 'wind' not in warned_types:
                alerts.append(f"💨 **УВАГА: ШТОРМОВИЙ ВІТЕР ({wind} м/с)!**")
                warned_types.append('wind')
            elif wind <= 15 and 'wind' in warned_types:
                warned_types.remove('wind')

            if alerts:
                await client.send_message(CHANNEL_USERNAME, "\n".join(alerts) + FOOTER_TEXT)
                
        except: pass
        await asyncio.sleep(1800)

# === ПАРСЕРИ ===
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
    with open(photo_path, "rb") as f: img = base64.b64encode(f.read()).decode("utf-8")
    payload = {"contents": [{"parts": [{"text": "Extract DTEK schedule. JSON list: [{\"group\": \"1.1\", \"start\": \"HH:MM\", \"end\": \"HH:MM\"}]"}, {"inline_data": {"mime_type": "image/jpeg", "data": img}}]}]}
    try:
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
            await client.send_message(CHANNEL_USERNAME, TEXT_TREVOGA_STOP + FOOTER_TEXT, file=IMG_TREVOGA_STOP)
        elif "тривог" in text or "тревога" in text or "укриття" in text:
            IS_ALARM_ACTIVE = True
            await client.send_message(CHANNEL_USERNAME, TEXT_TREVOGA + FOOTER_TEXT, file=IMG_TREVOGA)
        return

    # === ЕКСТРЕНІ ===
    # 1. СКАСУВАННЯ ЕКСТРЕНИХ
    if any(w in text for w in ['екстрені', 'экстренные']) and any(w in text for w in ['скасовані', 'отмена', 'відмінено']):
        if any(w in text for w in ['дніпро', 'днепр', 'дтек', 'дтэк']):
            await client.send_message(CHANNEL_USERNAME, TEXT_EXTRA_STOP + FOOTER_TEXT, file=IMG_EXTRA_STOP)
            return

    # 2. ПОЧАТОК ЕКСТРЕНИХ (якщо немає слова "скасовано")
    if any(w in text for w in ['екстрені', 'экстренные']):
        if any(w in text for w in ['дніпро', 'днепр', 'дтек', 'дтэк']):
            await client.send_message(CHANNEL_USERNAME, TEXT_EXTRA_START + FOOTER_TEXT, file=IMG_EXTRA_START)
            return

    # === ГРАФІКИ (ТЕКСТ та ФОТО) ===
    schedule = []
    
    # Спроба парсингу тексту
    if re.search(r'\d\.\d', text) and re.search(r'\d{1,2}:\d{2}', text):
        schedule = parse_schedule(event.message.message)
    
    # Спроба AI (якщо є фото)
    elif event.message.photo:
        async with processing_lock:
            try:
                # Тихий пінг адміну, що AI думає
                if event.is_private: await event.respond("🤖 Analysing...") 
                path = await event.message.download_media()
                schedule = await asyncio.to_thread(ask_gemini, path)
                os.remove(path)
            except: pass

    # ЯКЩО ГРАФІК ЗНАЙДЕНО
    if schedule and isinstance(schedule, list):
        service = await get_tasks_service()
        schedule.sort(key=lambda x: x.get('group', ''))
        
        # Визначаємо тип графіку (Оновлення чи Звичайний)
        is_update = any(w in text for w in ['зміни', 'оновлення', 'изменения', 'обновление', 'новые', 'корегування'])
        
        # Заголовок + ДАТА
        date_str = datetime.now().strftime('%d.%m.%Y')
        if is_update:
            header = f"⚡️✔️ **ОНОВЛЕННЯ ГРАФІКІВ ВІДКЛЮЧЕНЬ СВІТЛА.**\n📅 **На {date_str}**"
            img = IMG_NEW_GRAFIC
        else:
            header = f"⚡️📌 **ГРАФІКИ ВІДКЛЮЧЕНЬ СВІТЛА.**\n📅 **На {date_str}**"
            img = IMG_GRAFIC

        # Формуємо тіло
        msg_lines = [header, ""]
        prev_grp = None
        
        for entry in schedule:
            try:
                start = parser.parse(entry['start'])
                end = parser.parse(entry['end'])
                grp = entry.get('group', '?')
                
                # Розділювач
                main_grp = grp.split('.')[0] if '.' in grp else grp
                if prev_grp and main_grp != prev_grp: msg_lines.append("➖➖➖➖➖➖➖➖")
                prev_grp = main_grp
                
                msg_lines.append(f"🔹 **Гр. {grp}:** {start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
                
                # Google Tasks (1.1)
                if grp == MY_PERSONAL_GROUP:
                    notif = start - timedelta(hours=2, minutes=10)
                    task = {'title': f"💡 СВІТЛО (Гр. {grp})", 'notes': f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}", 'due': notif.isoformat() + 'Z'}
                    try: service.tasks().insert(tasklist='@default', body=task).execute()
                    except: pass
            except: continue
            
        full_msg = "\n".join(msg_lines) + FOOTER_TEXT
        await client.send_message(CHANNEL_USERNAME, full_msg, file=img)

async def startup():
    global REAL_SIREN_ID
    try:
        await client(JoinChannelRequest(SIREN_CHANNEL_USER))
        e = await client.get_entity(SIREN_CHANNEL_USER)
        REAL_SIREN_ID = int(f"-100{e.id}")
        print("✅ Bot Started. Siren ID found.")
    except: print("⚠️ Siren ID not found (manual mode only).")

if __name__ == '__main__':
    client.start()
    client.loop.create_task(morning_digest_loop())
    client.loop.create_task(evening_digest_loop())
    client.loop.create_task(weather_monitor_loop())
    client.loop.run_until_complete(startup())
    client.run_until_disconnected()
