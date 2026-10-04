# 🚀 TeleCloud — Telegram Unlimited Cloud Drive, Bot & Web Hosting

Ek all-in-one powerful system jo **Telegram ke Saved Messages / Bot** ko unlimited cloud storage backend ki tarah use karta hai, jisme aap:
1. 📁 **Full Folder & Subfolder System** bana sakte hain, files move aur organize kar sakte hain.
2. 🤖 **Live Telegram Bot** se directly Telegram me koi bhi file bhej kar cloud me save kar sakte hain aur commands se drive control kar sakte hain.
3. 🌐 **Static Websites Host** kar sakte hain (apne folders me HTML/CSS/JS upload karke live website chalayein).
4. 📝 **Built-in Code & Text Editor** se browser me hi code aur notes edit kar sakte hain.
5. ⚡ **Remote Link & Google Drive Downloader** se direct links server se Telegram me transfer kar sakte hain bina local PC storage use kiye.
6. 📦 **Download Folder as ZIP** aur **Public Share Links** se media stream ya download kar sakte hain.

---

## ✨ Features Breakdown

### 📁 1. Modern Cloud Drive & Folder Management
- **Nested Subfolders:** Folders ke andar subfolders banayein kisi bhi depth tak.
- **Move Files & Folders:** Kisi bhi file ya folder ko dusre folder me 1-click me move karein.
- **Download Folder as ZIP:** Pure folder ko uski files aur subfolders ke sath ek single ZIP archive me download karein.
- **Drag & Drop Upload:** Apne computer se multiple files ya folders drag-drop karke direct upload karein.

---

### 🌐 2. Virtual Static Website Hosting
- Kisi bhi folder me `index.html`, `style.css`, aur `script.js` upload ya create karein.
- Woh folder automatically ek **Live Website** ban jata hai:
  - URL: `http://localhost:8000/site/<folder_id>/`
- Folder header me **🌐 Live Website** button par click karke direct browser me open karein.
- **1-Click Website Starter:** Folder me **"Host Site Here"** par click karein aur starter template ready!
- Web pages, portfolio, landing pages, aur documentation host karne ke liye best tool.

---

### 🤖 3. Telegram Bot & Mini App Integration
Jab aap apna Telegram connect karte hain (Bot Token ya Account se), bot background me active ho jata hai:
- 📤 **Send Any File to Bot:** Bot ko Telegram par koi bhi Photo, Video, Document, APK, ZIP, Audio bhejein — bot usey aapke Cloud Drive ke active folder me automatically save kar dega!
- 🌐 **Telegram Mini App (WebApp):** Bot ke `/start` message me **"Open Web Drive"** button par click karke Telegram ke andar hi poora Drive open karein.
- **Bot Commands:**
  - `/start` - Welcome card, live storage stats, aur WebApp link.
  - `/folders` - Sabhi folders ki list aur active upload folder select karein.
  - `/createfolder <name>` - Telegram se hi naya folder banayein.
  - `/files` - Folder ki files browse karein with direct stream & download links.
  - `/search <query>` - Files aur folders instantly search karein.
  - `/stats` - Total storage size aur file counts dekhein.
  - `/websites` - Sabhi hosted websites ki list aur direct links dekhein.
  - `/setfolder <id>` - Incoming files ke liye target folder set karein.
  - `/resetfolder` - Target folder ko Root par reset karein.

---

### 📝 4. Built-in Code & Text Editor
- Browser me hi `.html`, `.css`, `.js`, `.py`, `.json`, `.txt`, `.md` files create aur edit karein.
- Syntax-friendly dark theme editor.
- **Live Save:** Edit karke direct Telegram Cloud me update save karein (purani copy automatically clean ho jati hai).
- HTML files ke liye 1-click **Preview** button.

---

### ⚡ 5. Remote URL & Google Drive Downloader
- **Google Drive Downloader:** Kisi bhi public/shared Google Drive link ko paste karein, server usey direct Telegram me upload kar dega (with quota limit bypass using cookies).
- **Direct Link Downloader:** Kisi bhi direct internet link (e.g. `https://example.com/movie.mp4`, `data.zip`) ko paste karein, direct cloud me save hoga.
- **HTTP Range Resumable:** Agar network disconnect ho jaye toh resume button se wahi se continue hota hai.

---

## 🛠️ How to Setup & Run

### Method 1: 1-Click Launch (Windows)
1. Simply double-click **`start.bat`**.
2. Yeh automatically dependencies install karke browser me `http://127.0.0.1:8000` launch kar dega!

### Method 2: Linux / macOS / VPS
```bash
chmod +x start.sh
./start.sh
```

### Method 3: Docker / Docker-Compose
```bash
docker-compose up -d --build
```

---

## 🔑 Telegram API & Bot Setup Guide

### 1. Telegram API Credentials (Free):
1. Browser me **[my.telegram.org](https://my.telegram.org)** par jayein aur login karein.
2. **"API development tools"** me jakar koi bhi app create karein.
3. Apna `api_id` aur `api_hash` copy karein.

### 2. TeleCloud Settings me Connect Karein:
1. Web Drive me Settings (⚙️) icon par click karein.
2. `API ID` aur `API HASH` dalein.
3. **Option A (Personal Saved Messages):** Phone number dalein -> OTP verify karein -> Connected!
4. **Option B (Bot Token):** Telegram me `@BotFather` se bot banayein aur uska token yahan paste karein -> Connected!

---

## 📂 Project Structure

```
cloud_storage/
│
├── app.py                # FastAPI Main Server, Website Hosting & REST APIs
├── bot_service.py        # Telegram Bot Commands & Auto-Upload Event Engine
├── config.py             # App Configuration & paths
├── database.py           # SQLite Virtual Drive, Folders, Files & Paths DB
├── telegram_service.py   # Telethon MTProto 2GB Cloud Storage Engine
├── gdrive_service.py     # Resumable Remote & Google Drive Downloader
├── task_manager.py       # Live Transfer Queue & Progress tracking
│
├── static/
│   ├── index.html        # Modern Cloud Drive SPA with Code Editor & WebApp SDK
│   ├── app.js            # Frontend logic (Folder nav, Editor, Hosting, Streams)
│   ├── share.html        # Public Share & Streaming Page
│   └── style.css         # Glassmorphism & layout styles
│
├── test_app.py           # Comprehensive Backend test suite
├── Dockerfile            # Production Docker image
├── docker-compose.yml    # 1-click Docker orchestration
├── start.bat             # 1-click Windows launcher
├── start.sh              # 1-click Linux/macOS launcher
└── requirements.txt      # Python dependencies
```
