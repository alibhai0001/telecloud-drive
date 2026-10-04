import time
import uuid
import asyncio
import logging
from typing import Dict, Any, List, Optional
import database

logger = logging.getLogger("task_manager")

class TaskManager:
    def __init__(self):
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self._last_db_save: Dict[str, float] = {}

    async def load_tasks_from_db(self):
        """Load persistent task history from database on startup"""
        try:
            db_tasks = await database.get_all_db_tasks()
            for t in db_tasks:
                self.tasks[t["id"]] = {
                    "id": t["id"],
                    "type": t["type"],
                    "title": t["title"],
                    "url": t.get("url"),
                    "folder_id": t.get("folder_id"),
                    "status": t["status"],
                    "progress": t.get("progress", 0),
                    "step": t.get("step") or ("Completed" if t["status"] == "completed" else "Interrupted"),
                    "downloaded_bytes": t.get("downloaded_bytes", 0),
                    "total_bytes": t.get("total_bytes", 0),
                    "temp_file_path": t.get("temp_file_path"),
                    "cookie": t.get("cookie"),
                    "error": t.get("error"),
                    "result": t.get("result"),
                    "metadata": {"url": t.get("url"), "folder_id": t.get("folder_id"), "cookie": t.get("cookie")},
                    "created_at": time.time(),
                    "updated_at": time.time()
                }
        except Exception as e:
            logger.error(f"Error loading tasks from DB: {e}")

    def create_task(self, task_type: str, title: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        task_id = str(uuid.uuid4())[:8]
        meta = metadata or {}
        task_data = {
            "id": task_id,
            "type": task_type,
            "title": title,
            "url": meta.get("url"),
            "folder_id": meta.get("folder_id"),
            "status": "pending",  # pending, downloading, uploading, completed, failed, paused
            "progress": 0,        # 0 - 100
            "step": "Initializing...",
            "speed": "",
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "temp_file_path": None,
            "cookie": meta.get("cookie"),
            "error": None,
            "result": None,
            "metadata": meta,
            "created_at": time.time(),
            "updated_at": time.time()
        }
        self.tasks[task_id] = task_data
        
        # Async save to DB
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(database.save_task_db(task_data))
        except RuntimeError:
            pass
            
        return task_id

    def update_task(self, task_id: str, **kwargs):
        if task_id in self.tasks:
            self.tasks[task_id].update(kwargs)
            now = time.time()
            self.tasks[task_id]["updated_at"] = now
            
            # Save to database (throttled every 1.5s or on major status change)
            status_change = "status" in kwargs or "result" in kwargs or "error" in kwargs
            last_save = self._last_db_save.get(task_id, 0)
            if status_change or (now - last_save > 1.5):
                self._last_db_save[task_id] = now
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(database.save_task_db(self.tasks[task_id]))
                except RuntimeError:
                    pass

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self.tasks.get(task_id)

    def get_all_tasks(self) -> List[Dict[str, Any]]:
        return sorted(list(self.tasks.values()), key=lambda x: x["updated_at"], reverse=True)

    async def clear_completed_tasks(self):
        self.tasks = {k: v for k, v in self.tasks.items() if v["status"] not in ("completed", "failed")}
        await database.clear_completed_db_tasks()

task_manager = TaskManager()
