import os
import re
import time
import asyncio
import logging
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import requests
from bs4 import BeautifulSoup
import humanize

import config
import database
from telegram_service import telegram_service
from task_manager import task_manager

logger = logging.getLogger("gdrive_service")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def extract_gdrive_id(url_or_id: str) -> Optional[str]:
    """Extract Google Drive file ID from various URL formats or return raw ID"""
    url_or_id = url_or_id.strip()
    
    # Format 1: /file/d/FILE_ID/
    match = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url_or_id)
    if match:
        return match.group(1)
        
    # Format 2: ?id=FILE_ID or &id=FILE_ID
    match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url_or_id)
    if match:
        return match.group(1)
        
    # Format 3: /folders/FOLDER_ID
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", url_or_id)
    if match:
        return match.group(1)
        
    # Format 4: Raw ID string
    if re.match(r"^[a-zA-Z0-9_-]{20,}$", url_or_id):
        return url_or_id
        
    return None

def extract_filename_from_cd(content_disposition: str) -> Optional[str]:
    """Parse filename from Content-Disposition header"""
    if not content_disposition:
        return None
        
    match = re.search(r"filename\*=UTF-8''([^;\r\n]+)", content_disposition, re.IGNORECASE)
    if match:
        return urllib.parse.unquote(match.group(1).strip('"\''))
        
    match = re.search(r'filename=["\']?([^";\r\n]+)["\']?', content_disposition, re.IGNORECASE)
    if match:
        return match.group(1).strip()
        
    return None

def parse_cookie_string(cookie_str: str) -> Dict[str, str]:
    """Parse raw cookie header string into dictionary"""
    cookies = {}
    if not cookie_str:
        return cookies
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies

