import asyncio
import os
import pickle
import time
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# ==================== HARDCODED CONFIG ====================
API_ID = 36114630
API_HASH = "eb058bb41fdd880a6aa81a5050025b69"
SESSION_STRING = "BQInEMYAQOPHizW9YcN-M-5H-XX8GAE3SWMhmOrrIihqXQjABM1J3PK6AVn5WG9aieEnx2IAyiKrtRqpd2B624d1AdsLJ4BM2N0zXuwzz-Ah_JDQ_W4L9vaETIt_952xBVsoDmcz6AVB0ktJ-5bby5ctKVfc8rsxWKqgj1DHfhOylF1iGW-pG5olB_VG_kTZt1iYJfULA6HNUS14wHRmrQhMErlQqvF3677EtTBhYu16PPnAQRtZaSxYvfxWWX9-72sL9MwA_DEm2jZ8uP3-r6yMd_gh1ua2bXjNP6c25Ex37lPL1EJmdqwWILjZjWcCTfeM7_ibpSYEMXhNhwShkpw7o86RcgAAAAHc6-MTAA"

BOT_OWNER_ID = 8001413907

DATA_DIR = "/data"
DOWNLOAD_DIR = f"{DATA_DIR}/downloads"
CLIENT_SECRETS_FILE = f"{DATA_DIR}/client_secrets.json"
TOKEN_FILE = f"{DATA_DIR}/token.pickle"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
# =======================================================

app = Client("my_userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# Global YouTube client + pending auth flows
youtube = None
pending_flows = {}

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

async def load_or_auth_youtube():
    global youtube
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds:
        return None
    youtube = build("youtube", "v3", credentials=creds)
    return True

async def start_youtube_auth(status_msg: Message):
    if not os.path.exists(CLIENT_SECRETS_FILE):
        await status_msg.edit("❌ `client_secrets.json` not found.\n\nSend it as a document now!")
        return
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    pending_flows[BOT_OWNER_ID] = flow
    await status_msg.edit(
        f"🔐 **YouTube Authentication**\n\n"
        f"1. Open: `{auth_url}`\n"
        f"2. Login with your Google account\n"
        f"3. Copy the code\n"
        f"4. Send: `/code YOUR_CODE_HERE`"
    )

async def process_auth_code(code: str, status_msg: Message):
    global youtube
    if BOT_OWNER_ID not in pending_flows:
        await status_msg.edit("❌ No pending auth. Run /youtube_auth first.")
        return
    flow = pending_flows[BOT_OWNER_ID]
    try:
        flow.fetch_token(code=code)
        creds = flow.credentials
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
        youtube = build("youtube", "v3", credentials=creds)
        del pending_flows[BOT_OWNER_ID]
        await status_msg.edit("✅ **YouTube authenticated!** Now forward videos.")
    except Exception as e:
        await status_msg.edit(f"❌ Auth failed: {str(e)}")

async def progress_callback(current: int, total: int, status_msg: Message, stage: str):
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
    await status_msg.edit("**Uploading to YouTube...** (0%)")
    body = {"snippet": {"title": title, "description": description, "categoryId": "22"}, "status": {"privacyStatus": "private"}}
    media = MediaFileUpload(file_path, chunksize=10*1024*1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            percent = int(status.progress() * 100)
            await status_msg.edit(f"**Uploading to YouTube...** `{percent}%`")
    await status_msg.edit(f"✅ **Uploaded!** https://youtu.be/{response['id']}")

video_queue = asyncio.Queue()
processing_lock = asyncio.Lock()

async def process_queue():
    global youtube
    while True:
        task = await video_queue.get()
        msg: Message = task["msg"]
        status_msg: Message = task["status_msg"]
        try:
            async with processing_lock:
                file_name = msg.video.file_name or f"video_{int(time.time())}.mp4"
                file_path = f"{DOWNLOAD_DIR}/{file_name}"
                await status_msg.edit("**Downloading...** (0%)")
                await msg.download(file_path, progress=progress_callback, progress_args=(status_msg, "Downloading"))
                title = msg.caption or file_name
                desc = msg.caption or "Uploaded via Telegram Userbot"
                await upload_to_youtube(file_path, title, desc, status_msg)
                if os.path.exists(file_path):
                    os.remove(file_path)
        except Exception as e:
            await status_msg.edit(f"❌ Error: {str(e)[:200]}")
        finally:
            video_queue.task_done()

# ===================== BYPASS FOR CLIENT_SECRETS.JSON =====================
@app.on_message(filters.document & filters.private)
async def handle_client_secrets(client, message: Message):
    if message.from_user.id != BOT_OWNER_ID:
        return
    if message.document.file_name == "client_secrets.json":
        file_path = f"{DATA_DIR}/client_secrets.json"
        await message.download(file_path)
        await message.reply("✅ `client_secrets.json` saved automatically!\n\nNow send `/youtube_auth`")
    else:
        await message.reply("📄 I only accept `client_secrets.json` for YouTube setup.")

# ===================== COMMANDS =====================
@app.on_message(filters.video & filters.private)
async def handle_video(client: Client, message: Message):
    if message.from_user.id != BOT_OWNER_ID:
        return
    status_msg = await message.reply("**Queued!** Waiting in line...")
    await video_queue.put({"msg": message, "status_msg": status_msg})

@app.on_message(filters.command("queue"))
async def show_queue(client, message):
    await message.reply(f"**Queue size:** {video_queue.qsize()}")

@app.on_message(filters.command("youtube_auth"))
async def youtube_auth_command(client, message: Message):
    if message.from_user.id != BOT_OWNER_ID:
        return
    status_msg = await message.reply("🔄 Checking...")
    if await load_or_auth_youtube():
        await status_msg.edit("✅ Already authenticated!")
    else:
        await start_youtube_auth(status_msg)

@app.on_message(filters.command("code"))
async def handle_auth_code(client, message: Message):
    if message.from_user.id != BOT_OWNER_ID:
        return
    code = message.text.split(maxsplit=1)[-1].strip()
    status_msg = await message.reply("🔄 Processing code...")
    await process_auth_code(code, status_msg)

# ===================== CORRECT STARTUP =====================
async def main():
    await app.start()
    await load_or_auth_youtube()
    asyncio.create_task(process_queue())
    print("🚀 Userbot started with queue + auto client_secrets bypass!")
    await idle()

if __name__ == "__main__":
    asyncio.run(main())
