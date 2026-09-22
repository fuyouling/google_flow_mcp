import json
import os
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

CACHE_FILE = "projects_cache.json"

class ProjectCache:
    """
    Manages persistent local storage for Google Flow project metadata.
    Data is stored in projects_cache.json in the current working directory.
    The primary key for a project is its logical 'project_name'.
    """
    
    @classmethod
    def load(cls) -> dict:
        if not os.path.exists(CACHE_FILE):
            return {"projects": {}}
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data
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
    def get_project_by_name(cls, project_name: str) -> Optional[dict]:
        data = cls.load()
        return data.get("projects", {}).get(project_name)

    @classmethod
    def delete_project(cls, project_name: str) -> None:
        data = cls.load()
        if "projects" in data and project_name in data["projects"]:
            del data["projects"][project_name]
            cls.save(data)

    @classmethod
    def update_project(cls, project_name: str, url: str = None) -> None:
        data = cls.load()
        existing = data.get("projects", {}).get(project_name, {})
        proj = {
            **existing,
            "name": project_name,
            "last_accessed": datetime.now(timezone.utc).isoformat()
        }
        if url:
            proj["url"] = url
        data.setdefault("projects", {})[project_name] = proj
        cls.save(data)

    @classmethod
    def update_project_characters(cls, project_name: str, characters: list) -> None:
        data = cls.load()
        existing = data.get("projects", {}).get(project_name, {})
        data.setdefault("projects", {})[project_name] = {
            **existing,
            "name": project_name,
            "characters": characters,
            "last_characters_updated": datetime.now(timezone.utc).isoformat()
        }
        cls.save(data)

    @classmethod
    def get_project_characters(cls, project_name: str) -> Optional[list]:
        proj = cls.get_project_by_name(project_name)
        if proj:
            return proj.get("characters")
        return None

    @classmethod
    def update_project_images(cls, project_name: str, images: list) -> None:
        data = cls.load()
        existing = data.get("projects", {}).get(project_name, {})
        data.setdefault("projects", {})[project_name] = {
            **existing,
            "name": project_name,
            "images": images,
            "last_images_updated": datetime.now(timezone.utc).isoformat()
        }
        cls.save(data)

    @classmethod
    def get_project_images(cls, project_name: str) -> Optional[list]:
        proj = cls.get_project_by_name(project_name)
        if proj:
            return proj.get("images")
        return None

    @classmethod
    def update_project_videos(cls, project_name: str, videos: list) -> None:
        data = cls.load()
        existing = data.get("projects", {}).get(project_name, {})
        data.setdefault("projects", {})[project_name] = {
            **existing,
            "name": project_name,
            "videos": videos,
            "last_videos_updated": datetime.now(timezone.utc).isoformat()
        }
        cls.save(data)

    @classmethod
    def get_project_videos(cls, project_name: str) -> Optional[list]:
        proj = cls.get_project_by_name(project_name)
        if proj:
            return proj.get("videos")
        return None


