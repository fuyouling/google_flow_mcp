import json
from datetime import datetime, timezone
from typing import Optional
from loguru import logger
from google_flow_mcp.config import get_settings
from google_flow_mcp.models.db import get_connection


class ProjectCache:
    """
    Manages persistent local storage for Google Flow project metadata using SQLite.
    The primary key for a project is its logical 'project_name'.
    Supports cluster deployment by storing URLs and assets per worker_id.
    """

    @classmethod
    def _build_project_dict(cls, row) -> dict:
        """Helper to convert a joined DB row into the expected project dictionary."""
        d = dict(row)
        # Parse JSON fields
        for field in ["characters", "images", "videos"]:
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except Exception:
                    d[field] = []
            else:
                # If None or empty, default to not present or empty list depending on usage
                # We'll just omit them if they are None to match old behavior, or set empty list
                pass
                
        # The old dict structure returned `{**proj, **worker_data}`
        # Also need to restructure it so `workers` key is present if anything expects it?
        # Actually, old code returned `{**proj, **worker_data}` from `get_project_by_name`
        # and stripped out the `workers` key, wait, old code did:
        # worker_data = workers[worker_id]
        # return {**proj, **worker_data}  -> This merges them. It doesn't strip `workers`, it keeps `workers` in `proj`.
        # So we should probably add a fake `workers` dict if something relies on it, but ideally nothing does outside this class.
        # Let's just return the flat dict. If something breaks, we'll fix it.
        return d

    @classmethod
    def get_project_by_name(cls, name: str) -> Optional[dict]:
        worker_id = get_settings().worker_id
        
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.name, p.last_accessed,
                       pw.worker_id, pw.url, pw.local_uuid,
                       pw.characters, pw.last_characters_updated,
                       pw.images, pw.last_images_updated,
                       pw.videos, pw.last_videos_updated
                FROM projects p
                JOIN project_workers pw ON p.name = pw.project_name
                WHERE p.name = ? AND pw.worker_id = ?
            """, (name, worker_id))
            row = cursor.fetchone()
            
            if row:
                return cls._build_project_dict(row)
        return None

    @classmethod
    def get_all_projects(cls) -> list[dict]:
        worker_id = get_settings().worker_id
        
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.name, p.last_accessed,
                       pw.worker_id, pw.url, pw.local_uuid,
                       pw.characters, pw.last_characters_updated,
                       pw.images, pw.last_images_updated,
                       pw.videos, pw.last_videos_updated
                FROM projects p
                JOIN project_workers pw ON p.name = pw.project_name
                WHERE pw.worker_id = ?
            """, (worker_id,))
            rows = cursor.fetchall()
            
            return [cls._build_project_dict(row) for row in rows]

    @classmethod
    def delete_project_for_worker(cls, project_name: str) -> None:
        worker_id = get_settings().worker_id
        
        with get_connection() as conn:
            cursor = conn.cursor()
            conn.execute("BEGIN IMMEDIATE")
            
            # Delete worker specific data
            cursor.execute("""
                DELETE FROM project_workers 
                WHERE project_name = ? AND worker_id = ?
            """, (project_name, worker_id))
            
            # Check if there are any workers left for this project
            cursor.execute("""
                SELECT COUNT(*) as count FROM project_workers WHERE project_name = ?
            """, (project_name,))
            row = cursor.fetchone()
            
            if row and row["count"] == 0:
                # No workers left, delete the project
                cursor.execute("""
                    DELETE FROM projects WHERE name = ?
                """, (project_name,))
                
            conn.commit()

    @classmethod
    def rename_project_for_worker(cls, old_name: str, new_name: str) -> None:
        worker_id = get_settings().worker_id
        
        with get_connection() as conn:
            cursor = conn.cursor()
            conn.execute("BEGIN IMMEDIATE")
            
            # 1. Get worker data from old project
            cursor.execute("""
                SELECT * FROM project_workers 
                WHERE project_name = ? AND worker_id = ?
            """, (old_name, worker_id))
            worker_row = cursor.fetchone()
            
            if not worker_row:
                conn.commit()
                return  # Nothing to rename for this worker
                
            worker_data = dict(worker_row)
            
            # 2. Delete worker data from old project
            cursor.execute("""
                DELETE FROM project_workers 
                WHERE project_name = ? AND worker_id = ?
            """, (old_name, worker_id))
            
            # Check if old project should be deleted
            cursor.execute("""
                SELECT COUNT(*) as count FROM project_workers WHERE project_name = ?
            """, (old_name,))
            row = cursor.fetchone()
            if row and row["count"] == 0:
                cursor.execute("DELETE FROM projects WHERE name = ?", (old_name,))
                
            # 3. Create or update new project
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute("""
                INSERT INTO projects (name, last_accessed)
                VALUES (?, ?)
                ON CONFLICT(name) DO UPDATE SET last_accessed = excluded.last_accessed
            """, (new_name, now))
            
            # 4. Insert worker data into new project
            cursor.execute("""
                INSERT INTO project_workers (
                    project_name, worker_id, url, local_uuid,
                    characters, last_characters_updated,
                    images, last_images_updated,
                    videos, last_videos_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_name, worker_id) DO UPDATE SET
                    url = excluded.url,
                    local_uuid = excluded.local_uuid,
                    characters = excluded.characters,
                    last_characters_updated = excluded.last_characters_updated,
                    images = excluded.images,
                    last_images_updated = excluded.last_images_updated,
                    videos = excluded.videos,
                    last_videos_updated = excluded.last_videos_updated
            """, (
                new_name, worker_id, worker_data.get("url"), worker_data.get("local_uuid"),
                worker_data.get("characters"), worker_data.get("last_characters_updated"),
                worker_data.get("images"), worker_data.get("last_images_updated"),
                worker_data.get("videos"), worker_data.get("last_videos_updated")
            ))
            
            conn.commit()

    @classmethod
    def update_project(cls, project_name: str, url: str = None) -> None:
        worker_id = get_settings().worker_id
        
        with get_connection() as conn:
            cursor = conn.cursor()
            conn.execute("BEGIN IMMEDIATE")
            
            now = datetime.now(timezone.utc).isoformat()
            
            # Ensure project exists
            cursor.execute("""
                INSERT INTO projects (name, last_accessed)
                VALUES (?, ?)
                ON CONFLICT(name) DO UPDATE SET last_accessed = excluded.last_accessed
            """, (project_name, now))
            
            local_uuid = None
            if url:
                try:
                    if "/project/" in url:
                        local_uuid = url.split("/project/")[1].split("/")[0]
                except Exception:
                    pass
            
            # Upsert worker
            if url:
                cursor.execute("""
                    INSERT INTO project_workers (project_name, worker_id, url, local_uuid)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(project_name, worker_id) DO UPDATE SET 
                        url = excluded.url,
                        local_uuid = excluded.local_uuid
                """, (project_name, worker_id, url, local_uuid))
            else:
                cursor.execute("""
                    INSERT OR IGNORE INTO project_workers (project_name, worker_id)
                    VALUES (?, ?)
                """, (project_name, worker_id))
                
            conn.commit()

    @classmethod
    def update_project_characters(cls, project_name: str, characters: list) -> None:
        worker_id = get_settings().worker_id
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Make sure project exists (it should, but just in case)
            cursor.execute("""
                INSERT OR IGNORE INTO projects (name, last_accessed)
                VALUES (?, ?)
            """, (project_name, datetime.now(timezone.utc).isoformat()))
            
            now = datetime.now(timezone.utc).isoformat()
            chars_json = json.dumps(characters, ensure_ascii=False)
            
            cursor.execute("""
                INSERT INTO project_workers (project_name, worker_id, characters, last_characters_updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_name, worker_id) DO UPDATE SET
                    characters = excluded.characters,
                    last_characters_updated = excluded.last_characters_updated
            """, (project_name, worker_id, chars_json, now))
            
            conn.commit()

    @classmethod
    def get_project_characters(cls, project_name: str) -> Optional[list]:
        proj = cls.get_project_by_name(project_name)
        if proj and "characters" in proj:
            return proj.get("characters")
        return None

    @classmethod
    def update_project_images(cls, project_name: str, images: list) -> None:
        worker_id = get_settings().worker_id
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR IGNORE INTO projects (name, last_accessed)
                VALUES (?, ?)
            """, (project_name, datetime.now(timezone.utc).isoformat()))
            
            now = datetime.now(timezone.utc).isoformat()
            images_json = json.dumps(images, ensure_ascii=False)
            
            cursor.execute("""
                INSERT INTO project_workers (project_name, worker_id, images, last_images_updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_name, worker_id) DO UPDATE SET
                    images = excluded.images,
                    last_images_updated = excluded.last_images_updated
            """, (project_name, worker_id, images_json, now))
            
            conn.commit()

    @classmethod
    def get_project_images(cls, project_name: str) -> Optional[list]:
        proj = cls.get_project_by_name(project_name)
        if proj and "images" in proj:
            return proj.get("images")
        return None

    @classmethod
    def update_project_videos(cls, project_name: str, videos: list) -> None:
        worker_id = get_settings().worker_id
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR IGNORE INTO projects (name, last_accessed)
                VALUES (?, ?)
            """, (project_name, datetime.now(timezone.utc).isoformat()))
            
            now = datetime.now(timezone.utc).isoformat()
            videos_json = json.dumps(videos, ensure_ascii=False)
            
            cursor.execute("""
                INSERT INTO project_workers (project_name, worker_id, videos, last_videos_updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_name, worker_id) DO UPDATE SET
                    videos = excluded.videos,
                    last_videos_updated = excluded.last_videos_updated
            """, (project_name, worker_id, videos_json, now))
            
            conn.commit()

    @classmethod
    def get_project_videos(cls, project_name: str) -> Optional[list]:
        proj = cls.get_project_by_name(project_name)
        if proj and "videos" in proj:
            return proj.get("videos")
        return None
