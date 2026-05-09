"""Penalty Posts — Queue page.

Shows open (non-closed) forum threads and lets admins draft, preview,
and publish incident-summary posts with automatic thread closure.

This file is loaded by the navigation entry-point (app.py).
"""

import os
from typing import Dict, List, Optional, Tuple

import requests
import streamlit as st

import discord_helpers as dh
import draft_manager as dm

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
if not st.user or not st.user.is_logged_in:
    st.error("🔒 Authentication Required")
    st.info("Please sign in with your Google account to access Penalty Posts.")
    if st.button("🔐 Sign in with Google"):
        st.login()
    st.stop()

USER_NAME: str = str(st.user.get("name") or "Unknown")
USER_EMAIL: str = str(st.user.get("email") or "unknown@example.com")

# ---------------------------------------------------------------------------
# Bot token
# ---------------------------------------------------------------------------
TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
if not TOKEN:
    st.error("❌ BOT_TOKEN environment variable is not set.")
    st.stop()

# ---------------------------------------------------------------------------
# Static configuration — edit these values to match your server
# ---------------------------------------------------------------------------

# Pre-select this channel ID as the default posting target.
# Leave as "" to require manual selection each time.
DEFAULT_POST_CHANNEL_ID: str = "1239988445326348460"

# Pre-filter the queue to threads from this forum channel ID.
# Leave as "" to show threads from all forum channels.
DEFAULT_FORUM_CHANNEL_ID: str = "1462883598351863839"

# Tag names to REMOVE from the forum thread when closing it (on top of applying "Closed").
# Example: ["Open", "Needs Review"]
TAGS_TO_REMOVE_ON_CLOSE: List[str] = ["Under Review"]

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------
_SS_DEFAULTS: Dict = {
    "view": "queue",  # "queue" | "editor"
    "selected_thread": None,  # thread dict when in editor view
    "editor_thread_id": None,  # tracks last loaded thread to detect switches
    "current_draft": None,  # loaded draft dict or None
    "selected_guild_id": None,
}
for _k, _v in _SS_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.write(f"👤 **{USER_NAME}**")
    st.caption(USER_EMAIL)
    col_r, col_l = st.columns(2)
    with col_r:
        if st.button("🔄 Refresh", use_container_width=True):
            dh.clear_caches()
            st.rerun()
    with col_l:
        if st.button("🚪 Logout", use_container_width=True):
            st.logout()

    st.divider()
    st.subheader("🤖 Bot Status")
    try:
        _bot = dh.fetch_bot_user(TOKEN)
        st.success(f"Connected as **{_bot['username']}**")
    except requests.HTTPError as _e:
        st.error(f"❌ Discord error {_e.response.status_code}")
        st.stop()
    except requests.RequestException:
        st.error("❌ Cannot reach Discord API")
        st.stop()


# ---------------------------------------------------------------------------
# Guild selection
# ---------------------------------------------------------------------------
try:
    _guilds = dh.fetch_guilds(TOKEN)
except requests.RequestException as _e:
    st.error(f"❌ Failed to load guilds: {_e}")
    st.stop()

if not _guilds:
    st.warning("The bot is not in any servers (or none match ALLOWED_GUILD_IDS).")
    st.stop()

if len(_guilds) == 1:
    GUILD = _guilds[0]
else:
    _gmap = {g["name"]: g for g in _guilds}
    _current_name = (
        _gmap.get(st.session_state.selected_guild_id, {}).get("name")
        if st.session_state.selected_guild_id
        else list(_gmap.keys())[0]
    )
    _sel_name = st.selectbox(
        "Server",
        list(_gmap.keys()),
        index=list(_gmap.keys()).index(_current_name) if _current_name in _gmap else 0,
    )
    GUILD = _gmap[_sel_name]

st.session_state.selected_guild_id = GUILD["id"]
GUILD_ID: str = GUILD["id"]
GUILD_NAME: str = GUILD["name"]


# ===========================================================================
# Helper functions
# ===========================================================================


def _format_dt(iso_or_snowflake: str, is_snowflake: bool = False) -> str:
    """Return a short human-readable timestamp."""
    if is_snowflake:
        return dh.snowflake_to_timestamp(iso_or_snowflake)
    return dh.format_timestamp(iso_or_snowflake)


