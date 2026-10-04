import sys
from pathlib import Path

# Add project root to sys.path so modules like config, database, telegram_service can be resolved
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app import app as fastapi_app

async def app(scope, receive, send):
    if scope["type"] == "http":
        headers = dict(scope.get("headers", []))
        # Vercel provides x-matched-path or x-forwarded-uri for the actual requested URI
        matched_path = headers.get(b"x-matched-path", b"").decode("latin1")
        forwarded_uri = headers.get(b"x-forwarded-uri", b"").decode("latin1")
        
        target_path = matched_path or forwarded_uri
        if target_path:
            clean_path = target_path.split("?")[0]
            scope["path"] = clean_path
            scope["raw_path"] = clean_path.encode("latin1")
        elif scope.get("path", "").startswith("/api/index.py"):
            new_path = scope["path"][len("/api/index.py"):]
            if not new_path.startswith("/"):
                new_path = "/" + new_path
            scope["path"] = new_path
            scope["raw_path"] = new_path.encode("latin1")

    await fastapi_app(scope, receive, send)
