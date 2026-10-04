import aiosqlite
import secrets
import json
from typing import Optional, List, Dict, Any
from config import DB_PATH

async def init_db():
    """Initialize database tables with migrations"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                parent_id INTEGER NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (parent_id) REFERENCES folders (id) ON DELETE CASCADE
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                size INTEGER NOT NULL,
                mime_type TEXT,
                folder_id INTEGER NULL,
                telegram_msg_id INTEGER NOT NULL,
                telegram_chat_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (folder_id) REFERENCES folders (id) ON DELETE CASCADE
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Persistent tasks table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS transfer_tasks (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT,
                folder_id INTEGER NULL,
                status TEXT NOT NULL,
                progress INTEGER DEFAULT 0,
                downloaded_bytes INTEGER DEFAULT 0,
                total_bytes INTEGER DEFAULT 0,
                temp_file_path TEXT,
                cookie TEXT,
                error TEXT,
                step TEXT,
                result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Public share links table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS share_links (
                token TEXT PRIMARY KEY,
                file_id INTEGER NOT NULL,
                downloads_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (file_id) REFERENCES files (id) ON DELETE CASCADE
            )
        """)
        
        await db.commit()

# ----------------- Folders -----------------
async def create_folder(name: str, parent_id: Optional[int] = None) -> Dict[str, Any]:
    """Create a new folder"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "INSERT INTO folders (name, parent_id) VALUES (?, ?)",
            (name, parent_id)
        )
        await db.commit()
        folder_id = cursor.lastrowid
        
        async with db.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)) as cur:
            row = await cur.fetchone()
            return dict(row)

async def get_folder(folder_id: int) -> Optional[Dict[str, Any]]:
    """Get folder by ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def get_folders(parent_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """List folders under a parent directory"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if parent_id is None:
            query = "SELECT * FROM folders WHERE parent_id IS NULL ORDER BY name COLLATE NOCASE ASC"
            params = ()
        else:
            query = "SELECT * FROM folders WHERE parent_id = ? ORDER BY name COLLATE NOCASE ASC"
            params = (parent_id,)
            
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def get_folder_breadcrumbs(folder_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get breadcrumbs hierarchy up to root"""
    breadcrumbs = [{"id": None, "name": "My Cloud"}]
    if not folder_id:
        return breadcrumbs
        
    current_id = folder_id
    chain = []
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        while current_id is not None:
            async with db.execute("SELECT id, name, parent_id FROM folders WHERE id = ?", (current_id,)) as cur:
                row = await cur.fetchone()
                if not row:
                    break
                chain.append({"id": row["id"], "name": row["name"]})
                current_id = row["parent_id"]
                
    chain.reverse()
    return breadcrumbs + chain

async def rename_folder(folder_id: int, new_name: str) -> bool:
    """Rename a folder"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE folders SET name = ? WHERE id = ?", (new_name, folder_id))
        await db.commit()
        return True

async def move_folder(folder_id: int, target_parent_id: Optional[int]) -> bool:
    """Move a folder into another parent folder (preventing cycles)"""
    if target_parent_id is not None:
        if folder_id == target_parent_id:
            return False
        sub_ids = await get_all_subfolder_ids(folder_id)
        if target_parent_id in sub_ids:
            return False
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE folders SET parent_id = ? WHERE id = ?", (target_parent_id, folder_id))
        await db.commit()
        return True

async def get_folder_by_name(name: str, parent_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Find a folder by name under a specific parent"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if parent_id is None:
            query = "SELECT * FROM folders WHERE name = ? AND parent_id IS NULL LIMIT 1"
            params = (name,)
        else:
            query = "SELECT * FROM folders WHERE name = ? AND parent_id = ? LIMIT 1"
            params = (name, parent_id)
        async with db.execute(query, params) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def check_folder_has_website(folder_id: int) -> bool:
    """Check if folder contains index.html for static website hosting"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM files WHERE folder_id = ? AND lower(name) = 'index.html'",
            (folder_id,)
        ) as cur:
            count = (await cur.fetchone())[0]
            return count > 0

