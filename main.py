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

# === ТЕКСТ ПІДТРИМКИ (ОНОВЛЕНИЙ) ===
FOOTER_TEXT = """

___

Підписуйтесь та поділіться з родичами і друзями:
https://t.me/strum_dp

ПІДТРИМКА СЕРВІСУ СТРУМ
🔗 Посилання на банку:
https://send.monobank.ua/jar/9gBQ4LTLUa"""

# Координати Дніпра
DNIPRO_LAT = 48.46
DNIPRO_LON = 35.04

# === ЗМІННІ ===
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']

# === МЕДІА ===
IMG_SCHEDULE = "https://arcanavisio.com/wp-content/uploads/2026/01/MAIN.jpg"
IMG_UPDATE = "https://arcanavisio.com/wp-content/uploads/2026/01/UPDATE.jpg"
IMG_EMERGENCY = "https://arcanavisio.com/wp-content/uploads/2026/01/EXTRA.jpg"
IMG_ALARM = "https://arcanavisio.com/wp-content/uploads/2026/01/ALARM.jpg"
IMG_ALL_CLEAR = "https://arcanavisio.com/wp-content/uploads/2026/01/REBOUND.jpg"
IMG_MORNING = "https://arcanavisio.com/wp-content/uploads/2026/01/MORN.jpg"
IMG_EVENING = "https://arcanavisio.com/wp-content/uploads/2026/01/EVN.jpg"

processing_lock = asyncio.Lock()
REAL_SIREN_ID = None
IS_ALARM_ACTIVE = False # Пам'ять про стан тривоги

# Мотиваційні фрази
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

# Стан погоди
weather_state = {
    'last_temp': None,
    'last_pressure': None,
    'precip_warned': False,
    'wind_warned': False,
    'temp_warned': False
}

async def get_tasks_service():
    creds_dict = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('tasks', 'v1', credentials=creds)

# === РАНКОВИЙ ДАЙДЖЕСТ (08:00) ===
async def morning_digest_loop():
    print("🌅 Morning Digest: Started")
    while True:
        now = datetime.now()
        target_time = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now >= target_time: target_time += timedelta(days=1)
        wait_seconds = (target_time - now).total_seconds()
        
        await asyncio.sleep(wait_seconds)
        
        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={DNIPRO_LAT}&longitude={DNIPRO_LON}&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Europe%2FKyiv"
            w_res = requests.get(url).json()
            daily = w_res.get('daily', {})
            t_max = daily['temperature_2m_max'][0]
            t_min = daily['temperature_2m_min'][0]
            rain_prob = daily['precipitation_probability_max'][0]
            
            weather_text = f"🌡 **Сьогодні:** {t_min}°C ... {t_max}°C\n"
            if rain_prob > 50: weather_text += f"☔️ **Опади:** Можливий дощ/сніг ({rain_prob}%)."
            else: weather_text += "☀️ **Опади:** Малоймовірні."

            alarm_text = "🔴 **Тривога:** Зараз небезпечно!" if IS_ALARM_ACTIVE else "🟢 **Тривога:** Тихо."
            quote = random.choice(MOTIVATION_QUOTES)

            msg = f"""👋 **Добрий ранок, Дніпро!**

{weather_text}

{alarm_text}

📅 **Графік:** Перевірте канал на наявність змін.

💬 **Думка дня:**
_{quote}_
{FOOTER_TEXT}"""

            await client.send_message(CHANNEL_USERNAME, msg, file=IMG_MORNING)
            print("✅ Morning digest sent.")
        except Exception as e:
            print(f"❌ Morning Error: {e}")
        
        await asyncio.sleep(60)

