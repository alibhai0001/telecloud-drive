import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

IS_VERCEL = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

if IS_VERCEL:
    DATA_DIR = Path("/tmp/data")
    TEMP_DIR = Path("/tmp/temp")
else:
    DATA_DIR = BASE_DIR / "data"
    TEMP_DIR = BASE_DIR / "temp"

STATIC_DIR = BASE_DIR / "static"

DATA_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)

API_ID = os.getenv("TELEGRAM_API_ID", "")
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SESSION_NAME = os.getenv("TELEGRAM_SESSION_NAME", str(DATA_DIR / "telegram_cloud"))
STORAGE_CHAT_ID = os.getenv("TELEGRAM_STORAGE_CHAT_ID", "me")
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "127.0.0.1")
DB_PATH = DATA_DIR / "cloud_storage.db"

def update_env_file(key: str, value: str):
    """Update or add a key-value pair in .env file or environment"""
    os.environ[key] = str(value)
    try:
        lines = []
        if ENV_PATH.exists():
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
        
        found = False
        new_lines = []
        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f"{key}={value}\n")
                found = True
            else:
                new_lines.append(line)
                
        if not found:
            new_lines.append(f"{key}={value}\n")
            
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except OSError:
        # Ignore on read-only filesystems (e.g. Vercel)
        pass
