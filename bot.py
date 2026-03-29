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

# ==================== MONKEY PATCH FOR PYROGRAM BUG ====================
import pyrogram.utils
def patched_get_peer_type(peer_id: int):
    if isinstance(peer_id, int):
        if peer_id > 0:
            return "user"
        elif str(peer_id).startswith("-100"):
            return "channel"
        else:
            return "group"
    raise ValueError(f"Peer id invalid: {peer_id}")
pyrogram.utils.get_peer_type = patched_get_peer_type
# =====================================================================

# ==================== HARDCODED CONFIG ====================
API_ID = 38861262
API_HASH = "607df10d59071e60acb73a9db7993111"
SESSION_STRING = "BQJQ-c4AvpHZC130VQPQCjJsihgzTHOHstjZWokF7ZrUn2bNG7aveLhykusaxKHor0cg2ErxENHJAVT0RDUSDN8h1eHk7np8zoEyTLcX9V1ldsT0fp6apm4hZDtMbCY1-68Jcw-ZsKrVYsXiZpXKzyasQRY4eKTfkwzbNt3q8ea5Kl0mUJ39zLD_rtVkkEJIXFw4rWZBt_J0LCi86dU6wRv1ApfyfpOM_d06qGZpRchm6w-XrQp8MVBwcPt8x75mJ0jCdR5xv8IujPWGz-eGbOC0sVpVMqIVT3w-O1YEtG38okfLYKyBoD-BBkLSLHqf9RrTx-7vWQMAnLAWSwpbnrNhqQQ3twAAAAHt3wQlAA"

BOT_OWNER_ID = 8285783077

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

# ===================== SUPER DEBUG HANDLER (catches EVERY message) =====================
@app.on_message(filters.private)
async def debug_all_messages(client, message: Message):
    if message.from_user.id != BOT_OWNER_ID:
        return
    text = message.text or message.caption or "NO TEXT"
    file_name = message.document.file_name if message.document else "NO FILE"
    print(f"🟢 DEBUG: Received → File: {file_name} | Text: {text}")
    await message.reply(
        f"✅ **Bot received your message!**\n\n"
        f"📄 File: `{file_name}`\n"
        f"💬 Text: `{text}`\n\n"
        f"Send `/youtube_auth` now!"
    )

# ===================== JSON FILE SAVER =====================
@app.on_message(filters.document & filters.private)
async def handle_client_secrets(client, message: Message):
    if message.from_user.id != BOT_OWNER_ID:
        return
    filename = (message.document.file_name or "").lower()
    print(f"📥 Document received: {filename}")
    if filename.endswith(".json"):
        file_path = f"{DATA_DIR}/client_secrets.json"
        await message.download(file_path)
        await message.reply("✅ `client_secrets.json` SAVED!\n\nNow send `/youtube_auth`")
    else:
        await message.reply(f"❌ Not a JSON file. Received: `{filename}`")

# ===================== COMMANDS =====================
@app.on_message(filters.command(["start", "ping"]))
async def ping_command(client, message: Message):
    if message.from_user.id != BOT_OWNER_ID:
        return
    await message.reply("🏓 **Bot is 100% alive!**\nSend your JSON file or /youtube_auth")

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

# ===================== QUEUE & UPLOAD FUNCTIONS =====================
video_queue = asyncio.Queue()
processing_lock = asyncio.Lock()

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

async def start_youtube_auth(status_msg: Message):
    if not os.path.exists(CLIENT_SECRETS_FILE):
        await status_msg.edit("❌ `client_secrets.json` not found.\n\nSend the JSON file again!")
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

# ===================== START =====================
async def main():
    await app.start()
    await load_or_auth_youtube()
    asyncio.create_task(process_queue())
    print("🚀 DEBUG BOT STARTED — listening to EVERY message in Saved Messages")
    await idle()

if __name__ == "__main__":
    asyncio.run(main())
