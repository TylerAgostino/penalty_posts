"""Discord REST API helpers for Penalty Posts."""

import io
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
import streamlit as st

DISCORD_API_BASE = "https://discord.com/api/v10"

# Channel types
CHANNEL_TEXT = 0
CHANNEL_ANNOUNCEMENT = 5
CHANNEL_FORUM = 15
CHANNEL_PUBLIC_THREAD = 11


# ---------------------------------------------------------------------------
# Internal HTTP helpers
# ---------------------------------------------------------------------------


def _hdrs(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bot {token}"}


def _get(token: str, path: str, **kwargs) -> requests.Response:
    r = requests.get(f"{DISCORD_API_BASE}{path}", headers=_hdrs(token), **kwargs)
    r.raise_for_status()
    return r


def _patch(token: str, path: str, **kwargs) -> requests.Response:
    r = requests.patch(f"{DISCORD_API_BASE}{path}", headers=_hdrs(token), **kwargs)
    r.raise_for_status()
    return r


# ---------------------------------------------------------------------------
# Cached fetchers
# ---------------------------------------------------------------------------


@st.cache_data(ttl=60, show_spinner=False)
def fetch_bot_user(token: str) -> Dict:
    """Fetch the bot's own user object."""
    return _get(token, "/users/@me").json()


@st.cache_data(ttl=300, show_spinner=False)
def fetch_guilds(token: str) -> List[Dict]:
    """Fetch guilds the bot belongs to, filtered by ALLOWED_GUILD_IDS if set."""
    guilds: List[Dict] = _get(token, "/users/@me/guilds").json()
    allowed_str = os.getenv("ALLOWED_GUILD_IDS", "").strip()
    if allowed_str:
        try:
            allowed_ids = {
                int(gid.strip()) for gid in allowed_str.split(",") if gid.strip()
            }
            guilds = [g for g in guilds if int(g["id"]) in allowed_ids]
        except ValueError:
            return []
    return guilds


@st.cache_data(ttl=120, show_spinner=False)
def fetch_all_channels(token: str, guild_id: str) -> List[Dict]:
    """Fetch all channels in a guild."""
    return _get(token, f"/guilds/{guild_id}/channels").json()


@st.cache_data(ttl=120, show_spinner=False)
def fetch_text_channels(token: str, guild_id: str) -> List[Dict]:
    """Fetch text/announcement channels sorted by position."""
    channels = fetch_all_channels(token, guild_id)
    text = [
        c for c in channels if c.get("type") in (CHANNEL_TEXT, CHANNEL_ANNOUNCEMENT)
    ]
    return sorted(text, key=lambda c: c.get("position", 0))


@st.cache_data(ttl=120, show_spinner=False)
def fetch_forum_channels(token: str, guild_id: str) -> List[Dict]:
    """Fetch forum channels sorted by position."""
    channels = fetch_all_channels(token, guild_id)
    forums = [c for c in channels if c.get("type") == CHANNEL_FORUM]
    return sorted(forums, key=lambda c: c.get("position", 0))


@st.cache_data(ttl=30, show_spinner=False)
def fetch_active_threads(token: str, guild_id: str) -> List[Dict]:
    """Fetch all active threads across the guild."""
    data = _get(token, f"/guilds/{guild_id}/threads/active").json()
    return data.get("threads", [])


@st.cache_data(ttl=30, show_spinner=False)
def fetch_thread_messages(token: str, thread_id: str, limit: int = 100) -> List[Dict]:
    """Fetch messages in a thread in chronological order."""
    msgs = _get(
        token, f"/channels/{thread_id}/messages", params={"limit": limit}
    ).json()
    return list(reversed(msgs))


@st.cache_data(ttl=60, show_spinner=False)
def fetch_single_message(
    token: str, channel_id: str, message_id: str
) -> Optional[Dict]:
    """Fetch a single message by ID. Returns None on failure."""
    try:
        return _get(token, f"/channels/{channel_id}/messages/{message_id}").json()
    except requests.HTTPError:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def fetch_members(token: str, guild_id: str) -> List[Dict]:
    """Fetch all non-bot guild members with automatic pagination."""
    members: List[Dict] = []
    after: Optional[str] = None
    while True:
        params: Dict = {"limit": 1000}
        if after:
            params["after"] = after
        r = requests.get(
            f"{DISCORD_API_BASE}/guilds/{guild_id}/members",
            headers=_hdrs(token),
            params=params,
        )
        r.raise_for_status()
        batch: List[Dict] = r.json()
        members.extend([m for m in batch if not m["user"].get("bot", False)])
        if len(batch) < 1000:
            break
        after = batch[-1]["user"]["id"]
    return sorted(
        members, key=lambda m: (m.get("nick") or m["user"]["username"]).lower()
    )


# ---------------------------------------------------------------------------
# Forum thread helpers
# ---------------------------------------------------------------------------


def _find_tag_id(channel: Dict, tag_name: str) -> Optional[str]:
    """Find a tag ID by name (case-insensitive) within a forum channel."""
    for tag in channel.get("available_tags", []):
        if tag["name"].lower() == tag_name.lower():
            return tag["id"]
    return None


def get_open_forum_threads(token: str, guild_id: str) -> List[Dict]:
    """
    Return active forum threads that do NOT have the 'Closed' tag applied.
    Each returned thread is augmented with '_forum_channel' and '_closed_tag_id'.
    """
    all_channels = fetch_all_channels(token, guild_id)
    channel_map = {c["id"]: c for c in all_channels}
    forum_ids = {c["id"] for c in all_channels if c.get("type") == CHANNEL_FORUM}
    active = fetch_active_threads(token, guild_id)

    open_threads: List[Dict] = []
    for thread in active:
        parent_id = thread.get("parent_id", "")
        if parent_id not in forum_ids:
            continue
        parent = channel_map.get(parent_id, {})
        closed_tag_id = _find_tag_id(parent, "closed")
        if closed_tag_id and closed_tag_id in thread.get("applied_tags", []):
            continue  # Already closed
        t = dict(thread)  # Don't mutate cached data
        t["_forum_channel"] = parent
        t["_closed_tag_id"] = closed_tag_id
        open_threads.append(t)

    open_threads.sort(key=lambda t: t.get("id", "0"), reverse=True)
    return open_threads


def apply_closed_tag(
    token: str,
    thread: Dict,
    also_remove_names: Optional[List[str]] = None,
) -> bool:
    """
    Apply the 'Closed' tag to a forum thread, optionally removing other tags by name.
    Returns True on success, False if no 'Closed' tag is configured or the API call fails.

    Parameters
    ----------
    also_remove_names
        Display names of tags to strip from the thread at the same time
        (e.g. ["Open", "Needs Review"]).  Case-insensitive.
    """
    forum = thread.get("_forum_channel", {})
    closed_tag_id = thread.get("_closed_tag_id") or _find_tag_id(forum, "closed")
    if not closed_tag_id:
        return False

    current: List[str] = list(thread.get("applied_tags", []))

    # Build the set of tag IDs to remove
    remove_ids: set = set()
    if also_remove_names:
        name_to_id = {
            t["name"].lower(): t["id"] for t in forum.get("available_tags", [])
        }
        remove_ids = {
            name_to_id[n.lower()] for n in also_remove_names if n.lower() in name_to_id
        }

    # Build the new tag list: drop removed IDs, ensure Closed is present
    new_tags = [tid for tid in current if tid not in remove_ids]
    if closed_tag_id not in new_tags:
        new_tags.append(closed_tag_id)

    if new_tags == current:
        return True  # Already in the desired state; no API call needed

    try:
        _patch(token, f"/channels/{thread['id']}", json={"applied_tags": new_tags})
        return True
    except requests.HTTPError:
        return False


def get_thread_tag_names(thread: Dict) -> List[str]:
    """Return display names of tags applied to a thread, excluding 'Closed'."""
    forum = thread.get("_forum_channel", {})
    tag_map = {t["id"]: t["name"] for t in forum.get("available_tags", [])}
    return [
        tag_map[tid]
        for tid in thread.get("applied_tags", [])
        if tid in tag_map and tag_map[tid].lower() != "closed"
    ]


# ---------------------------------------------------------------------------
# Messaging
# ---------------------------------------------------------------------------


def send_message(
    token: str,
    channel_id: str,
    content: str,
    files: Optional[List[Tuple[str, bytes]]] = None,
) -> Dict:
    """Send a message with optional file attachments to a Discord channel."""
    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
    hdrs = _hdrs(token)
    if files:
        form_data: Dict[str, str] = {}
        if content:
            form_data["content"] = content
        multipart = [
            (f"files[{i}]", (name, io.BytesIO(data), "application/octet-stream"))
            for i, (name, data) in enumerate(files)
        ]
        r = requests.post(url, headers=hdrs, data=form_data, files=multipart)
    else:
        r = requests.post(url, headers=hdrs, json={"content": content})
    r.raise_for_status()
    return r.json()


def edit_message(
    token: str,
    channel_id: str,
    message_id: str,
    content: str,
    keep_attachment_ids: Optional[List[str]] = None,
    new_files: Optional[List[Tuple[str, bytes]]] = None,
) -> Dict:
    """
    Edit a bot-authored Discord message.

    Attachment semantics (Discord API v10 rules):
    - keep_attachment_ids=None, new_files empty  -> text-only edit; existing attachments unchanged
    - keep_attachment_ids=None, new_files=[...]   -> append new files; all existing are kept
    - keep_attachment_ids=[...], new_files empty  -> keep only the listed attachment IDs (removes others)
    - keep_attachment_ids=[...], new_files=[...]  -> keep listed IDs and add new files
    """
    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}"
    hdrs = _hdrs(token)
    new_files = new_files or []

    # ── Case 1: text-only edit ──────────────────────────────────────────────
    if keep_attachment_ids is None and not new_files:
        r = requests.patch(url, headers=hdrs, json={"content": content})
        r.raise_for_status()
        return r.json()

    # ── Case 2+: attachment changes involved ────────────────────────────────
    if keep_attachment_ids is not None:
        # Build the explicit attachments list: retained existing + new-file placeholders
        att_list: List[Dict] = [{"id": aid} for aid in keep_attachment_ids]
        att_list += [{"id": i} for i in range(len(new_files))]
        payload: Dict = {"content": content, "attachments": att_list}
    else:
        # Only appending; no restrictions on existing attachments
        payload = {"content": content}

    if new_files:
        multipart = [
            (f"files[{i}]", (name, io.BytesIO(data), "application/octet-stream"))
            for i, (name, data) in enumerate(new_files)
        ]
        r = requests.patch(
            url,
            headers=hdrs,
            data={"payload_json": json.dumps(payload)},
            files=multipart,
        )
    else:
        # Removing attachments without adding new ones—plain JSON PATCH is fine
        r = requests.patch(url, headers=hdrs, json=payload)

    r.raise_for_status()
    return r.json()