def download_remote_file_sync(url_or_id: str, cookie_str: Optional[str], task_id: str) -> Tuple[str, int]:
    """
    High-Speed Resumable Remote File Downloader:
    - Supports Google Drive & any direct download links
    - HTTP Range Resume support: Resumes from last byte on retry instead of starting over!
    - 1MB high throughput buffer for fast speeds
    """
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=3)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",  # Prevent gzip compression on ranged binary files for accurate offsets
        "Connection": "keep-alive"
    })
    
    if cookie_str:
        cookies_dict = parse_cookie_string(cookie_str)
        session.cookies.update(cookies_dict)

    file_id = extract_gdrive_id(url_or_id)
    html_fallback_filename = None
    response = None

    # Determine primary endpoint
    if (url_or_id.startswith("http://") or url_or_id.startswith("https://")) and ("drive.usercontent.google.com" in url_or_id or not file_id):
        primary_url = url_or_id
    elif file_id:
        primary_url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&authuser=0"
    else:
        primary_url = url_or_id

    # Step 1: Initial check & handle Virus scan forms
    task_manager.update_task(
        task_id,
        status="downloading",
        step="Connecting to server...",
        progress=5
    )
    
    try:
        response = session.get(primary_url, stream=True, timeout=30)
    except Exception as e:
        if file_id:
            primary_url = f"https://drive.google.com/uc?id={file_id}&export=download"
            response = session.get(primary_url, stream=True, timeout=30)
        else:
            raise e

    content_type = response.headers.get("content-type", "").lower()

    # Handle HTML error or confirmation form
    if "text/html" in content_type:
        html_content = response.text
        soup = BeautifulSoup(html_content, "html.parser")
        
        # 1. Check for Quota Exceeded
        caption = soup.find(class_="uc-error-caption")
        subcaption = soup.find(class_="uc-error-subcaption")
        title = soup.find("title")
        
        # 2. Check for Virus Scan Warning Form
        form = soup.find("form", id="download-form") or soup.find("form")
        if form:
            action = form.get("action") or "https://drive.usercontent.google.com/download"
            if not action.startswith("http"):
                action = urllib.parse.urljoin("https://drive.usercontent.google.com", action)
                
            params = {}
            for inp in form.find_all("input"):
                name = inp.get("name")
                val = inp.get("value")
                if name and val is not None:
                    params[name] = val
                    
            name_size_tag = soup.find(class_="uc-name-size")
            if name_size_tag:
                name_match = re.search(r"([^(]+)", name_size_tag.get_text())
                if name_match:
                    html_fallback_filename = name_match.group(1).strip()
                    
            task_manager.update_task(
                task_id,
                step="Bypassing Virus Scan warning...",
                progress=10
            )
            
            # Follow the confirmation form
            response = session.get(action, params=params, stream=True, timeout=30)
            primary_url = response.url  # Save final download URL
            
            if "text/html" in response.headers.get("content-type", "").lower():
                soup2 = BeautifulSoup(response.text, "html.parser")
                caption2 = soup2.find(class_="uc-error-caption")
                title2 = soup2.find("title")
                if caption2 or (title2 and "quota" in title2.get_text().lower()):
                    msg = caption2.get_text(strip=True) if caption2 else "Download quota exceeded."
                    raise Exception(f"Google Drive Error: {msg}\n(Bypass this by pasting your Google Cookie in Settings)")
                if title2 and "access denied" in title2.get_text().lower():
                    raise Exception("Google Drive Error: Access Denied. Make sure link is public or add Google cookies in Settings.")
                raise Exception("Google Drive returned an unexpected HTML page.")
        else:
            if caption or (title and "quota" in title.get_text().lower()):
                msg = caption.get_text(strip=True) if caption else "Download quota exceeded."
                raise Exception(f"Google Drive Error: {msg}\n(Bypass this by pasting your Google Cookie in Settings)")
            if title and "access denied" in title.get_text().lower():
                raise Exception("Google Drive Error: Access Denied. File is private.")
            if title and "not found" in title.get_text().lower():
                raise Exception("Google Drive Error: File not found.")

    # Determine target filename
    cd_header = response.headers.get("content-disposition", "")
    filename = extract_filename_from_cd(cd_header) or html_fallback_filename
    
    if not filename:
        url_path = urllib.parse.urlparse(primary_url).path
        name_candidate = os.path.basename(url_path)
        if name_candidate and "." in name_candidate:
            filename = urllib.parse.unquote(name_candidate)
        else:
            filename = f"downloaded_{file_id or task_id}"
            
    filename = re.sub(r'[\\/*?:"<>|]', "_", filename)
    target_path = os.path.join(config.TEMP_DIR, f"{task_id}_{filename}")
    
    # Check if a partially downloaded file already exists (Resume support)
    existing_bytes = 0
    if os.path.exists(target_path):
        existing_bytes = os.path.getsize(target_path)
        
    total_size = int(response.headers.get("content-length", 0))
    if existing_bytes > 0 and total_size > existing_bytes:
        # Request with Range header to resume
        task_manager.update_task(
            task_id,
            step=f"Resuming download from {humanize.naturalsize(existing_bytes)}...",
            progress=int((existing_bytes / total_size) * 30) + 15
        )
        range_headers = {"Range": f"bytes={existing_bytes}-"}
        resumed_res = session.get(response.url or primary_url, headers=range_headers, stream=True, timeout=30)
        
        if resumed_res.status_code == 206:
            response = resumed_res
            write_mode = "ab"
            downloaded_bytes = existing_bytes
        else:
            # Server didn't accept range, restart
            write_mode = "wb"
            downloaded_bytes = 0
    else:
        write_mode = "wb"
        downloaded_bytes = 0

    task_manager.update_task(
        task_id,
        title=filename,
        temp_file_path=target_path,
        total_bytes=total_size if total_size > 0 else 0,
        step=f"Downloading {filename}...",
        progress=15
    )

    start_time = time.time()
    last_update_time = start_time
    chunk_size = 1024 * 1024  # 1MB buffer for high-speed line saturation

    with open(target_path, write_mode) as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                downloaded_bytes += len(chunk)
                
                curr_time = time.time()
                if curr_time - last_update_time > 0.4:
                    last_update_time = curr_time
                    elapsed = curr_time - start_time
                    speed = (downloaded_bytes - existing_bytes) / elapsed if elapsed > 0 else 0
                    speed_str = f"{humanize.naturalsize(speed)}/s"
                    
                    if total_size > 0:
                        pct = 15 + int((downloaded_bytes / total_size) * 35)  # 15% to 50%
                        pct = min(pct, 50)
                        step_text = f"Downloading: {humanize.naturalsize(downloaded_bytes)} / {humanize.naturalsize(total_size)} ({speed_str})"
                    else:
                        pct = 35
                        step_text = f"Downloading: {humanize.naturalsize(downloaded_bytes)} ({speed_str})"
                        
                    task_manager.update_task(
                        task_id,
                        progress=pct,
                        downloaded_bytes=downloaded_bytes,
                        total_bytes=total_size,
                        step=step_text,
                        speed=speed_str
                    )

    actual_file_size = os.path.getsize(target_path)
    
    if actual_file_size < 5000:
        with open(target_path, "rb") as f:
            header_sample = f.read(500).decode("utf-8", errors="ignore").lower()
            if "<html" in header_sample or "<!doctype html" in header_sample:
                os.remove(target_path)
                raise Exception("Server returned an HTML page instead of file. (Google Drive Quota Exceeded).")

    task_manager.update_task(
        task_id,
        progress=50,
        downloaded_bytes=actual_file_size,
        total_bytes=actual_file_size,
        step=f"Download complete: {humanize.naturalsize(actual_file_size)}"
    )
    
    return target_path, actual_file_size

