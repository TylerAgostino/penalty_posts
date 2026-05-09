"""Penalty Posts — Completed Posts page.

Shows all sent incident-summary posts and allows text edits
via Discord's edit-message API.

This file is loaded by the navigation entry-point (app.py).
"""

import os

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
# Session state
# ---------------------------------------------------------------------------
if "cp_editing_id" not in st.session_state:
    st.session_state.cp_editing_id = None  # post ID currently being edited


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_preview(content: str, max_chars: int = 160) -> str:
    content = content.strip()
    if len(content) <= max_chars:
        return content
    return content[:max_chars].rstrip() + "…"


def _discord_message_url(guild_id: str, channel_id: str, message_id: str) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

st.title("✅ Penalty Posts — Completed")
st.caption(
    "All sent incident-summary posts. Edit text and attachments here — "
    "changes are applied live to the Discord message."
)

posts = dm.list_posts()

if not posts:
    st.info("📭 No completed posts yet. Head to the Queue to create one.")
    st.stop()

# Search / filter
search_query = st.text_input(
    "🔍 Filter posts",
    placeholder="Search by thread name, channel, or content…",
    label_visibility="collapsed",
)
if search_query:
    q = search_query.lower()
    posts = [
        p
        for p in posts
        if q in p.get("thread_name", "").lower()
        or q in p.get("channel_name", "").lower()
        or q in p.get("post_content", "").lower()
    ]

st.caption(f"{len(posts)} post(s) found")
st.divider()