def download_attachment(url: str) -> Optional[bytes]:
    """Download a file from a Discord CDN URL. Returns None on failure."""
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        return r.content
    except requests.RequestException:
        return None


# ---------------------------------------------------------------------------
# Formatting utilities
# ---------------------------------------------------------------------------


def format_member_label(member: Dict) -> str:
    nick = member.get("nick")
    username = member["user"]["username"]
    return f"{nick} (@{username})" if nick else f"@{username}"


def build_mention(member: Dict) -> str:
    return f"<@{member['user']['id']}>"


def format_timestamp(iso_str: str) -> str:
    """Format an ISO 8601 timestamp for display."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y %H:%M UTC")
    except (ValueError, AttributeError):
        return iso_str


def snowflake_to_timestamp(snowflake_id: str) -> str:
    """Convert a Discord snowflake ID to a human-readable UTC timestamp."""
    try:
        ts_ms = (int(snowflake_id) >> 22) + 1420070400000
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        return dt.strftime("%b %d, %Y %H:%M UTC")
    except (ValueError, TypeError):
        return "Unknown"


def format_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1_048_576:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1_048_576:.1f} MB"


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


def clear_caches() -> None:
    """Invalidate all cached Discord API responses."""
    fetch_bot_user.clear()
    fetch_guilds.clear()
    fetch_all_channels.clear()
    fetch_text_channels.clear()
    fetch_forum_channels.clear()
    fetch_active_threads.clear()
    fetch_thread_messages.clear()
    fetch_single_message.clear()
    fetch_members.clear()
