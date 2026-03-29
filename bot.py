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

# ==================== CONFIG FROM RAILWAY ====================
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

DATA_DIR = "/data"
DOWNLOAD_DIR = f"{DATA_DIR}/downloads"
CLIENT_SECRETS_FILE = f"{DATA_DIR}/client_secrets.json"
TOKEN_FILE = f"{DATA_DIR}/token.pickle"
SESSION_FILE = f"{DATA_DIR}/session.txt"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
# ======================================================

# Load session if exists
if os.path.exists(SESSION_FILE):
    with open(SESSION_FILE, "r") as f:
        SESSION_STRING = f.read().strip()
else:
    SESSION_STRING = None

app = Client("yt_uploader_bot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

youtube = None
pending_flows = {}
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
setup_state = {}  # user_id : step

# ===================== SETUP WIZARD =====================
@app.on_message(filters.command(["start", "setup"]) & filters.private)
async def start_setup(client, message: Message):
    user_id = message.from_user.id
    if os.path.exists(SESSION_FILE):
        await message.reply("✅ Already logged in!\nSend `/youtube_auth` to connect YouTube or forward a video.")
        return
    setup_state[user_id] = "phone"
    await message.reply(
        "🔧 **Interactive Setup Started**\n\n"
        "📱 Send your **phone number** with country code\n"
        "Example: `+919876543210`"
    )

@app.on_message(filters.private)
async def handle_setup(client, message: Message):
    user_id = message.from_user.id
    if user_id not in setup_state:
        return

    step = setup_state[user_id]

    if step == "phone":
        phone = message.text.strip()
        setup_state[user_id] = {"step": "code", "phone": phone}
        await message.reply(f"✅ Phone saved: `{phone}`\n\nSend the **OTP** you just received on Telegram")

    elif isinstance(setup_state[user_id], dict) and setup_state[user_id]["step"] == "code":
        code = message.text.strip()
        phone = setup_state[user_id]["phone"]
        try:
            await app.sign_in(phone=phone, code=code)
            session_str = await app.export_session_string()
            with open(SESSION_FILE, "w") as f:
                f.write(session_str)
            del setup_state[user_id]
            await message.reply("✅ **Login successful!** Session saved.\n\nNow send `/youtube_auth` to connect YouTube.")
        except Exception as e:
            await message.reply(f"❌ Error: {str(e)}\nTry /setup again.")

# ===================== YOUTUBE AUTH & VIDEO HANDLING =====================
# (same working code as before - progress, queue, upload)

video_queue = asyncio.Queue()
processing_lock = asyncio.Lock()

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

@app.on_message(filters.document & filters.private)
async def handle_client_secrets(client, message: Message):
    filename = (message.document.file_name or "").lower()
    if filename.endswith(".json"):
        await message.download(CLIENT_SECRETS_FILE)
        await message.reply("✅ `client_secrets.json` saved!\nNow send `/youtube_auth`")
    else:
        await message.reply("❌ Please send your `client_secrets.json` file from Google Cloud.")

@app.on_message(filters.command("youtube_auth") & filters.private)
async def youtube_auth_command(client, message: Message):
    status_msg = await message.reply("🔄 Checking...")
    if await load_or_auth_youtube():
        await status_msg.edit("✅ YouTube already authenticated!")
    else:
        if not os.path.exists(CLIENT_SECRETS_FILE):
            await status_msg.edit("❌ First send `client_secrets.json` file!")
            return
        # same flow as before (auth_url + /code)
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
        auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
        pending_flows[message.from_user.id] = flow
        await status_msg.edit(
            f"🔐 Open this link:\n`{auth_url}`\nLogin → copy code → send `/code YOUR_CODE`"
        )

@app.on_message(filters.command("code") & filters.private)
async def handle_auth_code(client, message: Message):
    # same as before
    code = message.text.split(maxsplit=1)[-1].strip()
    # ... process_auth_code function (same as previous versions)

# ===================== QUEUE + DOWNLOAD + UPLOAD (full) =====================
# (paste the full progress_callback, upload_to_youtube, process_queue, handle_video from my earlier messages)

async def main():
    await app.start()
    print("🚀 Interactive Bot Started - PM me /setup")
    await idle()

if __name__ == "__main__":
    asyncio.run(main())