async def get_folders_enhanced(parent_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """List folders with website hosting availability flag"""
    folders_list = await get_folders(parent_id)
    for f in folders_list:
        f["has_website"] = await check_folder_has_website(f["id"])
    return folders_list

async def get_all_subfolder_ids(folder_id: int) -> List[int]:
    """Recursively get all descendant folder IDs"""
    sub_ids = [folder_id]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        queue = [folder_id]
        while queue:
            curr = queue.pop(0)
            async with db.execute("SELECT id FROM folders WHERE parent_id = ?", (curr,)) as cur:
                rows = await cur.fetchall()
                for r in rows:
                    sub_id = r["id"]
                    sub_ids.append(sub_id)
                    queue.append(sub_id)
    return sub_ids

async def delete_folder_recursive(folder_id: int) -> List[Dict[str, Any]]:
    """Delete a folder and all subfolders/files, returning list of deleted files for Telegram cleanup"""
    folder_ids = await get_all_subfolder_ids(folder_id)
    placeholders = ",".join("?" for _ in folder_ids)
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Get all files to be deleted
        async with db.execute(f"SELECT * FROM files WHERE folder_id IN ({placeholders})", folder_ids) as cur:
            files = [dict(r) for r in await cur.fetchall()]
            
        # Delete files from DB
        await db.execute(f"DELETE FROM files WHERE folder_id IN ({placeholders})", folder_ids)
        # Delete folders from DB
        await db.execute(f"DELETE FROM folders WHERE id IN ({placeholders})", folder_ids)
        await db.commit()
        
    return files

# ----------------- Files -----------------
async def add_file(name: str, size: int, mime_type: str, folder_id: Optional[int], telegram_msg_id: int, telegram_chat_id: str) -> Dict[str, Any]:
    """Record a new file uploaded to Telegram"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """INSERT INTO files (name, size, mime_type, folder_id, telegram_msg_id, telegram_chat_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, size, mime_type, folder_id, telegram_msg_id, str(telegram_chat_id))
        )
        await db.commit()
        file_id = cursor.lastrowid
        async with db.execute("SELECT * FROM files WHERE id = ?", (file_id,)) as cur:
            row = await cur.fetchone()
            return dict(row)

async def update_file_entry(file_id: int, name: str, size: int, mime_type: str, telegram_msg_id: int, telegram_chat_id: str) -> Optional[Dict[str, Any]]:
    """Update an existing file entry (e.g. after code editor save)"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """UPDATE files SET name = ?, size = ?, mime_type = ?, telegram_msg_id = ?, telegram_chat_id = ?
               WHERE id = ?""",
            (name, size, mime_type, telegram_msg_id, str(telegram_chat_id), file_id)
        )
        await db.commit()
        async with db.execute("SELECT * FROM files WHERE id = ?", (file_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def get_file_by_name(folder_id: Optional[int], name: str) -> Optional[Dict[str, Any]]:
    """Get single file in folder by exact name"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if folder_id is None:
            query = "SELECT * FROM files WHERE name = ? AND folder_id IS NULL LIMIT 1"
            params = (name,)
        else:
            query = "SELECT * FROM files WHERE name = ? AND folder_id = ? LIMIT 1"
            params = (name, folder_id)
        async with db.execute(query, params) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def get_file_by_relative_path(root_folder_id: int, relative_path: str) -> Optional[Dict[str, Any]]:
    """Resolve a relative URL path (e.g. 'assets/style.css' or 'index.html') inside a hosted folder tree"""
    parts = [p for p in relative_path.strip("/\\").split("/") if p and p != "."]
    if not parts:
        return await get_file_by_name(root_folder_id, "index.html")
        
    current_folder_id = root_folder_id
    # Traverse directory path parts except the final file
    for part in parts[:-1]:
        next_folder = await get_folder_by_name(part, current_folder_id)
        if not next_folder:
            return None
        current_folder_id = next_folder["id"]
        
    target_filename = parts[-1]
    return await get_file_by_name(current_folder_id, target_filename)

async def get_folder_files_recursive(folder_id: int) -> List[Dict[str, Any]]:
    """Recursively get all files under folder with their relative path inside folder"""
    all_files = []
    
    async def traverse(current_id: int, current_rel_path: str):
        # Fetch files in current_id
        folder_files = await get_files(current_id)
        for f in folder_files:
            rel = f"{current_rel_path}/{f['name']}" if current_rel_path else f['name']
            f["relative_path"] = rel
            all_files.append(f)
            
        # Fetch subfolders
        subfolders = await get_folders(current_id)
        for sf in subfolders:
            sub_path = f"{current_rel_path}/{sf['name']}" if current_rel_path else sf['name']
            await traverse(sf["id"], sub_path)
            
    await traverse(folder_id, "")
    return all_files

async def get_files(folder_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """List files in a given folder"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if folder_id is None:
            query = "SELECT * FROM files WHERE folder_id IS NULL ORDER BY created_at DESC"
            params = ()
        else:
            query = "SELECT * FROM files WHERE folder_id = ? ORDER BY created_at DESC"
            params = (folder_id,)
            
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def get_file(file_id: int) -> Optional[Dict[str, Any]]:
    """Get single file metadata by ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM files WHERE id = ?", (file_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def delete_file(file_id: int) -> Optional[Dict[str, Any]]:
    """Delete a file from DB and return its metadata for Telegram message deletion"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM files WHERE id = ?", (file_id,)) as cur:
            file_meta = await cur.fetchone()
            if not file_meta:
                return None
            file_data = dict(file_meta)
            
        await db.execute("DELETE FROM files WHERE id = ?", (file_id,))
        await db.commit()
        return file_data

async def rename_file(file_id: int, new_name: str) -> bool:
    """Rename a file in the virtual drive"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE files SET name = ? WHERE id = ?", (new_name, file_id))
        await db.commit()
        return True

