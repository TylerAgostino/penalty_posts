"""Local file-based persistence for Penalty Posts drafts and completed posts."""

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

# Directories relative to the app working directory
DRAFTS_DIR = "data/drafts"
POSTS_DIR = "data/posts"
DRAFT_FILES_DIR = "data/draft_files"


def _ensure_dirs() -> None:
    os.makedirs(DRAFTS_DIR, exist_ok=True)
    os.makedirs(POSTS_DIR, exist_ok=True)
    os.makedirs(DRAFT_FILES_DIR, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------


def save_draft(draft: Dict) -> str:
    """
    Persist a draft to disk. Assigns a UUID if the draft has no 'id'.
    Returns the draft ID.

    Expected fields:
        id, status ("draft"), thread_id, thread_name, guild_id, guild_name,
        target_channel_id, target_channel_name, post_content,
        selected_discord_attachments (list of attachment dicts with url/filename/size),
        local_uploads (list of {filename, stored_path, size, content_type}),
        tagged_member_ids, tagged_member_labels,
        created_at, updated_at, created_by_email, created_by_name
    """
    _ensure_dirs()
    if "id" not in draft:
        draft["id"] = str(uuid.uuid4())
    now = _now()
    draft["updated_at"] = now
    draft.setdefault("created_at", now)
    draft.setdefault("status", "draft")
    path = os.path.join(DRAFTS_DIR, f"{draft['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(draft, f, indent=2, ensure_ascii=False)
    return draft["id"]


def load_draft(draft_id: str) -> Optional[Dict]:
    """Load a draft by ID. Returns None if not found."""
    path = os.path.join(DRAFTS_DIR, f"{draft_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_drafts() -> List[Dict]:
    """List all drafts, newest-first by updated_at."""
    _ensure_dirs()
    drafts = []
    for fn in os.listdir(DRAFTS_DIR):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(DRAFTS_DIR, fn), encoding="utf-8") as f:
                    drafts.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass
    return sorted(drafts, key=lambda d: d.get("updated_at", ""), reverse=True)


def delete_draft(draft_id: str) -> None:
    """Delete a draft JSON file and any associated stored upload files."""
    path = os.path.join(DRAFTS_DIR, f"{draft_id}.json")
    if os.path.exists(path):
        os.remove(path)
    files_dir = os.path.join(DRAFT_FILES_DIR, draft_id)
    if os.path.exists(files_dir):
        shutil.rmtree(files_dir)


def get_draft_for_thread(thread_id: str) -> Optional[Dict]:
    """Return the most-recently-updated active draft for a thread, or None."""
    matches = [
        d
        for d in list_drafts()
        if d.get("thread_id") == thread_id and d.get("status") == "draft"
    ]
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Draft local file storage
# ---------------------------------------------------------------------------


def store_draft_file(draft_id: str, filename: str, data: bytes) -> str:
    """Save a locally-uploaded file for a draft. Returns the stored file path."""
    _ensure_dirs()
    dir_path = os.path.join(DRAFT_FILES_DIR, draft_id)
    os.makedirs(dir_path, exist_ok=True)
    safe_name = os.path.basename(filename)  # Prevent path traversal
    file_path = os.path.join(dir_path, safe_name)
    with open(file_path, "wb") as f:
        f.write(data)
    return file_path


def load_draft_file(file_path: str) -> Optional[bytes]:
    """Read a stored draft file. Returns None if the file is missing."""
    if os.path.exists(file_path):
        with open(file_path, "rb") as f:
            return f.read()
    return None


def remove_draft_file(file_path: str) -> None:
    """Delete a single stored draft file."""
    if os.path.exists(file_path):
        os.remove(file_path)


# ---------------------------------------------------------------------------
# Completed posts
# ---------------------------------------------------------------------------


def save_post(post: Dict) -> str:
    """
    Persist a completed post record to disk. Returns the post ID.

    Expected fields:
        id, draft_id, thread_id, thread_name, guild_id, guild_name,
        channel_id, channel_name, discord_message_id,
        post_content, posted_at, posted_by_email, posted_by_name,
        created_at, updated_at
    """
    _ensure_dirs()
    if "id" not in post:
        post["id"] = str(uuid.uuid4())
    now = _now()
    post.setdefault("created_at", now)
    post.setdefault("posted_at", now)
    post["updated_at"] = now
    path = os.path.join(POSTS_DIR, f"{post['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(post, f, indent=2, ensure_ascii=False)
    return post["id"]


def load_post(post_id: str) -> Optional[Dict]:
    """Load a post by ID."""
    path = os.path.join(POSTS_DIR, f"{post_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_posts() -> List[Dict]:
    """List all completed posts, newest-first."""
    _ensure_dirs()
    posts = []
    for fn in os.listdir(POSTS_DIR):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(POSTS_DIR, fn), encoding="utf-8") as f:
                    posts.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass
    return sorted(
        posts,
        key=lambda p: p.get("posted_at", p.get("created_at", "")),
        reverse=True,
    )


def update_post_content(post_id: str, new_content: str) -> Optional[Dict]:
    """Update the stored text content of a completed post. Returns updated post or None."""
    post = load_post(post_id)
    if not post:
        return None
    post["post_content"] = new_content
    post["updated_at"] = _now()
    save_post(post)
    return post
