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

# ==================== MONKEY PATCH ====================
import pyrogram.utils
def patched_get_peer_type(peer_id: int):
    if isinstance(peer_id, int):
        if peer_id > 0: return "user"
        elif str(peer_id).startswith("-100"): return "channel"
        else: return "group"
    raise ValueError(f"Peer id invalid: {peer_id}")
pyrogram.utils.get_peer_type = patched_get_peer_type
# ======================================================

# ==================== CONFIG ====================
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
# ======================================================

app = Client("my_userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

youtube = None
pending_flows = {}
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

async def load_or_auth_youtube():
    global youtube
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f: creds = pickle.load(f)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds:
        return None
    youtube = build("youtube", "v3", credentials=creds)
    return True

# ===================== DEBUG HANDLER (catches EVERYTHING) =====================
@app.on_message(filters.private)
async def debug_all_messages(client, message: Message):
    if message.from_user.id != BOT_OWNER_ID:
        return
    text = message.text or message.caption or "NO TEXT"
    file_name = message.document.file_name if message.document else "NO FILE"
    print(f"🟢 DEBUG: Received message in Saved Messages | Text: {text} | File: {file_name}")
    await message.reply(
        f"✅ **Bot received your message!**\n\n"
        f"📄 File name: `{file_name}`\n"
        f"💬 Text: `{text}`\n\n"
        f"If you sent the JSON file, it should be saved now.\n"
        f"Try sending `/youtube_auth`"
    )

# ===================== JSON SAVER (super loose) =====================
@app.on_message(filters.document & filters.private)
async def handle_client_secrets(client, message: Message):
    if message.from_user.id != BOT_OWNER_ID:
        return
    filename = (message.document.file_name or "").lower()
    print(f"📥 DEBUG: Document received → {filename}")
    if filename.endswith(".json"):
        file_path = f"{DATA_DIR}/client_secrets.json"
        await message.download(file_path)
        await message.reply("✅ `client_secrets.json` SAVED!\n\nNow send `/youtube_auth`")
    else:
        await message.reply(f"❌ Not a JSON file. Received: `{filename}`")

# ===================== COMMANDS =====================
@app.on_message(filters.command("start") | filters.command("ping"))
async def ping_command(client, message: Message):
    if message.from_user.id != BOT_OWNER_ID:
        return
    await message.reply("🏓 **Bot is 100% alive and listening!**\nSend your JSON file again or /youtube_auth")

@app.on_message(filters.command("queue"))
async def show_queue(client, message):
    await message.reply(f"**Queue size:** {video_queue.qsize()}")

@app.on_message(filters.command("youtube_auth"))
async def youtube_auth_command(client, message: Message):
    if message.from_user.id != BOT_OWNER_ID: return
    status_msg = await message.reply("🔄 Checking...")
    if await load_or_auth_youtube():
        await status_msg.edit("✅ Already authenticated!")
    else:
        await start_youtube_auth(status_msg)

@app.on_message(filters.command("code"))
async def handle_auth_code(client, message: Message):
    if message.from_user.id != BOT_OWNER_ID: return
    code = message.text.split(maxsplit=1)[-1].strip()
    status_msg = await message.reply("🔄 Processing code...")
    await process_auth_code(code, status_msg)

# ===================== QUEUE & UPLOAD (unchanged) =====================
video_queue = asyncio.Queue()
processing_lock = asyncio.Lock()

# ... [the rest of the code for queue, download, upload, start_youtube_auth, etc. is the same as last version] ...

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
    # ... same as before ...

async def process_auth_code(code: str, status_msg: Message):
    # ... same as before ...

async def progress_callback(current: int, total: int, status_msg: Message, stage: str):
    # ... same as before ...

async def upload_to_youtube(file_path: str, title: str, description: str, status_msg: Message):
    # ... same as before ...

async def main():
    await app.start()
    await load_or_auth_youtube()
    asyncio.create_task(process_queue())
    print("🚀 DEBUG BOT STARTED - listening to Saved Messages")
    await idle()

if __name__ == "__main__":
    asyncio.run(main())
