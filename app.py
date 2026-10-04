import os
import re
import io
import zipfile
import asyncio
import logging
import mimetypes
from typing import Optional, List, Dict, Any
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Response, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import humanize

import config
import database
from telegram_service import telegram_service
from gdrive_service import transfer_gdrive_to_telegram
from task_manager import task_manager
from bot_service import bot_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize database & load task history
    await database.init_db()
    await task_manager.load_tasks_from_db()
    
    # Check telegram status & start Bot listeners
    try:
        auth = await telegram_service.get_auth_status()
        if auth.get("authorized"):
            await bot_service.start()
    except Exception as e:
        logger.warning(f"Telegram auto-connect notice: {e}")
        
    yield

app = FastAPI(title="Telegram Cloud Storage Drive & Web Hosting", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Request Models -----------------
class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None

class FolderRename(BaseModel):
    name: str

class FolderMove(BaseModel):
    parent_id: Optional[int] = None

class FileRename(BaseModel):
    name: str

class FileMove(BaseModel):
    folder_id: Optional[int] = None

class TextFileCreate(BaseModel):
    name: str
    content: str
    folder_id: Optional[int] = None

class TextFileUpdate(BaseModel):
    content: str

class RemoteTransferRequest(BaseModel):
    url: str
    folder_id: Optional[int] = None
    cookie: Optional[str] = None

class AuthSendCodeRequest(BaseModel):
    api_id: str
    api_hash: str
    phone: str

class AuthVerifyCodeRequest(BaseModel):
    phone: str
    code: str
    phone_code_hash: Optional[str] = None
    password: Optional[str] = None

class AuthBotLoginRequest(BaseModel):
    api_id: str
    api_hash: str
    bot_token: str

class SettingsUpdate(BaseModel):
    gdrive_cookie: Optional[str] = None

# ----------------- Auth Endpoints -----------------
@app.get("/api/auth/status")
async def get_auth_status():
    status = await telegram_service.get_auth_status()
    if status.get("authorized") and not bot_service.handlers_registered:
        asyncio.create_task(bot_service.start())
    return status

@app.post("/api/auth/send-code")
async def send_code(req: AuthSendCodeRequest):
    res = await telegram_service.send_phone_code(req.api_id.strip(), req.api_hash.strip(), req.phone.strip())
    return res

@app.post("/api/auth/verify-code")
async def verify_code(req: AuthVerifyCodeRequest):
    res = await telegram_service.sign_in_with_code(
        phone=req.phone.strip(),
        code=req.code.strip(),
        phone_code_hash=req.phone_code_hash,
        password=req.password
    )
    if res.get("success"):
        asyncio.create_task(bot_service.start())
    return res

@app.post("/api/auth/bot-login")
async def bot_login(req: AuthBotLoginRequest):
    res = await telegram_service.sign_in_bot(
        api_id=req.api_id.strip(),
        api_hash=req.api_hash.strip(),
        bot_token=req.bot_token.strip()
    )
    if res.get("success"):
        asyncio.create_task(bot_service.start())
    return res

@app.post("/api/auth/logout")
async def logout():
    success = await telegram_service.logout()
    bot_service.handlers_registered = False
    return {"success": success}

# ----------------- Settings Endpoints -----------------
@app.get("/api/settings")
async def get_settings():
    cookie = await database.get_setting("gdrive_cookie", "")
    return {"gdrive_cookie": cookie}

@app.post("/api/settings")
async def update_settings(req: SettingsUpdate):
    if req.gdrive_cookie is not None:
        await database.set_setting("gdrive_cookie", req.gdrive_cookie.strip())
    return {"success": True}

# ----------------- Folders Endpoints -----------------
@app.get("/api/folders")
async def list_folders(parent_id: Optional[int] = None):
    folders = await database.get_folders_enhanced(parent_id)
    return folders

@app.post("/api/folders")
async def create_folder_endpoint(req: FolderCreate):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Folder name cannot be empty")
    new_folder = await database.create_folder(name, req.parent_id)
    new_folder["has_website"] = False
    return new_folder

@app.put("/api/folders/{folder_id}")
async def rename_folder_endpoint(folder_id: int, req: FolderRename):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Folder name cannot be empty")
    await database.rename_folder(folder_id, name)
    return {"success": True, "id": folder_id, "name": name}

@app.put("/api/folders/{folder_id}/move")
async def move_folder_endpoint(folder_id: int, req: FolderMove):
    success = await database.move_folder(folder_id, req.parent_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot move folder into itself or its own subfolder")
    return {"success": True, "id": folder_id, "parent_id": req.parent_id}

@app.delete("/api/folders/{folder_id}")
async def delete_folder_endpoint(folder_id: int, background_tasks: BackgroundTasks):
    deleted_files = await database.delete_folder_recursive(folder_id)
    
    # Delete corresponding telegram messages in background
    async def cleanup_telegram_files(files):
        for f in files:
            try:
                await telegram_service.delete_message(f["telegram_msg_id"], f["telegram_chat_id"])
            except Exception as e:
                logger.error(f"Failed to delete telegram msg for file {f['id']}: {e}")
                
    background_tasks.add_task(cleanup_telegram_files, deleted_files)
    return {"success": True, "deleted_files_count": len(deleted_files)}

@app.get("/api/folders/{folder_id}/breadcrumbs")
async def get_breadcrumbs(folder_id: Optional[int] = None):
    return await database.get_folder_breadcrumbs(folder_id)

@app.get("/api/folders/{folder_id}/download-zip")
async def download_folder_zip(folder_id: int):
    """Bundle and stream entire folder and subfolders as a ZIP archive"""
    folder = await database.get_folder(folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    folder_files = await database.get_folder_files_recursive(folder_id)
    if not folder_files:
        raise HTTPException(status_code=400, detail="Folder is empty")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for f in folder_files:
            file_bytes = await telegram_service.download_file_bytes(f["telegram_msg_id"], f["telegram_chat_id"])
            if file_bytes is not None:
                zip_path = f.get("relative_path", f["name"])
                zip_file.writestr(zip_path, file_bytes)

    zip_buffer.seek(0)
    zip_filename = f"{re.sub(r'[\\/*?:<>|]', '_', folder['name'])}.zip"

    headers = {
        "Content-Disposition": f'attachment; filename="{zip_filename}"',
        "Content-Length": str(zip_buffer.getbuffer().nbytes)
    }
    return Response(content=zip_buffer.getvalue(), media_type="application/zip", headers=headers)

@app.post("/api/folders/{folder_id}/init-website")
async def init_static_website(folder_id: int):
    """1-Click Website Starter Template (index.html, style.css, script.js)"""
    auth = await telegram_service.get_auth_status()
    if not auth.get("authorized"):
        raise HTTPException(status_code=401, detail="Telegram is not connected")

    folder = await database.get_folder(folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    starter_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{folder['name']} - Hosted on TeleCloud</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div class="card">
        <h1>🚀 Hello World!</h1>
        <p>This website is hosted directly from <strong>Telegram Cloud Storage</strong>.</p>
        <button onclick="greet()">Click Me</button>
        <p id="msg"></p>
    </div>
    <script src="script.js"></script>
</body>
</html>"""

    starter_css = """body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: linear-gradient(135deg, #0f172a, #1e293b);
    color: #f8fafc;
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    margin: 0;
}
.card {
    background: rgba(30, 41, 59, 0.8);
    backdrop-filter: blur(12px);
    border: 1px solid #334155;
    padding: 2.5rem;
    border-radius: 1.5rem;
    text-align: center;
    max-width: 480px;
    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);
}
h1 { color: #38bdf8; margin-top: 0; }
button {
    background: #0ea5e9;
    color: white;
    border: none;
    padding: 0.75rem 1.5rem;
    font-size: 1rem;
    font-weight: 600;
    border-radius: 0.75rem;
    cursor: pointer;
    transition: transform 0.2s, background 0.2s;
}
button:hover {
    background: #0284c7;
    transform: scale(1.05);
}"""

    starter_js = """function greet() {
    document.getElementById('msg').innerText = '🎉 Hosted with TeleCloud on ' + new Date().toLocaleTimeString();
}"""

    # Upload files to Telegram and record in DB
    files_to_create = [
        ("index.html", starter_html.encode("utf-8"), "text/html"),
        ("style.css", starter_css.encode("utf-8"), "text/css"),
        ("script.js", starter_js.encode("utf-8"), "application/javascript"),
    ]

    for fname, content_bytes, mime in files_to_create:
        existing = await database.get_file_by_name(folder_id, fname)
        upload_res = await telegram_service.upload_bytes(content_bytes, fname, chat_id="me")
        if existing:
            await database.update_file_entry(
                existing["id"], fname, len(content_bytes), mime,
                upload_res["message_id"], upload_res["chat_id"]
            )
        else:
            await database.add_file(
                name=fname,
                size=len(content_bytes),
                mime_type=mime,
                folder_id=folder_id,
                telegram_msg_id=upload_res["message_id"],
                telegram_chat_id=upload_res["chat_id"]
            )

    return {
        "success": True,
        "site_url": f"/site/{folder_id}/"
    }

# ----------------- Files Endpoints -----------------
@app.get("/api/files")
async def list_files(folder_id: Optional[int] = None):
    files = await database.get_files(folder_id)
    for f in files:
        f["human_size"] = humanize.naturalsize(f["size"])
    return files

@app.get("/api/files/{file_id}")
async def get_file_info(file_id: int):
    file_data = await database.get_file(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail="File not found")
    file_data["human_size"] = humanize.naturalsize(file_data["size"])
    return file_data

@app.put("/api/files/{file_id}/rename")
async def rename_file_endpoint(file_id: int, req: FileRename):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="File name cannot be empty")
    await database.rename_file(file_id, name)
    return {"success": True, "id": file_id, "name": name}

@app.put("/api/files/{file_id}/move")
async def move_file_endpoint(file_id: int, req: FileMove):
    await database.move_file(file_id, req.folder_id)
    return {"success": True, "id": file_id, "folder_id": req.folder_id}

@app.delete("/api/files/{file_id}")
async def delete_file_endpoint(file_id: int, background_tasks: BackgroundTasks):
    file_data = await database.delete_file(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail="File not found")
        
    async def cleanup_telegram_file(msg_id, chat_id):
        try:
            await telegram_service.delete_message(msg_id, chat_id)
        except Exception as e:
            logger.error(f"Error deleting telegram message {msg_id}: {e}")
            
    background_tasks.add_task(cleanup_telegram_file, file_data["telegram_msg_id"], file_data["telegram_chat_id"])
    return {"success": True, "id": file_id}

# ----------------- Code & Text Editor Endpoints -----------------
@app.get("/api/files/{file_id}/content")
async def get_file_content_text(file_id: int):
    """Retrieve raw text content of file for the built-in Code Editor"""
    file_data = await database.get_file(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail="File not found")

    content_bytes = await telegram_service.download_file_bytes(
        file_data["telegram_msg_id"], file_data["telegram_chat_id"]
    )
    if content_bytes is None:
        raise HTTPException(status_code=500, detail="Failed to fetch file from Telegram")

    try:
        text_content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text_content = content_bytes.decode("latin1", errors="replace")

    return {
        "id": file_id,
        "name": file_data["name"],
        "mime_type": file_data["mime_type"],
        "content": text_content
    }

@app.put("/api/files/{file_id}/content")
async def save_file_content_text(file_id: int, req: TextFileUpdate, background_tasks: BackgroundTasks):
    """Save updated text content directly back to Telegram Cloud"""
    file_data = await database.get_file(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail="File not found")

    content_bytes = req.content.encode("utf-8")
    upload_res = await telegram_service.upload_bytes(
        content_bytes, file_data["name"], chat_id="me"
    )

    old_msg_id = file_data["telegram_msg_id"]
    old_chat_id = file_data["telegram_chat_id"]

    updated_file = await database.update_file_entry(
        file_id=file_id,
        name=file_data["name"],
        size=len(content_bytes),
        mime_type=file_data["mime_type"] or "text/plain",
        telegram_msg_id=upload_res["message_id"],
        telegram_chat_id=upload_res["chat_id"]
    )

    # Delete previous telegram message version
    background_tasks.add_task(telegram_service.delete_message, old_msg_id, old_chat_id)

    return {"success": True, "file": updated_file}

@app.post("/api/files/text")
async def create_text_file(req: TextFileCreate):
    """Create a new text/code/HTML file directly in current folder"""
    auth = await telegram_service.get_auth_status()
    if not auth.get("authorized"):
        raise HTTPException(status_code=401, detail="Telegram is not connected")

    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="File name cannot be empty")

    mime_type, _ = mimetypes.guess_type(name)
    mime_type = mime_type or "text/plain"
    content_bytes = req.content.encode("utf-8")

    upload_res = await telegram_service.upload_bytes(
        content_bytes, name, chat_id="me"
    )

    db_file = await database.add_file(
        name=name,
        size=len(content_bytes),
        mime_type=mime_type,
        folder_id=req.folder_id,
        telegram_msg_id=upload_res["message_id"],
        telegram_chat_id=upload_res["chat_id"]
    )

    return {"success": True, "file": db_file}

# ----------------- Upload & Remote Transfer -----------------
@app.post("/api/upload")
async def upload_local_file(
    file: UploadFile = File(...),
    folder_id: Optional[int] = Form(None)
):
    """Direct upload from computer to Telegram Saved Messages"""
    auth = await telegram_service.get_auth_status()
    if not auth.get("authorized"):
        raise HTTPException(status_code=401, detail="Telegram is not connected. Please connect Telegram in settings.")

    task_id = task_manager.create_task("local_upload", file.filename or "uploaded_file")
    temp_path = config.TEMP_DIR / f"upload_{task_id}_{file.filename}"
    
    async def process_upload():
        try:
            task_manager.update_task(task_id, status="uploading", step="Saving temporary file...", progress=10)
            
            with open(temp_path, "wb") as buffer:
                while chunk := await file.read(1024 * 1024):
                    buffer.write(chunk)
                    
            file_size = os.path.getsize(temp_path)
            
            def tg_progress(current, total):
                if total > 0:
                    pct = 10 + int((current / total) * 85)
                    task_manager.update_task(
                        task_id,
                        progress=pct,
                        step=f"Uploading to Telegram: {humanize.naturalsize(current)} / {humanize.naturalsize(total)}"
                    )
                    
            upload_res = await telegram_service.upload_file(
                file_path=str(temp_path),
                file_name=file.filename,
                chat_id="me",
                progress_callback=tg_progress
            )
            
            db_file = await database.add_file(
                name=file.filename,
                size=file_size,
                mime_type=upload_res["mime_type"],
                folder_id=folder_id,
                telegram_msg_id=upload_res["message_id"],
                telegram_chat_id=upload_res["chat_id"]
            )
            
            task_manager.update_task(
                task_id,
                status="completed",
                progress=100,
                step="Uploaded successfully to Telegram Cloud!",
                result=db_file
            )
        except Exception as e:
            logger.error(f"Local upload failed: {e}", exc_info=True)
            task_manager.update_task(task_id, status="failed", error=str(e), step=f"Error: {str(e)}")
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
                
    asyncio.create_task(process_upload())
    return {"success": True, "task_id": task_id}

@app.post("/api/remote/gdrive")
@app.post("/api/remote/url")
async def import_remote_file(req: RemoteTransferRequest):
    """Import Google Drive link or ANY direct HTTP/HTTPS file into Telegram Cloud"""
    auth = await telegram_service.get_auth_status()
    if not auth.get("authorized"):
        raise HTTPException(status_code=401, detail="Telegram is not connected. Please connect Telegram in settings.")

    task_id = task_manager.create_task("remote_transfer", "Remote Cloud Transfer", {"url": req.url, "folder_id": req.folder_id})
    asyncio.create_task(transfer_gdrive_to_telegram(req.url, req.folder_id, task_id, cookie_override=req.cookie))
    return {"success": True, "task_id": task_id}

# ----------------- Task Management -----------------
@app.get("/api/tasks")
async def get_tasks():
    return task_manager.get_all_tasks()

@app.post("/api/tasks/{task_id}/retry")
async def retry_task(task_id: str):
    """Resume / Retry interrupted or failed transfer task"""
    task = task_manager.get_task(task_id) or await database.get_db_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    url = task.get("url") or task.get("metadata", {}).get("url")
    if not url:
        raise HTTPException(status_code=400, detail="Cannot retry task without source URL")
        
    folder_id = task.get("folder_id") or task.get("metadata", {}).get("folder_id")
    cookie = task.get("cookie") or task.get("metadata", {}).get("cookie")
    
    task_manager.update_task(
        task_id,
        status="downloading",
        error=None,
        step="Resuming transfer..."
    )
    asyncio.create_task(transfer_gdrive_to_telegram(url, folder_id, task_id, cookie_override=cookie))
    return {"success": True, "task_id": task_id}

@app.delete("/api/tasks/clear")
async def clear_tasks():
    await task_manager.clear_completed_tasks()
    return {"success": True}

# ----------------- Public Share Endpoints -----------------
@app.post("/api/files/{file_id}/share")
async def share_file_endpoint(file_id: int):
    """Generate or retrieve permanent public share link for a file"""
    file_data = await database.get_file(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail="File not found")
    share = await database.create_or_get_share_link(file_id)
    return {
        "success": True,
        "token": share["token"],
        "share_url": f"/s/{share['token']}"
    }

@app.get("/s/{token}")
async def public_share_page(token: str):
    """Public web page for shared file"""
    share_page = config.STATIC_DIR / "share.html"
    if share_page.exists():
        return FileResponse(share_page)
    return HTMLResponse("<h1>Shared File Page</h1>")

@app.get("/api/public/{token}/info")
async def public_share_info(token: str):
    """Public info endpoint for shared file"""
    info = await database.get_share_link_info(token)
    if not info:
        raise HTTPException(status_code=404, detail="Share link not found or expired")
    info["human_size"] = humanize.naturalsize(info["size"])
    return info

@app.get("/api/public/{token}/download")
async def public_download_endpoint(token: str, background_tasks: BackgroundTasks):
    """Public direct download endpoint"""
    info = await database.get_share_link_info(token)
    if not info:
        raise HTTPException(status_code=404, detail="Share link not found or expired")
        
    background_tasks.add_task(database.increment_share_downloads, token)
    file_size = info["size"]
    mime_type = info["mime_type"] or "application/octet-stream"
    file_name = info["name"]
    
    headers = {
        "Content-Disposition": f'attachment; filename="{file_name}"',
        "Content-Length": str(file_size),
        "Content-Type": mime_type
    }
    
    stream_gen = telegram_service.stream_file(
        message_id=info["telegram_msg_id"],
        chat_id=info["telegram_chat_id"],
        offset=0,
        length=file_size
    )
    return StreamingResponse(stream_gen, headers=headers, media_type=mime_type)

@app.get("/api/public/{token}/stream")
async def public_stream_endpoint(token: str, request: Request):
    """Public range-based media stream endpoint"""
    info = await database.get_share_link_info(token)
    if not info:
        raise HTTPException(status_code=404, detail="Share link not found or expired")
        
    file_size = info["size"]
    mime_type = info["mime_type"] or "application/octet-stream"
    file_name = info["name"]
    
    range_header = request.headers.get("range")
    if range_header:
        match = re.search(r"bytes=(\d+)-(\d*)", range_header)
        if match:
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else file_size - 1
            end = min(end, file_size - 1)
            content_length = end - start + 1
            
            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
                "Content-Type": mime_type,
                "Content-Disposition": f'inline; filename="{file_name}"'
            }
            
            stream_gen = telegram_service.stream_file(
                message_id=info["telegram_msg_id"],
                chat_id=info["telegram_chat_id"],
                offset=start,
                length=content_length
            )
            return StreamingResponse(stream_gen, status_code=206, headers=headers, media_type=mime_type)
            
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Type": mime_type,
        "Content-Disposition": f'inline; filename="{file_name}"'
    }
    stream_gen = telegram_service.stream_file(
        message_id=info["telegram_msg_id"],
        chat_id=info["telegram_chat_id"],
        offset=0,
        length=file_size
    )
    return StreamingResponse(stream_gen, headers=headers, media_type=mime_type)

# ----------------- Media Streaming & Downloads -----------------
@app.get("/api/stream/{file_id}")
async def stream_media(file_id: int, request: Request):
    """Stream media (Video, Audio, Images) with HTTP Range support"""
    file_data = await database.get_file(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail="File not found")
        
    file_size = file_data["size"]
    mime_type = file_data["mime_type"] or "application/octet-stream"
    file_name = file_data["name"]
    
    range_header = request.headers.get("range")
    if range_header:
        match = re.search(r"bytes=(\d+)-(\d*)", range_header)
        if match:
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else file_size - 1
            end = min(end, file_size - 1)
            content_length = end - start + 1
            
            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
                "Content-Type": mime_type,
                "Content-Disposition": f'inline; filename="{file_name}"'
            }
            
            stream_gen = telegram_service.stream_file(
                message_id=file_data["telegram_msg_id"],
                chat_id=file_data["telegram_chat_id"],
                offset=start,
                length=content_length
            )
            return StreamingResponse(stream_gen, status_code=206, headers=headers, media_type=mime_type)
            
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Type": mime_type,
        "Content-Disposition": f'inline; filename="{file_name}"'
    }
    stream_gen = telegram_service.stream_file(
        message_id=file_data["telegram_msg_id"],
        chat_id=file_data["telegram_chat_id"],
        offset=0,
        length=file_size
    )
    return StreamingResponse(stream_gen, headers=headers, media_type=mime_type)

@app.get("/api/download/{file_id}")
async def download_file(file_id: int):
    """Direct file download attachment"""
    file_data = await database.get_file(file_id)
    if not file_data:
        raise HTTPException(status_code=404, detail="File not found")
        
    file_size = file_data["size"]
    mime_type = file_data["mime_type"] or "application/octet-stream"
    file_name = file_data["name"]
    
    headers = {
        "Content-Disposition": f'attachment; filename="{file_name}"',
        "Content-Length": str(file_size),
        "Content-Type": mime_type
    }
    
    stream_gen = telegram_service.stream_file(
        message_id=file_data["telegram_msg_id"],
        chat_id=file_data["telegram_chat_id"],
        offset=0,
        length=file_size
    )
    return StreamingResponse(stream_gen, headers=headers, media_type=mime_type)

# ----------------- Virtual Static Website Hosting -----------------
@app.get("/site/{folder_id}")
@app.get("/site/{folder_id}/")
@app.get("/site/{folder_id}/{subpath:path}")
async def serve_static_website(folder_id: int, subpath: str = ""):
    """
    Host and serve any static website stored in a Telegram Cloud folder.
    Supports index.html, subdirectories, css, js, images, fonts, etc.
    """
    target_path = subpath if subpath else "index.html"
    file_data = await database.get_file_by_relative_path(folder_id, target_path)

    if not file_data:
        # Check if requested a directory without trailing slash
        if not subpath or subpath.endswith("/"):
            file_data = await database.get_file_by_name(folder_id, "index.html")

    if not file_data:
        raise HTTPException(
            status_code=404,
            detail=f"File '{target_path}' not found in hosted folder {folder_id}."
        )

    file_size = file_data["size"]
    mime_type = file_data["mime_type"] or mimetypes.guess_type(file_data["name"])[0] or "text/html"
    
    # Specific content-type overrides for web standards
    if file_data["name"].endswith(".html"):
        mime_type = "text/html; charset=utf-8"
    elif file_data["name"].endswith(".css"):
        mime_type = "text/css; charset=utf-8"
    elif file_data["name"].endswith(".js"):
        mime_type = "application/javascript; charset=utf-8"

    headers = {
        "Content-Length": str(file_size),
        "Content-Type": mime_type,
        "Cache-Control": "public, max-age=300"
    }

    stream_gen = telegram_service.stream_file(
        message_id=file_data["telegram_msg_id"],
        chat_id=file_data["telegram_chat_id"],
        offset=0,
        length=file_size
    )
    return StreamingResponse(stream_gen, headers=headers, media_type=mime_type)

# ----------------- Search & Stats -----------------
@app.get("/api/search")
async def search_endpoint(q: str):
    res = await database.search_items(q)
    for f in res["files"]:
        f["human_size"] = humanize.naturalsize(f["size"])
    return res

@app.get("/api/stats")
async def stats_endpoint():
    stats = await database.get_storage_stats()
    stats["human_size"] = humanize.naturalsize(stats["total_size"])
    return stats

# ----------------- Static UI Mount -----------------
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

@app.get("/")
async def root():
    index_file = config.STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>Telegram Cloud Storage Backend Running</h1><p>UI is being loaded...</p>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=config.HOST, port=config.PORT, reload=True)