def _get_display_name(msg_author: Dict, member_map_by_id: Dict[str, Dict]) -> str:
    """Resolve the best display name for a message author.

    Priority: server nickname > global display name > username.
    Falls back gracefully for users no longer in the server.
    """
    user_id = msg_author.get("id", "")
    member = member_map_by_id.get(user_id)
    if member and member.get("nick"):
        return member["nick"]
    return msg_author.get("global_name") or msg_author.get("username", "Unknown")


def _collect_thread_attachments(
    messages: List[Dict],
    member_map_by_id: Optional[Dict[str, Dict]] = None,
) -> List[Dict]:
    """Return a deduplicated list of attachment dicts from all thread messages."""
    seen_ids = set()
    attachments = []
    for msg in messages:
        author = _get_display_name(msg.get("author", {}), member_map_by_id or {})
        for att in msg.get("attachments", []):
            if att["id"] not in seen_ids:
                seen_ids.add(att["id"])
                enriched = dict(att)
                enriched["_author"] = author
                enriched["_message_id"] = msg["id"]
                attachments.append(enriched)
    return attachments


def _attachment_label(att: Dict) -> str:
    size_str = dh.format_size(att.get("size", 0))
    return f"{att['filename']} ({size_str}) — from {att['_author']}"


# ===========================================================================
# Queue view
# ===========================================================================


def show_queue() -> None:
    st.title("📋 Penalty Posts — Queue")
    st.caption(
        "Open forum threads awaiting an incident post. "
        "Threads tagged 'Closed' are hidden here and appear on the Completed Posts page."
    )

    with st.spinner("Loading forum threads..."):
        try:
            open_threads = dh.get_open_forum_threads(TOKEN, GUILD_ID)
        except requests.HTTPError as e:
            st.error(
                f"❌ Failed to load threads: {e.response.status_code} {e.response.text}"
            )
            return
        except requests.RequestException as e:
            st.error(f"❌ Network error: {e}")
            return

    # Load drafts to cross-reference
    all_drafts = dm.list_drafts()
    draft_by_thread = {
        d["thread_id"]: d for d in all_drafts if d.get("status") == "draft"
    }

    if not open_threads:
        st.info("✅ No open forum threads found. All caught up!")
        # Still show orphaned drafts if any exist
        orphan_drafts = [
            d
            for d in all_drafts
            if d.get("status") == "draft"
            and d["thread_id"] not in {t["id"] for t in open_threads}
        ]
        if orphan_drafts:
            st.subheader("📝 Saved Drafts (thread may be closed)")
            for draft in orphan_drafts:
                _render_draft_card(draft)
        return

    # Forum channel filter (if multiple forums)
    forum_names = sorted(
        {t["_forum_channel"].get("name", "Unknown") for t in open_threads}
    )
    if len(forum_names) > 1:
        # Compute the default selection
        if DEFAULT_FORUM_CHANNEL_ID:
            _default_forum = next(
                (
                    t["_forum_channel"]
                    for t in open_threads
                    if t.get("parent_id") == DEFAULT_FORUM_CHANNEL_ID
                ),
                None,
            )
            _default_name = _default_forum.get("name", "") if _default_forum else ""
            default_sel = (
                [_default_name] if _default_name in forum_names else forum_names
            )
        else:
            default_sel = forum_names

        selected_forums = st.multiselect(
            "Filter by forum channel",
            forum_names,
            default=default_sel,
            label_visibility="collapsed",
        )
        open_threads = [
            t
            for t in open_threads
            if t["_forum_channel"].get("name") in selected_forums
        ]

    st.subheader(f"🔔 Open Threads ({len(open_threads)})")

    for thread in open_threads:
        _render_thread_card(thread, draft_by_thread.get(thread["id"]))

    # Orphaned drafts section
    active_ids = {t["id"] for t in open_threads}
    orphan_drafts = [
        d
        for d in all_drafts
        if d.get("status") == "draft" and d["thread_id"] not in active_ids
    ]
    if orphan_drafts:
        st.divider()
        st.subheader("📝 Other Saved Drafts")
        st.caption(
            "These drafts reference threads that may have been closed externally."
        )
        for draft in orphan_drafts:
            _render_draft_card(draft)


