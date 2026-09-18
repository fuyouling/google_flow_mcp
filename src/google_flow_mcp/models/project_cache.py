import json
import os
from datetime import datetime
from typing import Dict, Optional
from loguru import logger

CACHE_FILE = "projects_cache.json"

class ProjectCache:
    """
    Manages persistent local storage for Google Flow project metadata.
    Data is stored in projects_cache.json in the current working directory.
    """
    
    @classmethod
    def load(cls) -> dict:
        if not os.path.exists(CACHE_FILE):
            return {"projects": {}}
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load project cache: {e}")
            return {"projects": {}}
            
    @classmethod
    def save(cls, data: dict) -> None:
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save project cache: {e}")

    @classmethod
    def get_project_by_title(cls, title: str) -> Optional[dict]:
        data = cls.load()
        for proj in data.get("projects", {}).values():
            if proj.get("name") == title:
                return proj
        return None

    @classmethod
    def get_project_by_id(cls, project_id: str) -> Optional[dict]:
        data = cls.load()
        return data.get("projects", {}).get(project_id)

    @classmethod
    def update_project(cls, project_id: str, name: str, url: str) -> None:
        data = cls.load()
        data["projects"][project_id] = {
            "id": project_id,
            "name": name,
            "url": url,
            "last_accessed": datetime.utcnow().isoformat() + "Z"
        }
        cls.save(data)