async def move_file(file_id: int, target_folder_id: Optional[int]) -> bool:
    """Move a file to a new virtual folder"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE files SET folder_id = ? WHERE id = ?", (target_folder_id, file_id))
        await db.commit()
        return True

async def search_items(query: str) -> Dict[str, Any]:
    """Search for files and folders by name"""
    search_term = f"%{query}%"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM folders WHERE name LIKE ? ORDER BY name ASC", (search_term,)) as cur:
            folders = [dict(r) for r in await cur.fetchall()]
        async with db.execute("SELECT * FROM files WHERE name LIKE ? ORDER BY name ASC", (search_term,)) as cur:
            files = [dict(r) for r in await cur.fetchall()]
            
    return {"folders": folders, "files": files}

async def get_storage_stats() -> Dict[str, Any]:
    """Get total storage statistics"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*), COALESCE(SUM(size), 0) FROM files") as cur:
            file_count, total_size = await cur.fetchone()
        async with db.execute("SELECT COUNT(*) FROM folders") as cur:
            folder_count = (await cur.fetchone())[0]
            
    return {
        "file_count": file_count,
        "total_size": total_size,
        "folder_count": folder_count
    }

# ----------------- Settings -----------------
async def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get setting value from database"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else default

async def set_setting(key: str, value: str):
    """Set setting value in database"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

# ----------------- Persistent Tasks -----------------
async def save_task_db(task: Dict[str, Any]):
    """Insert or update a transfer task in database"""
    async with aiosqlite.connect(DB_PATH) as db:
        result_json = json.dumps(task.get("result")) if task.get("result") else None
        await db.execute("""
            INSERT OR REPLACE INTO transfer_tasks (
                id, type, title, url, folder_id, status, progress,
                downloaded_bytes, total_bytes, temp_file_path, cookie,
                error, step, result, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            task["id"],
            task["type"],
            task["title"],
            task.get("url") or task.get("metadata", {}).get("url"),
            task.get("folder_id") or task.get("metadata", {}).get("folder_id"),
            task["status"],
            task.get("progress", 0),
            task.get("downloaded_bytes", 0),
            task.get("total_bytes", 0),
            task.get("temp_file_path"),
            task.get("cookie") or task.get("metadata", {}).get("cookie"),
            task.get("error"),
            task.get("step"),
            result_json
        ))
        await db.commit()

async def get_all_db_tasks() -> List[Dict[str, Any]]:
    """Get all transfer tasks sorted by updated_at descending"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM transfer_tasks ORDER BY updated_at DESC") as cur:
            rows = await cur.fetchall()
            tasks = []
            for r in rows:
                t = dict(r)
                if t["result"]:
                    try:
                        t["result"] = json.loads(t["result"])
                    except Exception:
                        pass
                tasks.append(t)
            return tasks

async def get_db_task(task_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific task by ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM transfer_tasks WHERE id = ?", (task_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            t = dict(row)
            if t["result"]:
                try:
                    t["result"] = json.loads(t["result"])
                except Exception:
                    pass
            return t

async def clear_completed_db_tasks():
    """Clear completed and failed tasks from history"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM transfer_tasks WHERE status IN ('completed', 'failed')")
        await db.commit()

# ----------------- Public Share Links -----------------
async def create_or_get_share_link(file_id: int) -> Dict[str, Any]:
    """Create or return existing public share token for a file"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Check if already shared
        async with db.execute("SELECT * FROM share_links WHERE file_id = ?", (file_id,)) as cur:
            existing = await cur.fetchone()
            if existing:
                return dict(existing)
                
        # Generate new 12-char secure token
        token = secrets.token_urlsafe(9)
        await db.execute("INSERT INTO share_links (token, file_id) VALUES (?, ?)", (token, file_id))
        await db.commit()
        
        async with db.execute("SELECT * FROM share_links WHERE token = ?", (token,)) as cur:
            row = await cur.fetchone()
            return dict(row)

async def get_share_link_info(token: str) -> Optional[Dict[str, Any]]:
    """Get shared file details by share token"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT s.token, s.file_id, s.downloads_count, s.created_at as shared_at,
                   f.name, f.size, f.mime_type, f.telegram_msg_id, f.telegram_chat_id
            FROM share_links s
            JOIN files f ON s.file_id = f.id
            WHERE s.token = ?
        """
        async with db.execute(query, (token,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def increment_share_downloads(token: str):
    """Increment downloads counter for public link"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE share_links SET downloads_count = downloads_count + 1 WHERE token = ?", (token,))
        await db.commit()

async def delete_share_link(token: str) -> bool:
    """Revoke public share link"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM share_links WHERE token = ?", (token,))
        await db.commit()
        return True