def _render_thread_card(thread: Dict, draft: Optional[Dict]) -> None:
    forum_name = thread["_forum_channel"].get("name", "Unknown")
    thread_name = thread.get("name", "Untitled Thread")
    created_ts = dh.snowflake_to_timestamp(thread["id"])
    tags = dh.get_thread_tag_names(thread)

    with st.container(border=True):
        col_info, col_btn = st.columns([5, 1])
        with col_info:
            badge = " 📝 *Draft saved*" if draft else ""
            st.markdown(f"### {thread_name}{badge}")
            meta_parts = [f"📁 `#{forum_name}`", f"🕐 {created_ts}"]
            if tags:
                meta_parts.append("🏷️ " + ", ".join(tags))
            st.caption("  ·  ".join(meta_parts))
        with col_btn:
            st.write("")
            if st.button(
                "Open →",
                key=f"open_{thread['id']}",
                type="primary",
                use_container_width=True,
            ):
                st.session_state.selected_thread = thread
                st.session_state.view = "editor"
                # Clear editor_thread_id so editor re-initialises for this thread
                st.session_state.editor_thread_id = None
                st.rerun()


def _render_draft_card(draft: Dict) -> None:
    with st.container(border=True):
        col_info, col_btn = st.columns([5, 1])
        with col_info:
            st.markdown(f"**{draft.get('thread_name', 'Untitled')}**")
            updated = draft.get("updated_at", "")
            by = draft.get("created_by_name", "")
            st.caption(f"Last saved: {dh.format_timestamp(updated)}  ·  by {by}")
        with col_btn:
            st.write("")
            if st.button(
                "Delete", key=f"del_draft_{draft['id']}", use_container_width=True
            ):
                dm.delete_draft(draft["id"])
                st.rerun()


# ===========================================================================
# Editor view
# ===========================================================================


