import os
import asyncio
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# Получаем ключи
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']

# Настройки каналов
SOURCE_CHANNELS = ['dtek_ua', 'avariykaaa'] 
TARGET_CHANNEL = 'strum_dp'

print("--- БОТ ЗАПУЩЕН ---")

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

@client.on(events.NewMessage(chats=SOURCE_CHANNELS))
async def handler(event):
    if not event.message.message:
        return
        
    original_text = event.message.message
    source_name = event.chat.title
    
    # Новый текст
    new_text = f"{original_text}\n\n⚡️ Джерело: {source_name}"
    
    print(f"Пост из {source_name}! Публикую...")

    try:
        # Публикуем с картинкой logo.png
        await client.send_file(
            TARGET_CHANNEL,
            'logo.png',
            caption=new_text
        )
    except Exception as e:
        print(f"Ошибка: {e}")

with client:
    client.run_until_disconnected()