async def transfer_gdrive_to_telegram(
    url_or_id: str,
    folder_id: Optional[int],
    task_id: str,
    cookie_override: Optional[str] = None
):
    """
    Full Resumable Pipeline:
    1. Download from GDrive/Direct URL (resumes if previously interrupted)
    2. Upload to Telegram Saved Messages
    3. Save in SQLite virtual drive
    4. Automatically clean up local temporary file (0 PC storage clutter)
    """
    temp_file_path = None
    try:
        task_manager.update_task(
            task_id,
            status="downloading",
            step="Connecting to server...",
            progress=5
        )

        cookie_str = cookie_override or await database.get_setting("gdrive_cookie")

        # Download with HTTP Range resume support
        temp_file_path, file_size = await asyncio.to_thread(
            download_remote_file_sync,
            url_or_id,
            cookie_str,
            task_id
        )

        file_name = os.path.basename(temp_file_path)
        if file_name.startswith(f"{task_id}_"):
            clean_file_name = file_name[len(f"{task_id}_"):]
        else:
            clean_file_name = file_name

        task_manager.update_task(
            task_id,
            title=clean_file_name,
            status="uploading",
            step="Uploading to Telegram Saved Messages (2GB Cloud)...",
            progress=50
        )

        # Upload to Telegram with live progress
        def tg_progress(current, total):
            if total > 0:
                pct = 50 + int((current / total) * 45)
                pct = min(pct, 95)
                task_manager.update_task(
                    task_id,
                    progress=pct,
                    step=f"Uploading to Telegram: {humanize.naturalsize(current)} / {humanize.naturalsize(total)}"
                )

        upload_result = await telegram_service.upload_file(
            file_path=temp_file_path,
            file_name=clean_file_name,
            chat_id="me",
            progress_callback=tg_progress
        )

        # Save to virtual database
        db_file = await database.add_file(
            name=clean_file_name,
            size=file_size,
            mime_type=upload_result["mime_type"],
            folder_id=folder_id,
            telegram_msg_id=upload_result["message_id"],
            telegram_chat_id=upload_result["chat_id"]
        )

        task_manager.update_task(
            task_id,
            status="completed",
            progress=100,
            step="Saved in Telegram Cloud! (Local temp cleaned)",
            result=db_file
        )

    except Exception as e:
        logger.error(f"Transfer error for task {task_id}: {e}", exc_info=True)
        task_manager.update_task(
            task_id,
            status="failed",
            error=str(e),
            step=f"Failed: {str(e)}"
        )
    finally:
        # STRICT CLEANUP: Delete temporary file on PC once uploaded to Telegram Cloud!
        task = task_manager.get_task(task_id)
        if task and task.get("status") == "completed":
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                    logger.info(f"Cleaned temp file: {temp_file_path}")
                except Exception as e:
                    logger.error(f"Error removing temp file {temp_file_path}: {e}")