def show_editor() -> None:
    thread: Dict = st.session_state.selected_thread
    thread_id: str = thread["id"]
    forum_channel = thread.get("_forum_channel", {})
    forum_name = forum_channel.get("name", "Unknown")

    # ── Re-initialise editor state when thread changes ──
    if st.session_state.editor_thread_id != thread_id:
        st.session_state.editor_thread_id = thread_id
        draft = dm.get_draft_for_thread(thread_id)
        st.session_state.current_draft = draft
        # Clear widget-keyed values so defaults take effect on next render
        for _key in [
            "editor_content",
            "editor_sel_attachments",
            "editor_channel",
            "editor_members",
        ]:
            st.session_state.pop(_key, None)

    draft: Optional[Dict] = st.session_state.current_draft

    # ── Back button ──
    if st.button("← Back to Queue"):
        st.session_state.view = "queue"
        st.session_state.selected_thread = None
        st.rerun()

    st.title(f"📄 {thread.get('name', 'Untitled Thread')}")
    st.caption(f"📁 `#{forum_name}`  ·  opened {dh.snowflake_to_timestamp(thread_id)}")

    # Draft status banner
    if draft:
        updated = dh.format_timestamp(draft.get("updated_at", ""))
        by = draft.get("created_by_name", "")
        st.info(f"📝 **Draft saved** — last updated {updated} by {by}")

    st.divider()

    # Fetch members early — cached, so this is free on re-runs.
    # Used for both conversation display names and the member-tagging widget.
    try:
        members = dh.fetch_members(TOKEN, GUILD_ID)
    except requests.RequestException:
        members = []
    member_map_by_id: Dict[str, Dict] = {m["user"]["id"]: m for m in members}
    member_map: Dict[str, Dict] = {dh.format_member_label(m): m for m in members}

    # Fetch thread messages (cached)
    with st.spinner("Loading thread messages..."):
        try:
            messages = dh.fetch_thread_messages(TOKEN, thread_id)
        except requests.HTTPError as e:
            st.error(f"❌ Could not load messages: {e.response.status_code}")
            messages = []
        except requests.RequestException as e:
            st.error(f"❌ Network error loading messages: {e}")
            messages = []

    all_attachments = _collect_thread_attachments(messages, member_map_by_id)

    # Build label ↔ attachment map
    label_to_att: Dict[str, Dict] = {}
    for att in all_attachments:
        label = _attachment_label(att)
        label_to_att[label] = att

    # Compute default attachment selection from draft
    draft_att_urls: set = set()
    if draft:
        draft_att_urls = {
            a["url"] for a in draft.get("selected_discord_attachments", [])
        }
    default_att_labels = [
        lbl for lbl, att in label_to_att.items() if att["url"] in draft_att_urls
    ]

    # Two-column layout
    col_conv, col_edit = st.columns([2, 3], gap="large")

    # ── Left column: Thread conversation ──
    with col_conv:
        st.subheader("💬 Thread Conversation")
        with st.container(height=520):
            if not messages:
                st.info("No messages found in this thread.")
            for msg in messages:
                author = _get_display_name(msg.get("author", {}), member_map_by_id)
                ts_raw = msg.get("timestamp", "")
                ts = dh.format_timestamp(ts_raw) if ts_raw else ""
                with st.chat_message(name=author):
                    st.caption(f"**{author}** · {ts}")
                    if msg.get("content"):
                        st.markdown(msg["content"])
                    for att in msg.get("attachments", []):
                        ct = att.get("content_type", "")
                        size_str = dh.format_size(att.get("size", 0))
                        if ct.startswith("image/"):
                            try:
                                st.image(
                                    att["proxy_url"] or att["url"],
                                    caption=f"{att['filename']} ({size_str})",
                                    use_container_width=True,
                                )
                            except Exception:
                                st.markdown(
                                    f"📎 [{att['filename']}]({att['url']}) ({size_str})"
                                )
                        elif ct.startswith("video/"):
                            st.caption(f"🎥 **{att['filename']}** ({size_str})")
                            try:
                                st.video(att["url"], format=ct)
                            except Exception:
                                st.markdown(f"[▶ Open video]({att['url']})")
                        else:
                            st.markdown(
                                f"📎 [{att['filename']}]({att['url']}) ({size_str})"
                            )

    # ── Right column: Post editor ──
    with col_edit:
        st.subheader("✏️ Draft Post")

        # Target channel
        try:
            text_channels = dh.fetch_text_channels(TOKEN, GUILD_ID)
        except requests.RequestException:
            text_channels = []

        channel_options = [f"#{c['name']}" for c in text_channels]
        channel_ids = [c["id"] for c in text_channels]

        # Determine default channel index: draft > static default > first channel
        default_ch_idx = 0
        _target_id = None
        if draft and draft.get("target_channel_id"):
            _target_id = draft["target_channel_id"]
        elif DEFAULT_POST_CHANNEL_ID:
            _target_id = DEFAULT_POST_CHANNEL_ID
        if _target_id and _target_id in channel_ids:
            default_ch_idx = channel_ids.index(_target_id)

        selected_ch_label = st.selectbox(
            "Post to channel",
            channel_options,
            index=default_ch_idx,
            key="editor_channel",
            help="The channel where the incident summary will be posted.",
        )
        selected_ch_idx = (
            channel_options.index(selected_ch_label)
            if selected_ch_label in channel_options
            else 0
        )
        selected_channel = text_channels[selected_ch_idx] if text_channels else None

        # Member tagging
        with st.expander("🏷️ Tag Members", expanded=False):
            # member_map already built above from the cached fetch
            default_tags = draft.get("tagged_member_labels", []) if draft else []
            default_tags = [
                t for t in default_tags if t in member_map
            ]  # Filter stale labels

            selected_member_labels = st.multiselect(
                "Search and select members to mention",
                options=list(member_map.keys()),
                default=default_tags,
                placeholder="Type a name to search…",
                key="editor_members",
            )

            if selected_member_labels:
                mention_str = " ".join(
                    dh.build_mention(member_map[lbl]) for lbl in selected_member_labels
                )
                st.code(mention_str, language=None)
                if st.button("➕ Insert mentions into post"):
                    existing = st.session_state.get("editor_content", "")
                    sep = " " if existing and not existing.endswith(" ") else ""
                    st.session_state["editor_content"] = existing + sep + mention_str
                    st.rerun()

        # Post content
        post_template = """## Event: S##R# - Track Name - Feature Lap #

### Driver(s)

### Incident(s)

### Decision(s)
**__No Action__**
        """
        default_content = draft.get("post_content", "") if draft else post_template
        post_content = st.text_area(
            "Post content",
            value=default_content,
            height=200,
            placeholder="Write the incident summary here…",
            key="editor_content",
        )

        # Discord attachment selection
        if label_to_att:
            st.markdown("**📎 Attach media from thread**")
            selected_att_labels = st.multiselect(
                "Select files to include in the post",
                options=list(label_to_att.keys()),
                default=default_att_labels,
                key="editor_sel_attachments",
                help="Files from the thread conversation. They will be re-uploaded with your post.",
                label_visibility="collapsed",
            )
        else:
            selected_att_labels = []
            st.caption("ℹ️ No attachments found in this thread.")

        # Local file upload
        st.markdown("**📁 Upload additional files**")

        # Show previously stored draft files
        stored_uploads: List[Dict] = draft.get("local_uploads", []) if draft else []
        still_valid = [
            u for u in stored_uploads if os.path.exists(u.get("stored_path", ""))
        ]
        removed_paths = set()
        if still_valid:
            st.caption(f"{len(still_valid)} file(s) saved with this draft:")
            for upload in still_valid:
                ucol_name, ucol_rm = st.columns([5, 1])
                ucol_name.write(
                    f"📄 {upload['filename']} ({dh.format_size(upload['size'])})"
                )
                if ucol_rm.button("✕", key=f"rm_{upload['stored_path']}"):
                    removed_paths.add(upload["stored_path"])
                    dm.remove_draft_file(upload["stored_path"])
        active_stored = [
            u for u in still_valid if u["stored_path"] not in removed_paths
        ]

        new_uploads = st.file_uploader(
            "Upload new files",
            accept_multiple_files=True,
            label_visibility="collapsed",
        )

        st.divider()

        # Action buttons
        btn_col1, btn_col2 = st.columns(2)

        # ── Save Draft ──
        with btn_col1:
            if st.button("💾 Save Draft", use_container_width=True):
                _do_save_draft(
                    thread=thread,
                    post_content=post_content,
                    selected_att_labels=selected_att_labels,
                    label_to_att=label_to_att,
                    selected_member_labels=(
                        selected_member_labels if selected_member_labels else []
                    ),
                    member_map=member_map,
                    active_stored=active_stored,
                    new_uploads=new_uploads or [],
                    selected_channel=selected_channel,
                )

        # ── Send & Close ──
        with btn_col2:
            can_send = (
                bool(post_content.strip())
                or bool(selected_att_labels)
                or bool(new_uploads)
                or bool(active_stored)
            )
            if st.button(
                "📤 Send & Close Thread",
                use_container_width=True,
                type="primary",
                disabled=not can_send,
            ):
                _do_send_and_close(
                    thread=thread,
                    post_content=post_content,
                    selected_att_labels=selected_att_labels,
                    label_to_att=label_to_att,
                    selected_member_labels=(
                        selected_member_labels if selected_member_labels else []
                    ),
                    member_map=member_map,
                    active_stored=active_stored,
                    new_uploads=new_uploads or [],
                    selected_channel=selected_channel,
                )


