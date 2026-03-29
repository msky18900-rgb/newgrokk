import asyncio
import os
import pickle
import time
from pyrogram import Client, filters
from pyrogram.types import Message
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow  # not used at runtime
import google.auth

# Config
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
DATA_DIR = "/data"
DOWNLOAD_DIR = f"{DATA_DIR}/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = Client("my_userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# Load YouTube credentials
with open(f"{DATA_DIR}/token.json", "rb") as f:
    creds = pickle.load(f)
youtube = build("youtube", "v3", credentials=creds)

# Queue + lock
video_queue = asyncio.Queue()
processing_lock = asyncio.Lock()
STATUS_MESSAGES = {}  # chat_id: {message_id: status_msg}

async def progress_callback(current: int, total: int, status_msg: Message, stage: str):
    """Throttle edits (every 5% or 10s)"""
    if not hasattr(progress_callback, "last_update"):
        progress_callback.last_update = {}
    key = f"{stage}_{status_msg.id}"
    now = time.time()
    percent = (current / total) * 100 if total else 0
    if key not in progress_callback.last_update or (now - progress_callback.last_update[key] > 8) or percent % 5 < 1:
        progress_callback.last_update[key] = now
        try:
            await status_msg.edit(f"**{stage}**\n`{percent:.1f}%` ({current//(1024*1024)}MB / {total//(1024*1024)}MB)")
        except: pass

async def upload_to_youtube(file_path: str, title: str, description: str, status_msg: Message):
    """Resumable upload with progress"""
    await status_msg.edit("**Uploading to YouTube...** (0%)")
    body = {
        "snippet": {"title": title, "description": description, "categoryId": "22"},  # 22 = People & Blogs
        "status": {"privacyStatus": "private"}  # change to public/unlisted later
    }
    media = MediaFileUpload(file_path, chunksize=10*1024*1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            percent = int(status.progress() * 100)
            await status_msg.edit(f"**Uploading to YouTube...** `{percent}%`")
    await status_msg.edit(f"✅ **Uploaded!** Video ID: `{response['id']}`\nhttps://youtu.be/{response['id']}")

async def process_queue():
    """Background worker - one video at a time"""
    while True:
        task = await video_queue.get()
        msg: Message = task["msg"]
        status_msg: Message = task["status_msg"]

        try:
            async with processing_lock:
                # Download
                file_name = msg.video.file_name or f"video_{int(time.time())}.mp4"
                file_path = f"{DOWNLOAD_DIR}/{file_name}"
                await status_msg.edit("**Downloading from Telegram...** (0%)")
                await msg.download(file_path, progress=progress_callback, progress_args=(status_msg, "Downloading"))

                # Upload
                title = msg.caption or file_name if msg.caption else file_name
                desc = msg.caption or "Uploaded via Telegram Userbot"
                await upload_to_youtube(file_path, title, desc, status_msg)

                # Cleanup
                if os.path.exists(file_path):
                    os.remove(file_path)

        except Exception as e:
            await status_msg.edit(f"❌ Error: {str(e)[:200]}")
        finally:
            video_queue.task_done()

@app.on_message(filters.video & filters.private)  # or add & filters.chat(YOUR_GROUP_ID)
async def handle_video(client: Client, message: Message):
    if message.from_user.id != int(os.getenv("BOT_OWNER_ID")):  # security
        return
    status_msg = await message.reply("**Queued!** Waiting in line...")
    await video_queue.put({"msg": message, "status_msg": status_msg})

@app.on_message(filters.command("queue"))
async def show_queue(client, message):
    await message.reply(f"**Queue size:** {video_queue.qsize()}")

# Start worker
@app.on_start()
async def start_bot(client):
    asyncio.create_task(process_queue())
    print("🚀 Userbot started with queue!")

if __name__ == "__main__":
    app.run()