# === ВЕЧІРНІЙ ДАЙДЖЕСТ (22:00) ===
async def evening_digest_loop():
    print("🌙 Evening Digest: Started")
    while True:
        now = datetime.now()
        target_time = now.replace(hour=22, minute=0, second=0, microsecond=0)
        if now >= target_time: target_time += timedelta(days=1)
        wait_seconds = (target_time - now).total_seconds()
        
        await asyncio.sleep(wait_seconds)
        
        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={DNIPRO_LAT}&longitude={DNIPRO_LON}&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Europe%2FKyiv"
            w_res = requests.get(url).json()
            daily = w_res.get('daily', {})
            
            t_max = daily['temperature_2m_max'][1]
            t_min = daily['temperature_2m_min'][1]
            rain_prob = daily['precipitation_probability_max'][1]
            
            weather_text = f"🌡 **Завтра:** {t_min}°C ... {t_max}°C\n"
            if rain_prob > 50: weather_text += f"☔️ **Опади:** Очікується дощ/сніг."
            else: weather_text += "✨ **Опади:** Без істотних опадів."

            alarm_text = "🔴 **Тривога:** Зараз лунає сирена." if IS_ALARM_ACTIVE else "🟢 **Тривога:** Наразі спокійно."

            msg = f"""🌙 **На добраніч, Дніпро!**

{weather_text}

{alarm_text}

🔋 **Нагадування:** Не забудьте поставити гаджети та павербанки на зарядку, якщо це потрібно.

Тихої ночі всім нам. ✨
{FOOTER_TEXT}"""

            await client.send_message(CHANNEL_USERNAME, msg, file=IMG_EVENING)
            print("✅ Evening digest sent.")
        except Exception as e:
            print(f"❌ Evening Error: {e}")
        
        await asyncio.sleep(60)

# === ПОГОДНІ АЛЕРТИ ===
async def check_weather_alerts():
    print("🌤 Weather Monitor: Started")
    while True:
        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={DNIPRO_LAT}&longitude={DNIPRO_LON}&current=temperature_2m,precipitation,rain,showers,snowfall,surface_pressure,wind_speed_10m&timezone=Europe%2FKyiv"
            response = await asyncio.to_thread(requests.get, url)
            data = response.json().get('current', {})

            if not data:
                await asyncio.sleep(1800)
                continue

            temp = data.get('temperature_2m', 0)
            pressure = data.get('surface_pressure', 0)
            wind = data.get('wind_speed_10m', 0)
            rain = data.get('rain', 0) + data.get('showers', 0)
            snow = data.get('snowfall', 0)
            
            alerts = []

            if temp < -10:
                if not weather_state['temp_warned']:
                    alerts.append(f"🥶 **СИЛЬНИЙ МОРОЗ:** {temp}°C! Одягайтесь тепліше.")
                    weather_state['temp_warned'] = True
            elif temp > 30:
                if not weather_state['temp_warned']:
                    alerts.append(f"🥵 **ПЕКЕЛЬНА СПЕКА:** {temp}°C! Беріть воду та панамку.")
                    weather_state['temp_warned'] = True
            else:
                if -9 < temp < 29: weather_state['temp_warned'] = False

            if wind > 15:
                if not weather_state['wind_warned']:
                    alerts.append(f"💨 **ШТОРМОВИЙ ВІТЕР:** {wind} м/с. Обережно під деревами.")
                    weather_state['wind_warned'] = True
            else:
                if wind < 10: weather_state['wind_warned'] = False

            if snow > 0:
                if not weather_state['precip_warned']:
                    alerts.append(f"❄️ **УВАГА: СНІГОПАД!** Можлива ожеледиця.")
                    weather_state['precip_warned'] = 'snow'
            elif rain > 0:
                if not weather_state['precip_warned']:
                    alerts.append(f"☔️ **ПОЧАВСЯ ДОЩ.** Не забудьте парасольку.")
                    weather_state['precip_warned'] = 'rain'
            else:
                weather_state['precip_warned'] = False

            if weather_state['last_pressure']:
                diff = abs(pressure - weather_state['last_pressure'])
                if diff > 5:
                     alerts.append(f"🩸 **СТРИБОК ТИСКУ:** Зміна на {diff:.1f} гПа.")
            
            weather_state['last_pressure'] = pressure
            weather_state['last_temp'] = temp

            if alerts:
                msg = "\n\n".join(alerts) + FOOTER_TEXT
                try: await client.send_message(CHANNEL_USERNAME, msg, file=IMG_EMERGENCY)
                except: pass

        except Exception as e:
            print(f"Weather Check Error: {e}")

        await asyncio.sleep(1800) 