# ===========================================================================
# Draft save logic
# ===========================================================================


def _do_save_draft(
    thread: Dict,
    post_content: str,
    selected_att_labels: List[str],
    label_to_att: Dict[str, Dict],
    selected_member_labels: List[str],
    member_map: Dict[str, Dict],
    active_stored: List[Dict],
    new_uploads: list,
    selected_channel: Optional[Dict],
) -> None:
    existing_draft = st.session_state.current_draft or {}
    draft_id = existing_draft.get("id", None)

    # Build a placeholder draft to get an ID for file storage
    placeholder = {"id": draft_id} if draft_id else {}
    temp_id = dm.save_draft(placeholder)

    # Save new uploads to disk
    stored: List[Dict] = list(active_stored)
    for uf in new_uploads:
        data = uf.read()
        path = dm.store_draft_file(temp_id, uf.name, data)
        stored.append(
            {
                "filename": uf.name,
                "stored_path": path,
                "size": len(data),
                "content_type": uf.type or "",
            }
        )

    # Build selected Discord attachments list
    selected_discord = []
    for lbl in selected_att_labels:
        att = label_to_att.get(lbl)
        if att:
            selected_discord.append(
                {
                    "url": att["url"],
                    "filename": att["filename"],
                    "size": att.get("size", 0),
                    "content_type": att.get("content_type", ""),
                    "id": att["id"],
                }
            )

    draft = {
        "id": temp_id,
        "status": "draft",
        "thread_id": thread["id"],
        "thread_name": thread.get("name", "Untitled"),
        "guild_id": GUILD_ID,
        "guild_name": GUILD_NAME,
        "target_channel_id": selected_channel["id"] if selected_channel else "",
        "target_channel_name": selected_channel["name"] if selected_channel else "",
        "post_content": post_content,
        "selected_discord_attachments": selected_discord,
        "local_uploads": stored,
        "tagged_member_ids": [
            dh.build_mention(member_map[lbl]).strip("<@>")
            for lbl in selected_member_labels
            if lbl in member_map
        ],
        "tagged_member_labels": selected_member_labels,
        "created_by_email": USER_EMAIL,
        "created_by_name": USER_NAME,
    }
    # Preserve original created_at
    if existing_draft.get("created_at"):
        draft["created_at"] = existing_draft["created_at"]

    dm.save_draft(draft)
    st.session_state.current_draft = draft
    st.success("✅ Draft saved successfully!")


