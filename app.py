import os
import re
import io
import secrets
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

class DeploymentCreate(BaseModel):
    name: str
    slug: str
    folder_id: int
    type: Optional[str] = "static_website"

class StarterDeployRequest(BaseModel):
    name: str
    slug: str
    template_type: str = "portfolio"  # 'portfolio', 'tg_mini_app', 'bio_link', 'retro_game', 'landing'
    parent_id: Optional[int] = None

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
    clean_folder_name = re.sub(r'[\\/*?:<>|]', '_', folder['name'])
    zip_filename = f"{clean_folder_name}.zip"

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

    original_filename = file.filename or "uploaded_file"
    safe_name = re.sub(r'[\\/*?:<>|]', '_', original_filename)
    task_id = task_manager.create_task("local_upload", original_filename, {"folder_id": folder_id})
    temp_path = config.TEMP_DIR / f"upload_{task_id}_{safe_name}"
    
    # Save file stream to disk BEFORE returning response (prevents FastAPI closing file handle)
    try:
        with open(temp_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                buffer.write(chunk)
    except Exception as e:
        logger.error(f"Error saving temp upload file: {e}")
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        task_manager.update_task(task_id, status="failed", error=str(e), step=f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to receive file: {str(e)}")

    file_size = os.path.getsize(temp_path)

    async def process_upload():
        try:
            task_manager.update_task(
                task_id,
                status="uploading",
                step="Uploading to Telegram Saved Messages...",
                progress=15,
                total_bytes=file_size
            )
            
            def tg_progress(current, total):
                if total > 0:
                    pct = 15 + int((current / total) * 80)
                    task_manager.update_task(
                        task_id,
                        progress=pct,
                        step=f"Uploading to Telegram: {humanize.naturalsize(current)} / {humanize.naturalsize(total)}"
                    )
                    
            upload_res = await telegram_service.upload_file(
                file_path=str(temp_path),
                file_name=original_filename,
                chat_id="me",
                progress_callback=tg_progress
            )
            
            db_file = await database.add_file(
                name=original_filename,
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

# ----------------- Deployments & Starter Templates -----------------
def generate_starter_template_files(template_type: str, title: str) -> List[Dict[str, Any]]:
    clean_title = title.strip() or "My Project"
    
    if template_type == "tg_mini_app":
        index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>{clean_title} | Telegram Mini App</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="style.css">
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col font-sans p-4 selection:bg-cyan-500 selection:text-white">
    <div class="max-w-md w-full mx-auto space-y-4 pt-2">
        <div class="bg-slate-900/80 backdrop-blur-xl border border-slate-800 p-5 rounded-2xl shadow-xl flex items-center gap-3.5">
            <div class="w-12 h-12 rounded-xl bg-gradient-to-tr from-cyan-500 to-blue-600 flex items-center justify-center text-white text-xl font-bold shadow-lg shadow-cyan-500/20">
                🚀
            </div>
            <div>
                <h1 class="text-lg font-bold text-white leading-tight">{clean_title}</h1>
                <p class="text-xs text-cyan-400 font-medium">Telegram Mini App</p>
            </div>
        </div>

        <div class="bg-slate-900/80 backdrop-blur-xl border border-slate-800 p-5 rounded-2xl shadow-xl space-y-3">
            <div class="flex items-center gap-3">
                <div id="userAvatar" class="w-10 h-10 rounded-full bg-cyan-500/20 border border-cyan-500/40 text-cyan-400 flex items-center justify-center font-bold text-sm">
                    TG
                </div>
                <div>
                    <h3 id="userName" class="text-sm font-bold text-white">Loading user...</h3>
                    <p id="userHandle" class="text-xs text-slate-400">@telegram_user</p>
                </div>
            </div>
            <div class="pt-2 border-t border-slate-800/80 grid grid-cols-2 gap-2 text-xs text-slate-300">
                <div class="bg-slate-950/60 p-2 rounded-lg border border-slate-800">
                    <span class="text-slate-500 block text-[10px]">PLATFORM</span>
                    <span id="tgPlatform" class="font-semibold text-white">Telegram Web</span>
                </div>
                <div class="bg-slate-950/60 p-2 rounded-lg border border-slate-800">
                    <span class="text-slate-500 block text-[10px]">COLOR SCHEME</span>
                    <span id="tgScheme" class="font-semibold text-cyan-400 capitalize">Dark</span>
                </div>
            </div>
        </div>

        <div class="bg-slate-900/80 backdrop-blur-xl border border-slate-800 p-5 rounded-2xl shadow-xl space-y-3">
            <h2 class="text-xs font-bold text-slate-400 uppercase tracking-wider">Mini App Actions</h2>
            <div class="grid grid-cols-2 gap-2.5">
                <button onclick="triggerHaptic('light')" class="p-3 bg-slate-800 hover:bg-slate-750 border border-slate-700 rounded-xl text-xs font-semibold text-white transition-all active:scale-95 flex flex-col items-center gap-1.5">
                    <span class="text-base">📳</span>
                    <span>Light Haptic</span>
                </button>
                <button onclick="triggerHaptic('heavy')" class="p-3 bg-slate-800 hover:bg-slate-750 border border-slate-700 rounded-xl text-xs font-semibold text-white transition-all active:scale-95 flex flex-col items-center gap-1.5">
                    <span class="text-base">💥</span>
                    <span>Heavy Impact</span>
                </button>
                <button onclick="toggleMainButton()" class="p-3 bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/30 rounded-xl text-xs font-semibold text-cyan-300 transition-all active:scale-95 flex flex-col items-center gap-1.5">
                    <span class="text-base">🔘</span>
                    <span>Toggle MainBtn</span>
                </button>
                <button onclick="sendDataToBot()" class="p-3 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 rounded-xl text-xs font-semibold text-emerald-300 transition-all active:scale-95 flex flex-col items-center gap-1.5">
                    <span class="text-base">📤</span>
                    <span>Send Data</span>
                </button>
            </div>
        </div>

        <div class="text-center text-[11px] text-slate-500 space-y-1">
            <p>Hosted on <span class="text-slate-400 font-medium">TeleCloud</span> via Telegram Cloud</p>
            <p class="font-mono text-[10px]" id="versionBadge">SDK v?.?</p>
        </div>
    </div>
    <script src="app.js"></script>
</body>
</html>"""

        style_css = """:root {
    --tg-bg: var(--tg-theme-bg-color, #0f172a);
    --tg-text: var(--tg-theme-text-color, #f8fafc);
    --tg-btn: var(--tg-theme-button-color, #0088cc);
    --tg-btn-text: var(--tg-theme-button-text-color, #ffffff);
}
body {
    background-color: var(--tg-bg);
    color: var(--tg-text);
}"""

        app_js = """const tg = window.Telegram?.WebApp;
document.addEventListener('DOMContentLoaded', () => {
    if (tg) {
        tg.ready();
        tg.expand();
        const user = tg.initDataUnsafe?.user;
        if (user) {
            document.getElementById('userName').textContent = `${user.first_name || ''} ${user.last_name || ''}`.trim() || 'Telegram User';
            document.getElementById('userHandle').textContent = user.username ? `@${user.username}` : `ID: ${user.id}`;
            document.getElementById('userAvatar').textContent = (user.first_name || 'T')[0].toUpperCase();
        } else {
            document.getElementById('userName').textContent = 'Guest User (Browser)';
            document.getElementById('userHandle').textContent = 'Open in Telegram for full SDK';
        }
        document.getElementById('tgPlatform').textContent = tg.platform || 'web';
        document.getElementById('tgScheme').textContent = tg.colorScheme || 'dark';
        document.getElementById('versionBadge').textContent = `Telegram WebApp SDK v${tg.version || '6.0'}`;
        tg.MainButton.setText('✨ CONFIRM ACTION');
        tg.MainButton.onClick(() => {
            triggerHaptic('heavy');
            tg.showAlert('You clicked the native Telegram MainButton!');
        });
    }
});

function triggerHaptic(style) {
    if (tg?.HapticFeedback) {
        tg.HapticFeedback.impactOccurred(style === 'heavy' ? 'heavy' : 'light');
    }
}

let mainBtnVisible = false;
function toggleMainButton() {
    if (!tg) return;
    triggerHaptic('light');
    mainBtnVisible = !mainBtnVisible;
    if (mainBtnVisible) tg.MainButton.show();
    else tg.MainButton.hide();
}

function sendDataToBot() {
    if (tg) {
        triggerHaptic('heavy');
        tg.showConfirm('Do you want to send action data to the bot?', (confirmed) => {
            if (confirmed) tg.sendData(JSON.stringify({ action: 'user_action', timestamp: Date.now() }));
        });
    } else {
        alert('Send data is available when opened inside Telegram client.');
    }
}"""
        return [
            {"name": "index.html", "content": index_html, "mime": "text/html"},
            {"name": "style.css", "content": style_css, "mime": "text/css"},
            {"name": "app.js", "content": app_js, "mime": "application/javascript"},
        ]

    elif template_type == "bio_link":
        index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{clean_title} | Links</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="style.css">
</head>
<body class="bg-[#0b0f19] text-slate-100 min-h-screen flex items-center justify-center p-4 font-sans selection:bg-purple-500 selection:text-white">
    <div class="max-w-sm w-full space-y-6 text-center">
        <div class="space-y-3">
            <div class="relative w-24 h-24 mx-auto">
                <div class="w-full h-full rounded-full bg-gradient-to-tr from-purple-500 via-pink-500 to-amber-400 p-1 shadow-xl shadow-purple-500/20 animate-pulse">
                    <div class="w-full h-full rounded-full bg-slate-900 flex items-center justify-center text-3xl font-bold text-white">
                        ✨
                    </div>
                </div>
            </div>
            <div>
                <h1 class="text-xl font-extrabold text-white flex items-center justify-center gap-1.5">
                    <span>{clean_title}</span>
                    <span class="text-cyan-400 text-sm">✓</span>
                </h1>
                <p class="text-xs text-slate-400 mt-1">Creator • Developer • Cloud Explorer</p>
            </div>
        </div>

        <div class="space-y-3">
            <a href="https://t.me/" target="_blank" class="flex items-center justify-between p-4 rounded-2xl bg-slate-900/80 border border-slate-800 hover:border-cyan-500/50 hover:bg-slate-800 text-white font-medium text-sm transition-all hover:scale-[1.02] shadow-lg group">
                <span class="flex items-center gap-3">
                    <span class="text-lg">📢</span>
                    <span>Telegram Channel</span>
                </span>
                <span class="text-slate-500 group-hover:text-cyan-400 transition-colors">→</span>
            </a>

            <a href="https://github.com/" target="_blank" class="flex items-center justify-between p-4 rounded-2xl bg-slate-900/80 border border-slate-800 hover:border-purple-500/50 hover:bg-slate-800 text-white font-medium text-sm transition-all hover:scale-[1.02] shadow-lg group">
                <span class="flex items-center gap-3">
                    <span class="text-lg">🐙</span>
                    <span>GitHub Repositories</span>
                </span>
                <span class="text-slate-500 group-hover:text-purple-400 transition-colors">→</span>
            </a>

            <a href="https://youtube.com/" target="_blank" class="flex items-center justify-between p-4 rounded-2xl bg-slate-900/80 border border-slate-800 hover:border-red-500/50 hover:bg-slate-800 text-white font-medium text-sm transition-all hover:scale-[1.02] shadow-lg group">
                <span class="flex items-center gap-3">
                    <span class="text-lg">🎬</span>
                    <span>YouTube Videos</span>
                </span>
                <span class="text-slate-500 group-hover:text-red-400 transition-colors">→</span>
            </a>

            <button onclick="shareProfile()" class="w-full flex items-center justify-between p-4 rounded-2xl bg-gradient-to-r from-cyan-500 to-blue-600 text-white font-semibold text-sm transition-all hover:scale-[1.02] shadow-lg shadow-cyan-500/20">
                <span class="flex items-center gap-3">
                    <span class="text-lg">🔗</span>
                    <span>Share This Page</span>
                </span>
                <span>↗</span>
            </button>
        </div>

        <p class="text-[11px] text-slate-500">Hosted with TeleCloud Drive</p>
    </div>
    <script>
        function shareProfile() {{
            if (navigator.share) {{
                navigator.share({{ title: '{clean_title}', url: window.location.href }});
            }} else {{
                navigator.clipboard.writeText(window.location.href);
                alert('Link copied to clipboard!');
            }}
        }}
    </script>
</body>
</html>"""
        return [
            {"name": "index.html", "content": index_html, "mime": "text/html"},
            {"name": "style.css", "content": "/* Bio Link Custom styles */", "mime": "text/css"},
        ]

    elif template_type == "retro_game":
        index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>{clean_title} | Galaxy Defender</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="style.css">
</head>
<body class="bg-black text-white min-h-screen flex flex-col items-center justify-center font-sans overflow-hidden select-none">
    <div class="relative max-w-lg w-full flex flex-col items-center p-3">
        <div class="w-full flex items-center justify-between px-4 py-2 bg-slate-900/80 border border-slate-800 rounded-xl mb-3 text-xs font-mono">
            <div>SCORE: <span id="scoreVal" class="text-cyan-400 font-bold text-sm">0</span></div>
            <div>HIGH: <span id="highScoreVal" class="text-amber-400 font-bold text-sm">0</span></div>
            <div>LIVES: <span id="livesVal" class="text-rose-400 font-bold text-sm">❤️❤️❤️</span></div>
        </div>

        <div class="relative border-2 border-cyan-500/40 rounded-2xl overflow-hidden shadow-2xl shadow-cyan-500/10">
            <canvas id="gameCanvas" width="360" height="480" class="bg-[#050814] block"></canvas>
            
            <div id="gameOverlay" class="absolute inset-0 bg-black/85 backdrop-blur-sm flex flex-col items-center justify-center p-6 text-center space-y-4">
                <h1 class="text-2xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-purple-400 font-mono tracking-wider">GALAXY DEFENDER</h1>
                <p class="text-xs text-slate-300 max-w-xs">Use Left/Right keys or buttons below to dodge & shoot alien invaders!</p>
                <button onclick="startGame()" class="px-6 py-3 bg-gradient-to-r from-cyan-500 to-blue-600 rounded-xl font-bold text-sm hover:scale-105 transition-all shadow-lg shadow-cyan-500/30">
                    PLAY NOW 🚀
                </button>
            </div>
        </div>

        <div class="w-full max-w-xs grid grid-cols-3 gap-3 mt-4">
            <button id="btnLeft" class="p-4 bg-slate-900 active:bg-slate-700 border border-slate-800 rounded-xl text-xl flex items-center justify-center active:scale-95">◀</button>
            <button id="btnFire" class="p-4 bg-rose-600 active:bg-rose-500 rounded-xl font-bold text-sm flex items-center justify-center active:scale-95 shadow-lg shadow-rose-600/30">FIRE 🎯</button>
            <button id="btnRight" class="p-4 bg-slate-900 active:bg-slate-700 border border-slate-800 rounded-xl text-xl flex items-center justify-center active:scale-95">▶</button>
        </div>
    </div>
    <script src="game.js"></script>
</body>
</html>"""

        game_js = """const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
let score = 0;
let highScore = parseInt(localStorage.getItem('galaxy_high_score') || '0');
let lives = 3;
let gameOver = true;
const player = { x: 160, y: 430, w: 32, h: 32, speed: 6, dx: 0 };
let bullets = [];
let enemies = [];
let particles = [];
let lastSpawn = 0;
document.getElementById('highScoreVal').textContent = highScore;

let audioCtx = null;
function playSound(freq, type = 'sine', duration = 0.1) {
    try {
        if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = type;
        osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
        gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + duration);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + duration);
    } catch(e) {}
}

function startGame() {
    score = 0;
    lives = 3;
    bullets = [];
    enemies = [];
    particles = [];
    player.x = 160;
    gameOver = false;
    document.getElementById('gameOverlay').classList.add('hidden');
    document.getElementById('scoreVal').textContent = '0';
    document.getElementById('livesVal').textContent = '❤️❤️❤️';
    lastSpawn = performance.now();
    requestAnimationFrame(gameLoop);
}

function shoot() {
    if (gameOver) return;
    bullets.push({ x: player.x + player.w/2 - 2, y: player.y, w: 4, h: 10, speed: 8 });
    playSound(600, 'square', 0.08);
}

window.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft' || e.key === 'a') player.dx = -player.speed;
    if (e.key === 'ArrowRight' || e.key === 'd') player.dx = player.speed;
    if (e.key === ' ' || e.key === 'ArrowUp') shoot();
});
window.addEventListener('keyup', (e) => {
    if (['ArrowLeft', 'a', 'ArrowRight', 'd'].includes(e.key)) player.dx = 0;
});

const btnLeft = document.getElementById('btnLeft');
const btnRight = document.getElementById('btnRight');
const btnFire = document.getElementById('btnFire');
if (btnLeft && btnRight && btnFire) {
    btnLeft.addEventListener('touchstart', (e) => { e.preventDefault(); player.dx = -player.speed; });
    btnLeft.addEventListener('touchend', () => { player.dx = 0; });
    btnRight.addEventListener('touchstart', (e) => { e.preventDefault(); player.dx = player.speed; });
    btnRight.addEventListener('touchend', () => { player.dx = 0; });
    btnFire.addEventListener('touchstart', (e) => { e.preventDefault(); shoot(); });
    btnLeft.addEventListener('mousedown', () => { player.dx = -player.speed; });
    btnLeft.addEventListener('mouseup', () => { player.dx = 0; });
    btnRight.addEventListener('mousedown', () => { player.dx = player.speed; });
    btnRight.addEventListener('mouseup', () => { player.dx = 0; });
    btnFire.addEventListener('mousedown', () => { shoot(); });
}

function createExplosion(x, y, color = '#38bdf8') {
    for (let i = 0; i < 12; i++) {
        particles.push({
            x, y,
            vx: (Math.random() - 0.5) * 6,
            vy: (Math.random() - 0.5) * 6,
            life: 20,
            color
        });
    }
}

function gameLoop(now) {
    if (gameOver) return;
    ctx.fillStyle = '#050814';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    player.x += player.dx;
    if (player.x < 0) player.x = 0;
    if (player.x > canvas.width - player.w) player.x = canvas.width - player.w;

    ctx.fillStyle = '#38bdf8';
    ctx.beginPath();
    ctx.moveTo(player.x + player.w/2, player.y);
    ctx.lineTo(player.x + player.w, player.y + player.h);
    ctx.lineTo(player.x, player.y + player.h);
    ctx.closePath();
    ctx.fill();

    if (now - lastSpawn > 800) {
        enemies.push({
            x: Math.random() * (canvas.width - 30),
            y: -20,
            w: 24,
            h: 24,
            speed: 2 + Math.random() * 2
        });
        lastSpawn = now;
    }

    for (let i = bullets.length - 1; i >= 0; i--) {
        const b = bullets[i];
        b.y -= b.speed;
        ctx.fillStyle = '#f43f5e';
        ctx.fillRect(b.x, b.y, b.w, b.h);
        if (b.y < 0) bullets.splice(i, 1);
    }

    for (let i = enemies.length - 1; i >= 0; i--) {
        const en = enemies[i];
        en.y += en.speed;
        ctx.fillStyle = '#a855f7';
        ctx.fillRect(en.x, en.y, en.w, en.h);
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(en.x + 4, en.y + 6, 4, 4);
        ctx.fillRect(en.x + 16, en.y + 6, 4, 4);

        for (let j = bullets.length - 1; j >= 0; j--) {
            const b = bullets[j];
            if (b.x < en.x + en.w && b.x + b.w > en.x && b.y < en.y + en.h && b.y + b.h > en.y) {
                createExplosion(en.x + en.w/2, en.y + en.h/2, '#a855f7');
                playSound(300, 'sawtooth', 0.15);
                enemies.splice(i, 1);
                bullets.splice(j, 1);
                score += 10;
                document.getElementById('scoreVal').textContent = score;
                if (score > highScore) {
                    highScore = score;
                    localStorage.setItem('galaxy_high_score', highScore);
                    document.getElementById('highScoreVal').textContent = highScore;
                }
                break;
            }
        }

        if (en.y > canvas.height) {
            enemies.splice(i, 1);
            lives--;
            document.getElementById('livesVal').textContent = '❤️'.repeat(Math.max(0, lives));
            if (lives <= 0) {
                gameOver = true;
                playSound(150, 'sawtooth', 0.4);
                document.getElementById('gameOverlay').classList.remove('hidden');
                return;
            }
        }
    }

    for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        p.life--;
        ctx.fillStyle = p.color;
        ctx.fillRect(p.x, p.y, 2, 2);
        if (p.life <= 0) particles.splice(i, 1);
    }
    requestAnimationFrame(gameLoop);
}"""
        return [
            {"name": "index.html", "content": index_html, "mime": "text/html"},
            {"name": "style.css", "content": "/* Galaxy Defender styles */", "mime": "text/css"},
            {"name": "game.js", "content": game_js, "mime": "application/javascript"},
        ]

    else:
        index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{clean_title} | Portfolio</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="style.css">
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans selection:bg-cyan-500 selection:text-white">
    <nav class="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md sticky top-0 z-30 px-6 py-4 flex items-center justify-between max-w-5xl mx-auto">
        <div class="font-bold text-lg text-white flex items-center gap-2">
            <span class="w-8 h-8 rounded-lg bg-cyan-500 flex items-center justify-center text-white text-sm">⚡</span>
            <span>{clean_title}</span>
        </div>
        <div class="flex items-center gap-4 text-xs font-semibold">
            <a href="#projects" class="text-slate-300 hover:text-white transition-colors">Projects</a>
            <a href="#skills" class="text-slate-300 hover:text-white transition-colors">Skills</a>
            <a href="#contact" class="px-3.5 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-600 text-white transition-all shadow-lg shadow-cyan-500/20">Contact</a>
        </div>
    </nav>

    <header class="max-w-4xl mx-auto px-6 pt-20 pb-16 text-center space-y-6">
        <div class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 text-xs font-semibold">
            <span>🚀 Live on TeleCloud</span>
        </div>
        <h1 class="text-4xl sm:text-5xl font-extrabold text-white leading-tight tracking-tight">
            Building the Future with <span class="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 via-blue-500 to-indigo-500">Fast & Modern Code</span>
        </h1>
        <p class="text-slate-400 text-base max-w-xl mx-auto leading-relaxed">
            Full-stack developer specializing in scalable cloud storage architectures, Telegram Bots, and modern reactive web applications.
        </p>
        <div class="flex items-center justify-center gap-3 pt-2">
            <a href="#projects" class="px-6 py-3 rounded-xl bg-cyan-500 hover:bg-cyan-600 text-white font-semibold text-sm shadow-xl shadow-cyan-500/25 transition-all hover:scale-105">View My Work</a>
            <a href="#contact" class="px-6 py-3 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-200 font-semibold text-sm transition-all">Get in Touch</a>
        </div>
    </header>

    <section id="projects" class="max-w-5xl mx-auto px-6 py-12 space-y-6">
        <h2 class="text-2xl font-bold text-white">Featured Projects</h2>
        <div class="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
            <div class="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 hover:border-cyan-500/40 transition-all hover:scale-[1.02] shadow-xl space-y-3">
                <div class="text-2xl">⚡</div>
                <h3 class="font-bold text-white text-base">TeleCloud Drive</h3>
                <p class="text-xs text-slate-400">Unlimited Cloud Storage with virtual static hosting backed by Telegram MTProto.</p>
                <div class="flex gap-1.5 pt-2 flex-wrap">
                    <span class="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-cyan-400 font-mono">FastAPI</span>
                    <span class="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-cyan-400 font-mono">Telethon</span>
                </div>
            </div>

            <div class="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 hover:border-purple-500/40 transition-all hover:scale-[1.02] shadow-xl space-y-3">
                <div class="text-2xl">🤖</div>
                <h3 class="font-bold text-white text-base">AI Assistant Bot</h3>
                <p class="text-xs text-slate-400">Intelligent Telegram bot with multimodal capabilities and context caching.</p>
                <div class="flex gap-1.5 pt-2 flex-wrap">
                    <span class="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-purple-400 font-mono">Python</span>
                    <span class="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-purple-400 font-mono">Gemini API</span>
                </div>
            </div>

            <div class="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 hover:border-emerald-500/40 transition-all hover:scale-[1.02] shadow-xl space-y-3">
                <div class="text-2xl">📱</div>
                <h3 class="font-bold text-white text-base">Mini Apps Hub</h3>
                <p class="text-xs text-slate-400">Responsive Telegram WebApps ecosystem with haptic feedback and real-time sync.</p>
                <div class="flex gap-1.5 pt-2 flex-wrap">
                    <span class="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-emerald-400 font-mono">JavaScript</span>
                    <span class="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-emerald-400 font-mono">Tailwind</span>
                </div>
            </div>
        </div>
    </section>

    <footer id="contact" class="border-t border-slate-800 py-8 text-center text-xs text-slate-500">
        <p>© 2026 {clean_title}. Hosted directly from Telegram Cloud via TeleCloud.</p>
    </footer>
    <script src="script.js"></script>
</body>
</html>"""

        script_js = """console.log('Portfolio loaded successfully!');"""
        return [
            {"name": "index.html", "content": index_html, "mime": "text/html"},
            {"name": "style.css", "content": "/* Portfolio Styles */", "mime": "text/css"},
            {"name": "script.js", "content": script_js, "mime": "application/javascript"},
        ]

# ----------------- Deployments API Endpoints -----------------
@app.get("/api/deployments")
async def list_deployments():
    """List all deployed websites and mini apps"""
    deps = await database.get_all_deployments()
    custom_url = os.getenv("PUBLIC_URL") or os.getenv("WEBAPP_URL") or ""
    custom_url = custom_url.rstrip("/")
    for d in deps:
        d["live_url"] = f"/d/{d['slug']}"
        d["full_url"] = f"{custom_url}/d/{d['slug']}" if custom_url else f"/d/{d['slug']}"
    return deps

@app.post("/api/deployments")
async def create_deployment_endpoint(req: DeploymentCreate):
    """Deploy a website from an existing cloud folder"""
    folder = await database.get_folder(req.folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    dep = await database.create_deployment(req.name, req.slug, req.folder_id, req.type or "static_website")
    return {
        "success": True,
        "deployment": dep,
        "live_url": f"/d/{dep['slug']}"
    }

@app.get("/api/deployments/folder/{folder_id}")
async def get_folder_deployment(folder_id: int):
    """Check if folder is already deployed"""
    dep = await database.get_deployment_by_folder_id(folder_id)
    if not dep:
        return {"deployed": False, "deployment": None}
    return {
        "deployed": True,
        "deployment": dep,
        "live_url": f"/d/{dep['slug']}"
    }

@app.delete("/api/deployments/{dep_id}")
async def delete_deployment_endpoint(dep_id: str):
    """Unpublish / delete a deployment"""
    deleted = await database.delete_deployment(dep_id)
    return {"success": deleted}

@app.post("/api/deployments/create-starter")
async def create_starter_deployment(req: StarterDeployRequest):
    """1-Click Create & Deploy Starter Template (Mini App, Portfolio, Bio Link, Game)"""
    auth = await telegram_service.get_auth_status()
    if not auth.get("authorized"):
        raise HTTPException(status_code=401, detail="Telegram is not connected. Please connect in settings.")

    # Create folder
    folder = await database.create_folder(req.name.strip(), req.parent_id)
    folder_id = folder["id"]

    # Generate template files
    files = generate_starter_template_files(req.template_type, req.name)

    for f_item in files:
        fname = f_item["name"]
        content_bytes = f_item["content"].encode("utf-8")
        mime = f_item["mime"]

        upload_res = await telegram_service.upload_bytes(content_bytes, fname, chat_id="me")
        await database.add_file(
            name=fname,
            size=len(content_bytes),
            mime_type=mime,
            folder_id=folder_id,
            telegram_msg_id=upload_res["message_id"],
            telegram_chat_id=upload_res["chat_id"]
        )

    # Create deployment
    dep = await database.create_deployment(req.name, req.slug, folder_id, req.template_type)
    return {
        "success": True,
        "deployment": dep,
        "folder_id": folder_id,
        "live_url": f"/d/{dep['slug']}",
        "message": f"Starter template '{req.name}' created and deployed live!"
    }

@app.post("/api/deployments/from-zip")
async def deploy_from_zip(
    zip_file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    slug: Optional[str] = Form(None),
    parent_id: Optional[int] = Form(None)
):
    """Deploy website directly by uploading a ZIP archive"""
    auth = await telegram_service.get_auth_status()
    if not auth.get("authorized"):
        raise HTTPException(status_code=401, detail="Telegram is not connected. Please connect in settings.")

    content = await zip_file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        zip_buffer = io.BytesIO(content)
        with zipfile.ZipFile(zip_buffer, "r") as z:
            namelist = z.namelist()
            if not namelist:
                raise HTTPException(status_code=400, detail="ZIP archive is empty.")

            project_name = (name or Path(zip_file.filename or "my-website").stem).strip()
            folder = await database.create_folder(project_name, parent_id)
            folder_id = folder["id"]

            dir_map = {"": folder_id}

            for item in sorted(namelist):
                if item.endswith("/"):
                    parts = [p for p in item.strip("/").split("/") if p]
                    curr_parent = folder_id
                    curr_path = ""
                    for p in parts:
                        curr_path = f"{curr_path}/{p}" if curr_path else p
                        if curr_path not in dir_map:
                            sub_folder = await database.create_folder(p, curr_parent)
                            dir_map[curr_path] = sub_folder["id"]
                        curr_parent = dir_map[curr_path]

            for item in namelist:
                if item.endswith("/") or item.startswith("__MACOSX") or item.endswith(".DS_Store"):
                    continue
                file_bytes = z.read(item)
                item_path = Path(item)
                fname = item_path.name
                parent_dir_path = "/".join(item.split("/")[:-1])
                target_folder_id = dir_map.get(parent_dir_path, folder_id)

                if parent_dir_path and parent_dir_path not in dir_map:
                    parts = [p for p in parent_dir_path.split("/") if p]
                    curr_parent = folder_id
                    curr_path = ""
                    for p in parts:
                        curr_path = f"{curr_path}/{p}" if curr_path else p
                        if curr_path not in dir_map:
                            sub_folder = await database.create_folder(p, curr_parent)
                            dir_map[curr_path] = sub_folder["id"]
                        curr_parent = dir_map[curr_path]
                    target_folder_id = dir_map[parent_dir_path]

                mime_type, _ = mimetypes.guess_type(fname)
                mime_type = mime_type or "application/octet-stream"

                upload_res = await telegram_service.upload_bytes(file_bytes, fname, chat_id="me")
                await database.add_file(
                    name=fname,
                    size=len(file_bytes),
                    mime_type=mime_type,
                    folder_id=target_folder_id,
                    telegram_msg_id=upload_res["message_id"],
                    telegram_chat_id=upload_res["chat_id"]
                )

            dep_slug = slug or re.sub(r'[^a-zA-Z0-9_-]', '-', project_name.lower()).strip('-') or f"site-{secrets.token_hex(3)}"
            dep = await database.create_deployment(project_name, dep_slug, folder_id)
            return {
                "success": True,
                "deployment": dep,
                "folder_id": folder_id,
                "live_url": f"/d/{dep['slug']}",
                "message": f"Website '{project_name}' successfully deployed!"
            }
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP archive.")
    except Exception as e:
        logger.error(f"Error deploying from zip: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ----------------- Deployment Public Serving -----------------
@app.get("/d/{slug}")
@app.get("/d/{slug}/")
@app.get("/d/{slug}/{subpath:path}")
async def serve_deployed_site(slug: str, subpath: str = "", background_tasks: BackgroundTasks = None):
    """
    Serve live deployed website by custom slug (e.g. /d/my-portfolio/ or /d/my-portfolio/app.js)
    """
    dep = await database.get_deployment_by_slug(slug)
    if not dep:
        return HTMLResponse(
            status_code=404,
            content=f"""<!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>404 - Site Not Found | TeleCloud</title>
                <script src="https://cdn.tailwindcss.com"></script>
            </head>
            <body class="bg-slate-950 text-slate-100 flex items-center justify-center min-h-screen font-sans p-4">
                <div class="max-w-md w-full bg-slate-900 border border-slate-800 p-8 rounded-2xl text-center shadow-2xl">
                    <div class="w-16 h-16 bg-rose-500/10 text-rose-400 rounded-2xl flex items-center justify-center mx-auto mb-4 border border-rose-500/20 text-2xl font-bold">404</div>
                    <h1 class="text-xl font-bold text-white mb-2">Website Not Found</h1>
                    <p class="text-sm text-slate-400 mb-6">No active website deployment is mapped to slug <code class="text-cyan-400 font-mono">{slug}</code>.</p>
                    <a href="/" class="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-cyan-500 hover:bg-cyan-600 text-white font-semibold text-sm transition-all">Go to TeleCloud Drive</a>
                </div>
            </body>
            </html>"""
        )

    # Increment visitor count
    if background_tasks:
        background_tasks.add_task(database.increment_deployment_visits, slug)
    else:
        asyncio.create_task(database.increment_deployment_visits(slug))

    folder_id = dep["folder_id"]
    target_path = subpath if subpath else "index.html"
    file_data = await database.get_file_by_relative_path(folder_id, target_path)

    if not file_data and (not subpath or subpath.endswith("/")):
        file_data = await database.get_file_by_name(folder_id, "index.html")

    # SPA Fallback: if not an asset request (no extension), try index.html
    if not file_data and "." not in target_path.split("/")[-1]:
        file_data = await database.get_file_by_name(folder_id, "index.html")

    if not file_data:
        return HTMLResponse(
            status_code=404,
            content=f"""<!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <title>404 - Page Not Found</title>
                <script src="https://cdn.tailwindcss.com"></script>
            </head>
            <body class="bg-slate-950 text-slate-100 flex items-center justify-center min-h-screen font-sans p-4">
                <div class="max-w-md w-full bg-slate-900 border border-slate-800 p-8 rounded-2xl text-center shadow-2xl">
                    <h1 class="text-2xl font-bold text-white mb-2">404 Not Found</h1>
                    <p class="text-sm text-slate-400 mb-4">File <code class="text-cyan-400 font-mono">{target_path}</code> does not exist in deployment <strong>{dep['name']}</strong>.</p>
                    <a href="/d/{slug}/" class="text-xs text-cyan-400 hover:underline">Return to Home</a>
                </div>
            </body>
            </html>"""
        )

    file_size = file_data["size"]
    mime_type = file_data["mime_type"] or mimetypes.guess_type(file_data["name"])[0] or "text/html"

    if file_data["name"].endswith(".html"):
        mime_type = "text/html; charset=utf-8"
    elif file_data["name"].endswith(".css"):
        mime_type = "text/css; charset=utf-8"
    elif file_data["name"].endswith(".js"):
        mime_type = "application/javascript; charset=utf-8"
    elif file_data["name"].endswith(".json"):
        mime_type = "application/json; charset=utf-8"
    elif file_data["name"].endswith(".svg"):
        mime_type = "image/svg+xml"

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