def parse_text_all_groups(text):
    schedule = []
    lines = text.split('\n')
    for line in lines:
        line_lower = line.lower().strip()
        groups = re.findall(r'\b(\d\.\d)\b', line_lower)
        if groups:
            times = re.findall(r'(\d{1,2}:\d{2}).*?(\d{1,2}:\d{2})', line_lower)
            if times:
                today = datetime.now().strftime('%Y-%m-%d')
                for gr in groups:
                    if gr in [t[0] for t in times] or gr in [t[1] for t in times]: continue
                    for t in times:
                        schedule.append({
                            "group": gr,
                            "start": f"{today}T{t[0]}:00",
                            "end": f"{today}T{t[1]}:00"
                        })
    return schedule

def ask_gemini_all_groups(photo_path, text):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent"
    try:
        with open(photo_path, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode("utf-8")
    except: return "FILE_ERROR"
    prompt = f"""
    Analyze schedule. Find ALL groups. Return JSON list: [{{ "group": "1.1", "start": "HH:MM", "end": "HH:MM" }}]
    Date today: {datetime.now().strftime('%Y-%m-%d')}.
    """
    payload = {"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": image_data}}]}]}
    full_url = f"{url}?key={GEMINI_KEY}"
    for attempt in range(1, 6):
        try:
            response = requests.post(full_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=60)
            if response.status_code == 200:
                try: return json.loads(response.json()['candidates'][0]['content']['parts'][0]['text'].replace('```json', '').replace('```', '').strip())
                except: return [] 
            elif response.status_code == 429: time.sleep(30); continue
            else: time.sleep(10); continue
        except: time.sleep(10)
    return "TIMEOUT"

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage())
async def handler(event):
    text = (event.message.message or "").lower()
    chat_id = event.chat_id
    global IS_ALARM_ACTIVE
    
    # === 1. СИРЕНА ===
    is_siren = False
    if REAL_SIREN_ID and chat_id == REAL_SIREN_ID: is_siren = True
    if event.chat and hasattr(event.chat, 'username') and event.chat.username:
        if event.chat.username.lower() == SIREN_CHANNEL_USER: is_siren = True
    if "test_siren" in text and event.out: is_siren = True
    if event.fwd_from and ("сирена" in text or "тривог" in text): is_siren = True

    if is_siren:
        if "відбій" in text or "отбой" in text:
            IS_ALARM_ACTIVE = False
            msg = "🟢 **ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ!**" + FOOTER_TEXT
            await client.send_message(CHANNEL_USERNAME, msg, file=IMG_ALL_CLEAR)
        elif "тривог" in text or "тревога" in text or "укриття" in text:
            IS_ALARM_ACTIVE = True
            msg = "🔴 **УВАГА! ПОВІТРЯНА ТРИВОГА!**" + FOOTER_TEXT
            await client.send_message(CHANNEL_USERNAME, msg, file=IMG_ALARM)
        return

    # === 2. ЕКСТРЕНІ (НОВИЙ ТЕКСТ) ===
    if any(w in text for w in ['екстрені', 'экстренные', 'скасовані', 'отмена']):
        if any(k in text for k in ['дніпро', 'днепр', 'дтек', 'дтэк']):
            msg = "🚨 **ЕКСТРЕНІ ВІДКЛЮЧЕННЯ! ГРАФІКИ НЕ ДІЮТЬ!**" + FOOTER_TEXT
            await client.send_message(CHANNEL_USERNAME, msg, file=IMG_EMERGENCY)
            return

    # === 3. ГРАФІКИ (ТЕКСТ) ===
    if re.search(r'\d\.\d', text) and re.search(r'\d{1,2}:\d{2}', text):
        schedule = parse_text_all_groups(event.message.message)
        if schedule:
            service = await get_tasks_service()
            schedule.sort(key=lambda x: x['group'])
            
            is_update = any(w in text for w in ['зміни', 'оновлення', 'изменения', 'обновление'])
            header = "🔄 **ОНОВЛЕННЯ ГРАФІКУ:**" if is_update else "⚡️ **ГРАФІК ВІДКЛЮЧЕНЬ:**"
            img_to_use = IMG_UPDATE if is_update else IMG_SCHEDULE
            
            msg_lines = [header, ""]
            previous_main_group = None

            for entry in schedule:
                try:
                    start_dt = parser.parse(entry['start'])
                    end_dt = parser.parse(entry['end'])
                except: continue
                
                grp = entry['group']
                current_main_group = grp.split('.')[0] if '.' in grp else grp
                if previous_main_group and current_main_group != previous_main_group:
                    msg_lines.append("➖➖➖➖➖➖➖➖")

                msg_lines.append(f"🔹 **Гр. {grp}:** {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}")
                previous_main_group = current_main_group

                if grp == MY_PERSONAL_GROUP:
                    notif_time = start_dt - timedelta(hours=2, minutes=10)
                    task = {
                        'title': f"{'🔄' if is_update else '💡'} СВІТЛО (Гр. {grp})",
                        'notes': f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}",
                        'due': notif_time.isoformat() + 'Z'
                    }
                    try: service.tasks().insert(tasklist='@default', body=task).execute()
                    except: pass
            
            full_message = "\n".join(msg_lines) + FOOTER_TEXT
            await client.send_message(CHANNEL_USERNAME, full_message, file=img_to_use)
            return

    # === 4. ГРАФІКИ (ФОТО) ===
    if event.message.photo:
        async with processing_lock:
            status = await client.send_message(MAIN_ACCOUNT_USERNAME, "🛡 **AI:** Перевіряю фото...")
            path = await event.message.download_media()
            result = await asyncio.to_thread(ask_gemini_all_groups, path, event.message.message)
            os.remove(path)
            
            if isinstance(result, list) and result:
                service = await get_tasks_service()
                schedule = result
                schedule.sort(key=lambda x: x.get('group', ''))
                
                msg_lines = ["⚡️ **ГРАФІК ВІДКЛЮЧЕНЬ (AI):**", ""]
                previous_main_group = None

                for entry in schedule:
                    try:
                        start_dt = parser.parse(entry['start'])
                        end_dt = parser.parse(entry['end'])
                        grp = entry.get('group', '?')
                    except: continue

                    current_main_group = grp.split('.')[0] if '.' in grp else grp
                    if previous_main_group and current_main_group != previous_main_group:
                        msg_lines.append("➖➖➖➖➖➖➖➖")

                    msg_lines.append(f"🔹 **Гр. {grp}:** {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}")
                    previous_main_group = current_main_group

                    if grp == MY_PERSONAL_GROUP:
                        notif_time = start_dt - timedelta(hours=2, minutes=10)
                        task = {
                            'title': f"💡 СВІТЛО (Гр. {grp})",
                            'notes': f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}",
                            'due': notif_time.isoformat() + 'Z'
                        }
                        try: service.tasks().insert(tasklist='@default', body=task).execute()
                        except: pass
                
                await client.delete_messages(None, status)
                full_message = "\n".join(msg_lines) + FOOTER_TEXT
                await client.send_message(CHANNEL_USERNAME, full_message, file=IMG_SCHEDULE)
            else:
                await client.delete_messages(None, status)

async def startup_check():
    global REAL_SIREN_ID
    try:
        await client(JoinChannelRequest(SIREN_CHANNEL_USER))
        entity = await client.get_entity(SIREN_CHANNEL_USER)
        REAL_SIREN_ID = int(f"-100{entity.id}")
        await client.send_message(MAIN_ACCOUNT_USERNAME, f"🟢 **STRUM:** Оновлено. Текст екстрених виправлено.")
    except:
        pass

# === ЗАПУСК ===
if __name__ == '__main__':
    client.start()
    client.loop.create_task(check_weather_alerts()) 
    client.loop.create_task(morning_digest_loop())  
    client.loop.create_task(evening_digest_loop())  
    client.loop.run_until_complete(startup_check())
    print("Bot is running...")
    client.run_until_disconnected()
