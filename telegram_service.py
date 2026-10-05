import os
import re
import secrets
import asyncio
import logging
import mimetypes
from pathlib import Path
from typing import Optional, Dict, Any, AsyncGenerator, Callable
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeFilename, DocumentAttributeVideo, DocumentAttributeAudio
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError
)

import config
import database

logger = logging.getLogger("telegram_service")
logging.basicConfig(level=logging.INFO)

class TelegramService:
    def __init__(self):
        self.client: Optional[TelegramClient] = None
        self._lock = asyncio.Lock()
        self.phone_code_hash_cache: Dict[str, str] = {}
        self.current_user: Optional[Dict[str, Any]] = None
        
    async def get_client(self, api_id: Optional[str] = None, api_hash: Optional[str] = None) -> Optional[TelegramClient]:
        """Initialize or return current Telethon client with persistent StringSession support"""
        async with self._lock:
            eff_api_id = api_id or await database.get_setting("api_id") or config.API_ID
            eff_api_hash = api_hash or await database.get_setting("api_hash") or config.API_HASH
            
            if not eff_api_id or not eff_api_hash:
                return None
                
            try:
                eff_api_id_int = int(eff_api_id)
            except ValueError:
                return None
                
            if self.client is None or not self.client.is_connected():
                eff_session_str = await database.get_setting("session_string") or os.getenv("TELEGRAM_SESSION_STRING", "")
                
                if eff_session_str:
                    self.client = TelegramClient(StringSession(eff_session_str), eff_api_id_int, eff_api_hash)
                else:
                    session_file = str(config.DATA_DIR / "tg_cloud_session")
                    self.client = TelegramClient(session_file, eff_api_id_int, eff_api_hash)
                    
                await self.client.connect()
                
            return self.client

    async def get_auth_status(self) -> Dict[str, Any]:
        """Check if client is connected and authorized"""
        api_id = await database.get_setting("api_id") or config.API_ID
        api_hash = await database.get_setting("api_hash") or config.API_HASH
        
        if not api_id or not api_hash:
            return {
                "configured": False,
                "authorized": False,
                "user": None,
                "message": "API_ID and API_HASH not configured"
            }
            
        try:
            client = await self.get_client()
            if client and await client.is_user_authorized():
                me = await client.get_me()
                user_info = {
                    "id": me.id,
                    "first_name": me.first_name,
                    "last_name": me.last_name or "",
                    "username": me.username or "",
                    "phone": me.phone or "",
                    "is_bot": me.bot
                }
                self.current_user = user_info
                return {
                    "configured": True,
                    "authorized": True,
                    "user": user_info,
                    "message": "Connected to Telegram"
                }
            else:
                return {
                    "configured": True,
                    "authorized": False,
                    "user": None,
                    "message": "API credentials set, login required"
                }
        except Exception as e:
            logger.error(f"Error checking auth status: {e}")
            return {
                "configured": True,
                "authorized": False,
                "user": None,
                "error": str(e),
                "message": "Connection error"
            }

    async def send_phone_code(self, api_id: str, api_hash: str, phone: str) -> Dict[str, Any]:
        """Send verification code to Telegram phone number"""
        try:
            # Save API credentials
            await database.set_setting("api_id", api_id)
            await database.set_setting("api_hash", api_hash)
            config.update_env_file("TELEGRAM_API_ID", api_id)
            config.update_env_file("TELEGRAM_API_HASH", api_hash)
            
            client = await self.get_client(api_id, api_hash)
            if not client:
                return {"success": False, "error": "Could not initialize Telegram client"}
                
            res = await client.send_code_request(phone)
            self.phone_code_hash_cache[phone] = res.phone_code_hash
            return {
                "success": True,
                "phone_code_hash": res.phone_code_hash,
                "message": f"Verification code sent to {phone}"
            }
        except Exception as e:
            logger.error(f"Error sending code: {e}")
            return {"success": False, "error": str(e)}

    async def sign_in_with_code(self, phone: str, code: str, phone_code_hash: Optional[str] = None, password: Optional[str] = None) -> Dict[str, Any]:
        """Complete phone login with OTP and optional 2FA password"""
        try:
            client = await self.get_client()
            if not client:
                return {"success": False, "error": "Telegram client not ready"}
                
            code_hash = phone_code_hash or self.phone_code_hash_cache.get(phone)
            if not code_hash:
                return {"success": False, "error": "Missing phone code hash. Please request code again."}
                
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
            except SessionPasswordNeededError:
                if not password:
                    return {
                        "success": False,
                        "requires_password": True,
                        "message": "2-Step Verification Password required"
                    }
                await client.sign_in(password=password)
            except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
                return {"success": False, "error": f"Invalid or expired code: {e}"}
            except PasswordHashInvalidError:
                return {"success": False, "requires_password": True, "error": "Invalid 2FA password"}
                
            me = await client.get_me()
            
            # Save persistent StringSession
            try:
                session_str = client.session.save()
                if session_str:
                    await database.set_setting("session_string", session_str)
                    config.update_env_file("TELEGRAM_SESSION_STRING", session_str)
            except Exception as e:
                logger.warning(f"Could not save StringSession: {e}")

            return {
                "success": True,
                "user": {
                    "id": me.id,
                    "first_name": me.first_name,
                    "phone": me.phone
                }
            }
        except Exception as e:
            logger.error(f"Error during sign in: {e}")
            return {"success": False, "error": str(e)}

    async def sign_in_bot(self, api_id: str, api_hash: str, bot_token: str) -> Dict[str, Any]:
        """Sign in using a Telegram Bot Token"""
        try:
            await database.set_setting("api_id", api_id)
            await database.set_setting("api_hash", api_hash)
            await database.set_setting("bot_token", bot_token)
            config.update_env_file("TELEGRAM_API_ID", api_id)
            config.update_env_file("TELEGRAM_API_HASH", api_hash)
            config.update_env_file("TELEGRAM_BOT_TOKEN", bot_token)
            
            client = await self.get_client(api_id, api_hash)
            if not client:
                return {"success": False, "error": "Could not initialize client"}
                
            await client.start(bot_token=bot_token)
            me = await client.get_me()

            # Save persistent StringSession
            try:
                session_str = client.session.save()
                if session_str:
                    await database.set_setting("session_string", session_str)
                    config.update_env_file("TELEGRAM_SESSION_STRING", session_str)
            except Exception as e:
                logger.warning(f"Could not save StringSession: {e}")

            return {
                "success": True,
                "user": {
                    "id": me.id,
                    "first_name": me.first_name,
                    "username": me.username,
                    "is_bot": True
                }
            }
        except Exception as e:
            logger.error(f"Error bot login: {e}")
            return {"success": False, "error": str(e)}

    async def logout(self) -> bool:
        """Logout and disconnect session"""
        try:
            if self.client and self.client.is_connected():
                await self.client.log_out()
                self.client = None
            session_file = config.DATA_DIR / "tg_cloud_session.session"
            if session_file.exists():
                session_file.unlink()
            await database.set_setting("session_string", "")
            config.update_env_file("TELEGRAM_SESSION_STRING", "")
            return True
        except Exception as e:
            logger.error(f"Error logging out: {e}")
            return False

    async def upload_file(
        self,
        file_path: str,
        file_name: Optional[str] = None,
        chat_id: str = "me",
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Dict[str, Any]:
        """
        Upload file to Telegram Saved Messages ('me') or target chat.
        Supports up to 2GB per file.
        """
        client = await self.get_client()
        if not client or not await client.is_user_authorized():
            raise Exception("Telegram client is not authorized. Please connect Telegram in settings.")
            
        p = Path(file_path)
        actual_name = file_name or p.name
        mime_type, _ = mimetypes.guess_type(actual_name)
        mime_type = mime_type or "application/octet-stream"
        file_size = p.stat().st_size
        
        attributes = [DocumentAttributeFilename(file_name=actual_name)]
        
        # Add caption with file details
        caption = f"📁 **{actual_name}**\n📊 Size: {file_size / (1024*1024):.2f} MB\n💾 Cloud Storage Backup"
        
        target = "me" if chat_id == "me" else int(chat_id)
        
        msg = await client.send_file(
            target,
            file=file_path,
            caption=caption,
            force_document=True,
            attributes=attributes,
            progress_callback=progress_callback
        )
        
        return {
            "message_id": msg.id,
            "chat_id": str(target),
            "file_name": actual_name,
            "size": file_size,
            "mime_type": mime_type
        }

    async def get_message(self, message_id: int, chat_id: str = "me"):
        """Get Telegram message object containing the document"""
        client = await self.get_client()
        if not client or not await client.is_user_authorized():
            raise Exception("Telegram client is not authorized")
            
        target = "me" if chat_id == "me" else int(chat_id)
        msg = await client.get_messages(target, ids=message_id)
        return msg

    async def stream_file(
        self,
        message_id: int,
        chat_id: str = "me",
        offset: int = 0,
        length: Optional[int] = None,
        chunk_size: int = 256 * 1024
    ) -> AsyncGenerator[bytes, None]:
        """
        Stream file content directly from Telegram MTProto servers chunk by chunk.
        Supports range offsets for seeking media and resuming downloads.
        """
        client = await self.get_client()
        if not client:
            return
            
        target = "me" if chat_id == "me" else int(chat_id)
        msg = await client.get_messages(target, ids=message_id)
        if not msg or not msg.media:
            return

        # Use Telethon iter_download with offset and request_size
        bytes_sent = 0
        async for chunk in client.iter_download(
            msg.media,
            offset=offset,
            request_size=chunk_size
        ):
            if length is not None and bytes_sent + len(chunk) > length:
                yield chunk[:length - bytes_sent]
                break
            yield chunk
            bytes_sent += len(chunk)
            if length is not None and bytes_sent >= length:
                break

    async def download_file_bytes(self, message_id: int, chat_id: str = "me") -> Optional[bytes]:
        """Download entire file content as in-memory bytes"""
        chunks = []
        async for chunk in self.stream_file(message_id, chat_id=chat_id):
            chunks.append(chunk)
        return b"".join(chunks) if chunks else None

    async def upload_bytes(
        self,
        data: bytes,
        file_name: str,
        chat_id: str = "me"
    ) -> Dict[str, Any]:
        """Upload in-memory bytes directly to Telegram"""
        client = await self.get_client()
        if not client or not await client.is_user_authorized():
            raise Exception("Telegram client is not authorized")

        mime_type, _ = mimetypes.guess_type(file_name)
        mime_type = mime_type or "application/octet-stream"
        file_size = len(data)

        # Write to temporary file for reliable MTProto multipart upload
        safe_base = re.sub(r'[\\/*?:<>|]', '_', Path(file_name).name)
        temp_path = config.TEMP_DIR / f"mem_{secrets.token_hex(4)}_{safe_base}"
        try:
            with open(temp_path, "wb") as f:
                f.write(data)

            attributes = [DocumentAttributeFilename(file_name=file_name)]
            caption = f"📁 **{file_name}**\n📊 Size: {file_size / (1024*1024):.2f} MB\n💾 Cloud Storage Backup"
            target = "me" if chat_id == "me" else int(chat_id)

            msg = await client.send_file(
                target,
                file=str(temp_path),
                caption=caption,
                force_document=True,
                attributes=attributes
            )

            return {
                "message_id": msg.id,
                "chat_id": str(target),
                "file_name": file_name,
                "size": file_size,
                "mime_type": mime_type
            }
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    async def delete_message(self, message_id: int, chat_id: str = "me") -> bool:
        """Delete message from Telegram chat"""
        try:
            client = await self.get_client()
            if not client:
                return False
            target = "me" if chat_id == "me" else int(chat_id)
            await client.delete_messages(target, [message_id])
            return True
        except Exception as e:
            logger.error(f"Error deleting telegram message: {e}")
            return False

# Global instance
telegram_service = TelegramService()
