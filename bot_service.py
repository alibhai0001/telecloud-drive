import os
import io
import asyncio
import logging
import mimetypes
from typing import Optional, Dict, Any, List
import humanize
from telethon import events, Button
from telethon.tl.types import DocumentAttributeFilename

import config
import database
from telegram_service import telegram_service

logger = logging.getLogger("bot_service")
logging.basicConfig(level=logging.INFO)

class BotService:
    def __init__(self):
        self.handlers_registered = False
        self.user_active_folders: Dict[int, Optional[int]] = {}  # telegram_user_id -> folder_id
        self._running_task = None

    def get_web_url(self) -> str:
        """Get accessible Web Drive URL"""
        custom_url = os.getenv("PUBLIC_URL") or os.getenv("WEBAPP_URL")
        if custom_url:
            return custom_url.rstrip("/")
        return f"http://{config.HOST}:{config.PORT}"

    async def start(self):
        """Initialize bot event listeners on Telethon client"""
        client = await telegram_service.get_client()
        if not client:
            logger.info("Telegram client not available yet for BotService")
            return

        if self.handlers_registered:
            return

        try:
            self._register_handlers(client)
            self.handlers_registered = True
            logger.info("🤖 Telegram Bot Service event handlers registered successfully!")
        except Exception as e:
            logger.error(f"Failed to register bot handlers: {e}")

    def _register_handlers(self, client):
        """Register all command and file upload event handlers"""

        # Command: /start
        @client.on(events.NewMessage(pattern=r"^/start"))
        async def handle_start(event):
            sender = await event.get_sender()
            sender_id = sender.id if sender else event.chat_id
            name = getattr(sender, "first_name", "Friend") or "Friend"
            web_url = self.get_web_url()
            
            stats = await database.get_storage_stats()
            stats_size = humanize.naturalsize(stats["total_size"])
            
            active_folder_id = self.user_active_folders.get(sender_id)
            active_folder_name = "Root (My Cloud)"
            if active_folder_id:
                folder_obj = await database.get_folder(active_folder_id)
                if folder_obj:
                    active_folder_name = folder_obj["name"]

            welcome_text = (
                f"👋 **Namaste {name}! Welcome to TeleCloud Drive** 🚀\n\n"
                f"Aapka **Unlimited Telegram Cloud Storage** active hai!\n\n"
                f"📊 **Current Stats:**\n"
                f"• 📁 **Folders:** {stats['folder_count']}\n"
                f"• 📄 **Total Files:** {stats['file_count']}\n"
                f"• 💾 **Storage Used:** {stats_size} (Unlimited ♾️)\n"
                f"• 🎯 **Active Target Folder:** `{active_folder_name}`\n\n"
                f"✨ **Aap kya kar sakte hain:**\n"
                f"1️⃣ **Direct File Upload:** Koi bhi Video, Photo, Audio, PDF, APK ya ZIP yahan bhej dein — woh auto-save ho jayegi.\n"
                f"2️⃣ **Web Dashboard:** Full Google Drive style web UI me files manage karein.\n"
                f"3️⃣ **Website Hosting:** Folders me HTML sites upload karke live host karein.\n\n"
                f"👇 Niche diye buttons use karein:"
            )

            # Check if web_url is HTTPS for Telegram WebApp button
            is_https = web_url.startswith("https://")
            buttons = []
            if is_https:
                buttons.append([Button.url("🌐 Open Web Drive (Mini App)", web_url)])
            else:
                buttons.append([Button.url("🌐 Open Web Dashboard", web_url)])
                
            buttons.append([
                Button.inline("📁 Browse Folders", b"action:folders"),
                Button.inline("📊 Storage Stats", b"action:stats")
            ])
            buttons.append([
                Button.inline("🌐 Hosted Websites", b"action:websites"),
                Button.inline("❓ Help Guide", b"action:help")
            ])

            await event.respond(welcome_text, buttons=buttons)

        # Command: /help
        @client.on(events.NewMessage(pattern=r"^/help"))
        async def handle_help(event):
            help_text = (
                "📖 **TeleCloud Bot Command Guide**\n\n"
                "• 📤 **Send any file/media:** Bot usey seedha Cloud Storage me save karega.\n"
                "• `/folders` - Sabhi folders dekhein aur upload destination set karein.\n"
                "• `/createfolder <name>` - Naya folder banayein (e.g. `/createfolder Movies`).\n"
                "• `/files` - Active folder ki files list karein.\n"
                "• `/search <query>` - Files search karein (e.g. `/search video.mp4`).\n"
                "• `/deploy <folder_id_or_name> [slug]` - 🚀 Kisi folder ko instantly live website bana kar deploy karein!\n"
                "• `/deployments` ya `/sites` - Sabhi live deployed websites aur Mini-Apps ki list dekhein.\n"
                "• `/undeploy <slug>` - Website deployment ko unpublish / delete karein.\n"
                "• `/stats` - Total storage & file count dekhein.\n"
                "• `/setfolder <id>` - Target folder set karein jisme nayi files aayengi.\n"
                "• `/resetfolder` - Target folder ko Root par reset karein."
            )
            await event.respond(help_text)

        # Command: /folders
        @client.on(events.NewMessage(pattern=r"^/folders"))
        async def handle_folders_cmd(event):
            await self._send_folders_list(event)

        # Command: /createfolder <name>
        @client.on(events.NewMessage(pattern=r"^/createfolder(?:\s+(.+))?"))
        async def handle_create_folder_cmd(event):
            folder_name = event.pattern_match.group(1)
            if not folder_name or not folder_name.strip():
                await event.respond("⚠️ Please provide a folder name:\nExample: `/createfolder Documents`")
                return

            folder_name = folder_name.strip()
            sender = await event.get_sender()
            sender_id = sender.id if sender else event.chat_id
            parent_id = self.user_active_folders.get(sender_id)

            new_folder = await database.create_folder(folder_name, parent_id)
            self.user_active_folders[sender_id] = new_folder["id"]

            await event.respond(
                f"✅ **Folder Created Successfully!**\n\n"
                f"📁 **Name:** `{new_folder['name']}`\n"
                f"🆔 **Folder ID:** `{new_folder['id']}`\n"
                f"🎯 **Active Target Folder set to:** `{new_folder['name']}`\n\n"
                f"Ab jo bhi file bhejenge woh is folder me store hogi."
            )

        # Command: /setfolder <id>
        @client.on(events.NewMessage(pattern=r"^/setfolder(?:\s+(\d+))?"))
        async def handle_set_folder_cmd(event):
            folder_id_str = event.pattern_match.group(1)
            sender = await event.get_sender()
            sender_id = sender.id if sender else event.chat_id
            
            if not folder_id_str:
                await event.respond("⚠️ Please provide a valid Folder ID.\nExample: `/setfolder 1`\n\nUse `/folders` to see all IDs.")
                return

            folder_id = int(folder_id_str)
            folder = await database.get_folder(folder_id)
            if not folder:
                await event.respond(f"❌ Folder with ID `{folder_id}` not found.")
                return

            self.user_active_folders[sender_id] = folder_id
            await event.respond(f"🎯 Target upload folder set to: 📁 **{folder['name']}** (ID: {folder['id']})")

        # Command: /resetfolder
        @client.on(events.NewMessage(pattern=r"^/resetfolder"))
        async def handle_reset_folder_cmd(event):
            sender = await event.get_sender()
            sender_id = sender.id if sender else event.chat_id
            self.user_active_folders[sender_id] = None
            await event.respond("🎯 Target folder reset to: 📁 **Root (My Cloud)**")

        # Command: /stats
        @client.on(events.NewMessage(pattern=r"^/stats"))
        async def handle_stats_cmd(event):
            stats = await database.get_storage_stats()
            stats_size = humanize.naturalsize(stats["total_size"])
            text = (
                "📊 **TeleCloud Storage Statistics**\n\n"
                f"📁 **Total Folders:** {stats['folder_count']}\n"
                f"📄 **Total Files:** {stats['file_count']}\n"
                f"💾 **Storage Consumed:** {stats_size}\n"
                f"⚡ **Cloud Backend:** Unlimited Telegram MTProto\n"
                f"🚀 **Status:** Online & Ready"
            )
            await event.respond(text)

        # Command: /search <query>
        @client.on(events.NewMessage(pattern=r"^/search(?:\s+(.+))?"))
        async def handle_search_cmd(event):
            query = event.pattern_match.group(1)
            if not query or not query.strip():
                await event.respond("⚠️ Please enter a search query.\nExample: `/search resume`")
                return

            query = query.strip()
            res = await database.search_items(query)
            found_folders = res["folders"]
            found_files = res["files"]

            if not found_folders and not found_files:
                await event.respond(f"🔍 No items found matching: `{query}`")
                return

            text_parts = [f"🔍 **Search Results for:** `{query}`\n"]
            if found_folders:
                text_parts.append("📁 **Folders:**")
                for f in found_folders[:10]:
                    text_parts.append(f"• `{f['name']}` (ID: {f['id']})")
                text_parts.append("")

            if found_files:
                web_url = self.get_web_url()
                text_parts.append("📄 **Files:**")
                for f in found_files[:15]:
                    size_str = humanize.naturalsize(f["size"])
                    link = f"{web_url}/api/download/{f['id']}"
                    text_parts.append(f"• [{f['name']}]({link}) ({size_str})")

            await event.respond("\n".join(text_parts))

        # Command: /files or /list
        @client.on(events.NewMessage(pattern=r"^/(?:files|list)(?:\s+(\d+))?"))
        async def handle_files_cmd(event):
            folder_id_str = event.pattern_match.group(1)
            sender = await event.get_sender()
            sender_id = sender.id if sender else event.chat_id
            
            target_folder_id = int(folder_id_str) if folder_id_str else self.user_active_folders.get(sender_id)
            
            folder_name = "Root (My Cloud)"
            if target_folder_id:
                folder_obj = await database.get_folder(target_folder_id)
                if folder_obj:
                    folder_name = folder_obj["name"]

            files_list = await database.get_files(target_folder_id)
            if not files_list:
                await event.respond(f"📁 Folder **{folder_name}** is empty.\nSend any file here to upload!")
                return

            web_url = self.get_web_url()
            msg_parts = [f"📂 **Files in {folder_name} ({len(files_list)} items):**\n"]
            for f in files_list[:20]:
                size_str = humanize.naturalsize(f["size"])
                dl_url = f"{web_url}/api/download/{f['id']}"
                msg_parts.append(f"• [{f['name']}]({dl_url}) — `{size_str}`")

            if len(files_list) > 20:
                msg_parts.append(f"\n_...and {len(files_list) - 20} more files. View all in Web Drive._")

            buttons = [[Button.url("🌐 Open in Web Drive", web_url)]]
            await event.respond("\n".join(msg_parts), buttons=buttons)

        # Command: /deploy <folder_id_or_name> [slug]
        @client.on(events.NewMessage(pattern=r"^/deploy(?:\s+(\S+))?(?:\s+(\S+))?"))
        async def handle_deploy_cmd(event):
            target = event.pattern_match.group(1)
            custom_slug = event.pattern_match.group(2)
            web_url = self.get_web_url()

            if not target:
                await event.respond(
                    "⚠️ **Usage:** `/deploy <folder_id_or_name> [slug]`\n\n"
                    "**Examples:**\n"
                    "• `/deploy 1 my-portfolio`\n"
                    "• `/deploy Website`\n\n"
                    "Use `/folders` to see all your folders."
                )
                return

            target = target.strip()
            folder = None
            if target.isdigit():
                folder = await database.get_folder(int(target))
            
            if not folder:
                all_f = await database.get_folders()
                for f in all_f:
                    if f["name"].lower() == target.lower():
                        folder = f
                        break

            if not folder:
                await event.respond(f"❌ Folder `{target}` not found. Check `/folders`.")
                return

            slug = custom_slug or folder["name"]
            dep = await database.create_deployment(name=folder["name"], slug=slug, folder_id=folder["id"])
            live_url = f"{web_url}/d/{dep['slug']}"

            buttons = [
                [Button.url("🌐 Open Live Website", live_url)],
                [Button.url("📂 Manage in Drive", web_url)]
            ]

            msg = (
                f"🚀 **Website Deployed Successfully!**\n\n"
                f"✨ **Name:** `{dep['name']}`\n"
                f"📁 **Folder:** `{folder['name']}`\n"
                f"🔗 **Live URL:** {live_url}\n"
                f"🌐 **Slug:** `/d/{dep['slug']}`\n\n"
                f"Folder me koi bhi file edit ya upload karne par live site instantly update ho jayegi!"
            )
            await event.respond(msg, buttons=buttons)

        # Command: /deployments or /sites
        @client.on(events.NewMessage(pattern=r"^/(?:deployments|sites)"))
        async def handle_deployments_list_cmd(event):
            deps = await database.get_all_deployments()
            web_url = self.get_web_url()

            if not deps:
                await event.respond(
                    "🚀 **No Active Deployments Found**\n\n"
                    "Aap kisi bhi folder ko deploy kar sakte hain:\n"
                    "Command: `/deploy <folder_name_or_id> [slug]`"
                )
                return

            text_parts = ["🚀 **Active TeleCloud Deployments & Sites:**\n"]
            buttons = []
            for d in deps:
                live_url = f"{web_url}/d/{d['slug']}"
                text_parts.append(
                    f"• 🌐 **{d['name']}**\n"
                    f"  🔗 URL: {live_url}\n"
                    f"  📁 Folder: `{d.get('folder_name', 'Unknown')}` | 👁️ Visits: `{d.get('visits_count', 0)}`\n"
                )
                if len(buttons) < 4:
                    buttons.append([Button.url(f"🌐 Open {d['name']}", live_url)])

            await event.respond("\n".join(text_parts), buttons=buttons if buttons else None)

        # Command: /undeploy <slug>
        @client.on(events.NewMessage(pattern=r"^/undeploy(?:\s+(\S+))?"))
        async def handle_undeploy_cmd(event):
            slug = event.pattern_match.group(1)
            if not slug:
                await event.respond("⚠️ **Usage:** `/undeploy <slug>`\nExample: `/undeploy my-portfolio`")
                return

            dep = await database.get_deployment_by_slug(slug.strip())
            if not dep:
                await event.respond(f"❌ No deployment found with slug `{slug}`.")
                return

            await database.delete_deployment(dep["id"])
            await event.respond(f"✅ Deployment `{dep['name']}` (`/d/{dep['slug']}`) has been removed/unassigned.")

        # Command: /websites
        @client.on(events.NewMessage(pattern=r"^/websites"))
        async def handle_websites_cmd(event):
            all_folders = await database.get_folders()
            web_url = self.get_web_url()
            hosted_sites = []
            
            for f in all_folders:
                has_web = await database.check_folder_has_website(f["id"])
                if has_web:
                    site_url = f"{web_url}/site/{f['id']}/"
                    hosted_sites.append(f"• 🌐 **{f['name']}**: [Open Website]({site_url})")

            if not hosted_sites:
                await event.respond(
                    "🌐 **No Hosted Websites Yet**\n\n"
                    "Aap kisi bhi folder me `index.html` file upload ya create karein, ya `/deploy <folder>` command use karein!"
                )
                return

            text = "🌐 **Live Hosted Websites from Storage:**\n\n" + "\n".join(hosted_sites)
            await event.respond(text)

        # Callback Queries Handler (Inline Buttons)
        @client.on(events.CallbackQuery())
        async def handle_callback_query(event):
            data = event.data.decode("utf-8")
            sender = await event.get_sender()
            sender_id = sender.id if sender else event.chat_id

            if data == "action:folders":
                await self._send_folders_list(event, is_callback=True)
            elif data == "action:stats":
                stats = await database.get_storage_stats()
                stats_size = humanize.naturalsize(stats["total_size"])
                text = (
                    "📊 **TeleCloud Storage Statistics**\n\n"
                    f"📁 **Total Folders:** {stats['folder_count']}\n"
                    f"📄 **Total Files:** {stats['file_count']}\n"
                    f"💾 **Storage Used:** {stats_size}\n"
                    f"⚡ **Backend:** Unlimited Telegram MTProto"
                )
                await event.answer()
                await event.respond(text)
            elif data == "action:websites":
                all_folders = await database.get_folders()
                web_url = self.get_web_url()
                hosted_sites = []
                for f in all_folders:
                    if await database.check_folder_has_website(f["id"]):
                        hosted_sites.append(f"• 🌐 **{f['name']}**: [Open Site]({web_url}/site/{f['id']}/)")
                await event.answer()
                if hosted_sites:
                    await event.respond("🌐 **Live Hosted Websites:**\n\n" + "\n".join(hosted_sites))
                else:
                    await event.respond("🌐 No websites hosted yet. Upload `index.html` to any folder to host it!")
            elif data == "action:help":
                await event.answer()
                await event.respond(
                    "📖 **Quick Help:**\n\n"
                    "• Send any Document/Video/Audio/Photo to save.\n"
                    "• Use `/createfolder <name>` to make a folder.\n"
                    "• Use `/folders` to change active folder.\n"
                    "• Use `/files` to list your files."
                )
            elif data.startswith("setfolder:"):
                f_id = int(data.split(":")[1])
                folder = await database.get_folder(f_id)
                if folder:
                    self.user_active_folders[sender_id] = f_id
                    await event.answer(f"Target folder set to: {folder['name']}")
                    await event.respond(f"🎯 Target upload folder set to: 📁 **{folder['name']}**")
                else:
                    await event.answer("Folder not found", alert=True)

        # File Upload Handler: ANY Document, Photo, Video, Audio sent to the bot
        @client.on(events.NewMessage())
        async def handle_incoming_file(event):
            # Ignore bot command text messages
            if event.raw_text and event.raw_text.startswith("/"):
                return

            # Check if message has media/document/photo/video/audio
            if not event.media:
                return

            sender = await event.get_sender()
            sender_id = sender.id if sender else event.chat_id
            target_folder_id = self.user_active_folders.get(sender_id)

            folder_name = "Root (My Cloud)"
            if target_folder_id:
                folder_obj = await database.get_folder(target_folder_id)
                if folder_obj:
                    folder_name = folder_obj["name"]

            # Extract file name and size
            file_name = "telegram_file"
            mime_type = "application/octet-stream"
            file_size = 0

            if event.file:
                file_name = event.file.name or f"telegram_file_{event.id}"
                mime_type = event.file.mime_type or mime_type
                file_size = event.file.size or 0
            elif event.photo:
                file_name = f"photo_{event.id}.jpg"
                mime_type = "image/jpeg"
                file_size = 500000
            elif event.video:
                file_name = f"video_{event.id}.mp4"
                mime_type = "video/mp4"
                file_size = 1000000

            chat_id = str(event.chat_id)
            msg_id = event.id

            try:
                # Save into database
                db_file = await database.add_file(
                    name=file_name,
                    size=file_size,
                    mime_type=mime_type,
                    folder_id=target_folder_id,
                    telegram_msg_id=msg_id,
                    telegram_chat_id=chat_id
                )

                web_url = self.get_web_url()
                dl_link = f"{web_url}/api/download/{db_file['id']}"
                stream_link = f"{web_url}/api/stream/{db_file['id']}"
                size_str = humanize.naturalsize(file_size) if file_size > 0 else "Unknown"

                buttons = [
                    [
                        Button.url("📥 Direct Download", dl_link),
                        Button.url("▶️ Stream", stream_link)
                    ],
                    [Button.url("🌐 Open Web Drive", web_url)]
                ]

                reply_msg = (
                    f"✅ **File Saved to Telegram Cloud Storage!**\n\n"
                    f"📄 **Name:** `{file_name}`\n"
                    f"📊 **Size:** `{size_str}`\n"
                    f"📁 **Folder:** `{folder_name}`\n"
                    f"💾 **File ID:** `{db_file['id']}`\n\n"
                    f"Aap ise Web UI me access ya stream kar sakte hain."
                )

                await event.reply(reply_msg, buttons=buttons)
                logger.info(f"Saved incoming Telegram file: {file_name} in folder {folder_name}")

            except Exception as e:
                logger.error(f"Error saving incoming Telegram file: {e}", exc_info=True)
                await event.reply(f"❌ Error saving file to Cloud database: {str(e)}")

    async def _send_folders_list(self, event, is_callback=False):
        """Helper to list all folders with quick select buttons"""
        folders_list = await database.get_folders()
        if not folders_list:
            text = "📁 **No folders created yet.**\nUse `/createfolder <name>` to create your first folder!"
            if is_callback:
                await event.answer()
                await event.respond(text)
            else:
                await event.respond(text)
            return

        text = "📁 **Select Active Upload Folder:**\nClick any folder below to make it the default destination for new files:\n"
        buttons = []
        row = []
        for f in folders_list:
            btn = Button.inline(f"📁 {f['name']}", f"setfolder:{f['id']}".encode("utf-8"))
            row.append(btn)
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        if is_callback:
            await event.answer()
            await event.respond(text, buttons=buttons)
        else:
            await event.respond(text, buttons=buttons)

# Global instance
bot_service = BotService()