# ===========================================================================
# Send & Close logic
# ===========================================================================


def _do_send_and_close(
    thread: Dict,
    post_content: str,
    selected_att_labels: List[str],
    label_to_att: Dict[str, Dict],
    selected_member_labels: List[str],
    member_map: Dict[str, Dict],
    active_stored: List[Dict],
    new_uploads: list,
    selected_channel: Optional[Dict],
) -> None:
    if not selected_channel:
        st.error("❌ Please select a target channel before sending.")
        return

    files_to_send: List[Tuple[str, bytes]] = []
    errors: List[str] = []

    # 1. Download Discord CDN attachments
    with st.spinner("Downloading thread attachments..."):
        for lbl in selected_att_labels:
            att = label_to_att.get(lbl)
            if not att:
                continue
            data = dh.download_attachment(att["url"])
            if data is None:
                errors.append(
                    f"Could not download: {att['filename']} (URL may have expired)"
                )
            else:
                files_to_send.append((att["filename"], data))

    # 2. Read stored draft files
    for upload in active_stored:
        data = dm.load_draft_file(upload["stored_path"])
        if data is None:
            errors.append(f"Stored file missing: {upload['filename']}")
        else:
            files_to_send.append((upload["filename"], data))

    # 3. Read new in-session uploads
    for uf in new_uploads:
        files_to_send.append((uf.name, uf.read()))

    if errors:
        for err in errors:
            st.warning(f"⚠️ {err}")

    # 4. Send the message
    with st.spinner(f"Sending post to #{selected_channel['name']}..."):
        try:
            sent = dh.send_message(
                TOKEN,
                selected_channel["id"],
                post_content,
                files_to_send if files_to_send else None,
            )
        except requests.HTTPError as e:
            st.error(
                f"❌ Discord rejected the post ({e.response.status_code}): {e.response.text}"
            )
            return
        except requests.RequestException as e:
            st.error(f"❌ Failed to reach Discord: {e}")
            return

    # 5. Apply 'Closed' tag and strip any configured open-state tags
    with st.spinner("Closing forum thread..."):
        closed_ok = dh.apply_closed_tag(
            TOKEN, thread, also_remove_names=TAGS_TO_REMOVE_ON_CLOSE or None
        )
        if not closed_ok:
            st.warning(
                "⚠️ Post sent, but could not apply the 'Closed' tag to the forum thread. "
                "The forum may not have a 'Closed' tag configured, or the bot may lack "
                "MANAGE_THREADS permission."
            )

    # 6. Persist post record
    existing_draft = st.session_state.current_draft or {}
    post = {
        "draft_id": existing_draft.get("id", ""),
        "thread_id": thread["id"],
        "thread_name": thread.get("name", "Untitled"),
        "guild_id": GUILD_ID,
        "guild_name": GUILD_NAME,
        "channel_id": selected_channel["id"],
        "channel_name": selected_channel["name"],
        "discord_message_id": sent["id"],
        "post_content": post_content,
        "posted_by_email": USER_EMAIL,
        "posted_by_name": USER_NAME,
    }
    dm.save_post(post)

    # 7. Delete draft
    if existing_draft.get("id"):
        dm.delete_draft(existing_draft["id"])

    # 8. Invalidate thread cache so queue refreshes
    dh.fetch_active_threads.clear()

    st.success(
        f"✅ Post sent to **#{selected_channel['name']}** and thread marked as Closed!"
    )
    st.balloons()

    # Return to queue after a moment
    st.session_state.view = "queue"
    st.session_state.selected_thread = None
    st.session_state.current_draft = None
    st.rerun()


# ===========================================================================
# View routing
# ===========================================================================

if st.session_state.view == "editor" and st.session_state.selected_thread:
    show_editor()
else:
    st.session_state.view = "queue"
    show_queue()

st.divider()
st.markdown(
    "<div style='text-align:center;color:gray;padding:10px'>"
    "<small>Penalty Posts | Discord REST API &amp; Streamlit</small>"
    "</div>",
    unsafe_allow_html=True,
)