for post in posts:
    post_id = post["id"]
    thread_name = post.get("thread_name", "Untitled")
    channel_name = post.get("channel_name", "unknown")
    guild_id = post.get("guild_id", "")
    channel_id = post.get("channel_id", "")
    message_id = post.get("discord_message_id", "")
    posted_at = dh.format_timestamp(post.get("posted_at", post.get("created_at", "")))
    updated_at = post.get("updated_at", "")
    posted_by = post.get("posted_by_name", "Unknown")
    preview = _short_preview(post.get("post_content", ""))
    msg_url = _discord_message_url(guild_id, channel_id, message_id)

    with st.container(border=True):
        # Header row
        hcol_info, hcol_btns = st.columns([5, 2])

        with hcol_info:
            st.markdown(f"### {thread_name}")
            meta = [
                f"📣 `#{channel_name}`",
                f"🕐 {posted_at}",
                f"👤 {posted_by}",
            ]
            if updated_at and updated_at != post.get("posted_at"):
                meta.append(f"*edited {dh.format_timestamp(updated_at)}*")
            st.caption("  ·  ".join(meta))
            if preview:
                st.markdown(f"> {preview}")

        with hcol_btns:
            st.write("")
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                # Toggle edit panel
                is_editing = st.session_state.cp_editing_id == post_id
                edit_label = "❌ Cancel" if is_editing else "✏️ Edit"
                if st.button(
                    edit_label, key=f"toggle_edit_{post_id}", use_container_width=True
                ):
                    st.session_state.cp_editing_id = None if is_editing else post_id
                    st.rerun()
            with btn_col2:
                st.link_button(
                    "🔗 View",
                    url=msg_url,
                    use_container_width=True,
                    help="Open the original Discord message",
                )

        # Edit panel (shown when this post is selected for editing)
        if st.session_state.cp_editing_id == post_id:
            st.divider()

            # Fetch the live message from Discord (source of truth)
            with st.spinner("Loading current post from Discord..."):
                live_msg = dh.fetch_single_message(TOKEN, channel_id, message_id)

            if not live_msg:
                st.error(
                    "❌ Could not fetch the Discord message. It may have been deleted."
                )
            else:
                live_content: str = live_msg.get("content", "")
                live_attachments = live_msg.get("attachments", [])

                # ── Text editor ────────────────────────────────────────────
                st.markdown("✏️ **Post Content**")
                edited_content = st.text_area(
                    "Post content",
                    value=live_content,
                    height=200,
                    key=f"edit_content_{post_id}",
                    label_visibility="collapsed",
                )

                # ── Existing attachments ─────────────────────────────────────
                st.markdown("📎 **Current Attachments**")
                if not live_attachments:
                    st.caption("ℹ️ No attachments on this post.")
                else:
                    st.caption("Uncheck an attachment to remove it from the post.")
                    for att in live_attachments:
                        att_id = att["id"]
                        att_name = att.get("filename", "file")
                        att_size = dh.format_size(att.get("size", 0))
                        att_ct = att.get("content_type", "")
                        att_url = att.get("url", "")
                        att_proxy = att.get("proxy_url") or att_url

                        with st.container(border=True):
                            chk_col, meta_col = st.columns([1, 9])
                            with chk_col:
                                keep = st.checkbox(
                                    "Keep",
                                    value=True,
                                    key=f"keep_{post_id}_{att_id}",
                                    label_visibility="collapsed",
                                )
                            with meta_col:
                                if keep:
                                    st.markdown(f"📎 **{att_name}** ({att_size})")
                                else:
                                    st.markdown(
                                        f"~~📎 {att_name}~~ ({att_size}) — *will be removed*"
                                    )

                            if keep:
                                if att_ct.startswith("image/"):
                                    try:
                                        st.image(
                                            att_proxy,
                                            caption=att_name,
                                            use_container_width=True,
                                        )
                                    except Exception:
                                        st.markdown(f"[🔍 View image]({att_url})")
                                elif att_ct.startswith("video/"):
                                    try:
                                        st.video(att_url, format=att_ct)
                                    except Exception:
                                        st.markdown(f"[▶ Open video]({att_url})")
                                else:
                                    st.markdown(f"[📥 Download]({att_url})")

                # ── New attachments ───────────────────────────────────────────
                st.markdown("📁 **Add New Attachments**")
                new_uploads = st.file_uploader(
                    "Upload new files to add to the post",
                    accept_multiple_files=True,
                    key=f"new_files_{post_id}",
                    label_visibility="collapsed",
                )

                # ── Save button ─────────────────────────────────────────────
                st.divider()
                save_col, _ = st.columns([1, 3])
                with save_col:
                    if st.button(
                        "💾 Save Changes",
                        key=f"save_edit_{post_id}",
                        type="primary",
                        use_container_width=True,
                    ):
                        if (
                            not edited_content.strip()
                            and not live_attachments
                            and not new_uploads
                        ):
                            st.error(
                                "❌ Post must have content or at least one attachment."
                            )
                        else:
                            # Determine what actually changed
                            text_changed = edited_content != live_content

                            # Which existing attachments the user wants to keep
                            kept_ids = [
                                att["id"]
                                for att in live_attachments
                                if st.session_state.get(
                                    f"keep_{post_id}_{att['id']}", True
                                )
                            ]
                            att_removed = len(kept_ids) < len(live_attachments)
                            new_file_data = [
                                (uf.name, uf.read()) for uf in (new_uploads or [])
                            ]

                            # Decide which edit_message variant to call
                            if (
                                not text_changed
                                and not att_removed
                                and not new_file_data
                            ):
                                st.info("No changes to save.")
                            else:
                                with st.spinner("Updating post on Discord..."):
                                    try:
                                        if att_removed or new_file_data:
                                            dh.edit_message(
                                                TOKEN,
                                                channel_id,
                                                message_id,
                                                edited_content,
                                                keep_attachment_ids=kept_ids,
                                                new_files=(
                                                    new_file_data
                                                    if new_file_data
                                                    else None
                                                ),
                                            )
                                        else:
                                            dh.edit_message(
                                                TOKEN,
                                                channel_id,
                                                message_id,
                                                edited_content,
                                            )
                                    except requests.HTTPError as e:
                                        st.error(
                                            f"❌ Discord rejected the edit "
                                            f"({e.response.status_code}): {e.response.text}"
                                        )
                                        st.stop()
                                    except requests.RequestException as e:
                                        st.error(f"❌ Network error: {e}")
                                        st.stop()

                                # Update local record (text only; attachments live on Discord)
                                dm.update_post_content(post_id, edited_content)
                                dh.fetch_single_message.clear()

                                st.success("✅ Post updated on Discord!")
                                st.session_state.cp_editing_id = None
                                st.rerun()

st.divider()
st.markdown(
    "<div style='text-align:center;color:gray;padding:10px'>"
    "<small>Penalty Posts | Discord REST API &amp; Streamlit</small>"
    "</div>",
    unsafe_allow_html=True,
)
