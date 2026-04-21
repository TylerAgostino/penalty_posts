import io
import os
from typing import Dict, List, Optional, Tuple

import requests
import streamlit as st

# Discord REST API base URL
DISCORD_API_BASE = "https://discord.com/api/v10"

# Page configuration
st.set_page_config(page_title="Discord Post Manager", page_icon="📝", layout="wide")

# Check authentication
if not st.user or not st.user.is_logged_in:
    st.error("🔒 Authentication Required")
    st.info(
        "Please sign in with your Google account to access the Discord Post Manager."
    )
    if st.button("🔐 Log in with Google"):
        st.login()
    st.stop()

# Display user info in sidebar
with st.sidebar:
    st.write("👤 **Signed in as:**")
    st.write(f"**Name:** {st.user.get('name', 'N/A')}")
    st.write(f"**Email:** {st.user.get('email', 'N/A')}")
    if st.button("🚪 Logout"):
        st.logout()
    st.divider()


# ---------------------------------------------------------------------------
# Discord REST helpers
# ---------------------------------------------------------------------------


def _bot_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bot {token}"}


@st.cache_data(ttl=60, show_spinner=False)
def fetch_bot_user(token: str) -> Dict:
    """Fetch the bot's own user object to verify connectivity."""
    r = requests.get(f"{DISCORD_API_BASE}/users/@me", headers=_bot_headers(token))
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=300, show_spinner=False)
def fetch_guilds(token: str) -> List[Dict]:
    """Fetch guilds the bot belongs to, optionally filtered by ALLOWED_GUILD_IDS."""
    r = requests.get(
        f"{DISCORD_API_BASE}/users/@me/guilds", headers=_bot_headers(token)
    )
    r.raise_for_status()
    guilds: List[Dict] = r.json()

    allowed_str = os.getenv("ALLOWED_GUILD_IDS", "").strip()
    if allowed_str:
        try:
            allowed_ids = {
                int(gid.strip()) for gid in allowed_str.split(",") if gid.strip()
            }
            guilds = [g for g in guilds if int(g["id"]) in allowed_ids]
        except ValueError:
            st.error(
                "❌ Invalid ALLOWED_GUILD_IDS format. Must be comma-separated numeric guild IDs."
            )
            return []

    return guilds


@st.cache_data(ttl=300, show_spinner=False)
def fetch_channels(token: str, guild_id: str) -> List[Dict]:
    """Fetch text/announcement channels for a guild, sorted by position."""
    r = requests.get(
        f"{DISCORD_API_BASE}/guilds/{guild_id}/channels", headers=_bot_headers(token)
    )
    r.raise_for_status()
    channels: List[Dict] = r.json()
    # Type 0 = GUILD_TEXT, Type 5 = GUILD_ANNOUNCEMENT
    text_channels = [c for c in channels if c.get("type") in (0, 5)]
    return sorted(text_channels, key=lambda c: c.get("position", 0))


@st.cache_data(ttl=300, show_spinner=False)
def fetch_members(token: str, guild_id: str) -> List[Dict]:
    """Fetch all non-bot members of a guild with automatic pagination."""
    headers = _bot_headers(token)
    members: List[Dict] = []
    after: Optional[str] = None

    while True:
        params: Dict = {"limit": 1000}
        if after:
            params["after"] = after

        r = requests.get(
            f"{DISCORD_API_BASE}/guilds/{guild_id}/members",
            headers=headers,
            params=params,
        )
        r.raise_for_status()
        batch: List[Dict] = r.json()

        members.extend([m for m in batch if not m["user"].get("bot", False)])

        if len(batch) < 1000:
            break
        after = batch[-1]["user"]["id"]

    return sorted(
        members,
        key=lambda m: (m.get("nick") or m["user"]["username"]).lower(),
    )


def send_message(
    token: str,
    channel_id: str,
    content: str,
    files: Optional[List[Tuple[str, bytes]]] = None,
) -> None:
    """
    Send a message (with optional file attachments) to a Discord channel.
    Raises requests.HTTPError on failure.
    """
    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
    headers = _bot_headers(token)

    if files:
        # Multipart form upload — let requests set the Content-Type boundary
        form_data: Dict[str, str] = {}
        if content:
            form_data["content"] = content

        multipart = [
            (f"files[{i}]", (name, io.BytesIO(data), "application/octet-stream"))
            for i, (name, data) in enumerate(files)
        ]
        r = requests.post(url, headers=headers, data=form_data, files=multipart)
    else:
        r = requests.post(url, headers=headers, json={"content": content})

    r.raise_for_status()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_member_label(member: Dict) -> str:
    nick = member.get("nick")
    username = member["user"]["username"]
    return f"{nick} (@{username})" if nick else f"@{username}"


def build_mention(member: Dict) -> str:
    return f"<@{member['user']['id']}>"


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------


def main():
    st.title("📝 Discord Post Manager")
    st.markdown("Post messages to Discord channels using a shared bot account")

    discord_token = os.getenv("BOT_TOKEN", "").strip()
    if not discord_token:
        st.error("❌ BOT_TOKEN environment variable not set!")
        st.info("Please set the BOT_TOKEN environment variable with your bot's token.")
        st.stop()

    # Sidebar — bot connectivity status
    with st.sidebar:
        st.header("🤖 Bot Status")
        try:
            bot_user = fetch_bot_user(discord_token)
            st.success("✅ Connected")
            st.info(f"Logged in as: **{bot_user['username']}**")
        except requests.HTTPError as e:
            st.error(
                f"❌ Discord API error: {e.response.status_code} {e.response.reason}"
            )
            st.stop()
        except requests.RequestException as e:
            st.error(f"❌ Cannot reach Discord API: {e}")
            st.stop()

        if st.button("🔄 Refresh"):
            fetch_bot_user.clear()
            fetch_guilds.clear()
            fetch_channels.clear()
            fetch_members.clear()
            st.rerun()

    # Main content
    with st.container():
        st.header("Create Post")

        try:
            guilds = fetch_guilds(discord_token)

            if not guilds:
                st.warning(
                    "The bot is not in any servers (or none match ALLOWED_GUILD_IDS). "
                    "Please invite the bot to a server first."
                )
                st.stop()

            guild_map = {g["name"]: g for g in guilds}
            selected_guild_name = st.selectbox(
                "Select Server (Guild)",
                options=list(guild_map.keys()),
                help="Choose the Discord server to post to",
            )

            if not selected_guild_name:
                st.stop()

            selected_guild = guild_map[selected_guild_name]
            channels = fetch_channels(discord_token, selected_guild["id"])

            if not channels:
                st.warning(f"No text channels found in **{selected_guild_name}**.")
                st.stop()

            channel_map = {c["name"]: c for c in channels}
            selected_channel_name = st.selectbox(
                "Select Channel",
                options=list(channel_map.keys()),
                help="Choose the channel to post to",
            )

            if not selected_channel_name:
                st.stop()

            selected_channel = channel_map[selected_channel_name]

            # Message content
            st.subheader("Message Content")

            with st.expander("🏷️ Tag Members", expanded=False):
                members = fetch_members(discord_token, selected_guild["id"])

                if not members:
                    st.info(
                        "No members found. Make sure the bot has the **Server Members Intent** "
                        "enabled in the Discord Developer Portal."
                    )
                else:
                    st.caption(
                        f"{len(members)} member(s) in **{selected_guild_name}**. "
                        "Select one or more to insert their mention(s) into the message."
                    )

                    member_map = {format_member_label(m): m for m in members}
                    selected_labels = st.multiselect(
                        "Search and select members to tag",
                        options=list(member_map.keys()),
                        placeholder="Type a name to search...",
                        help="Selected members will be inserted as mentions into your message.",
                    )

                    if selected_labels:
                        mention_preview = " ".join(
                            build_mention(member_map[label])
                            for label in selected_labels
                        )
                        st.code(mention_preview)
                        st.caption(
                            "👆 This is how the mentions will appear in your message."
                        )

                        if st.button("➕ Insert Mentions into Message"):
                            existing = st.session_state.get("post_content", "")
                            separator = (
                                " " if existing and not existing.endswith(" ") else ""
                            )
                            st.session_state["post_content"] = (
                                existing + separator + mention_preview
                            )
                            st.rerun()

            message_content = st.text_area(
                "Post Content",
                height=200,
                placeholder="Write your message here...",
                help="Enter the text content of your post. Use the 'Tag Members' section above to insert mentions.",
                key="post_content",
            )

            # File uploads
            st.subheader("Attachments")
            uploaded_files = st.file_uploader(
                "Upload files (images, videos, gifs, etc.)",
                accept_multiple_files=True,
                help="Upload files to attach to your post",
            )

            if uploaded_files:
                st.write("**Selected files:**")
                for f in uploaded_files:
                    st.write(f"- {f.name} ({f.size / (1024 * 1024):.2f} MB)")

            # Submit
            col1, _ = st.columns([1, 4])
            with col1:
                submit = st.button(
                    "📤 Send Post", type="primary", use_container_width=True
                )

            if submit:
                if not message_content and not uploaded_files:
                    st.error(
                        "Please enter message content or upload at least one file."
                    )
                else:
                    with st.spinner("Sending message to Discord..."):
                        files_to_send = (
                            [(f.name, f.read()) for f in uploaded_files]
                            if uploaded_files
                            else None
                        )
                        try:
                            send_message(
                                discord_token,
                                selected_channel["id"],
                                message_content,
                                files_to_send,
                            )
                            st.success(
                                f"✅ Message sent successfully to "
                                f"**#{selected_channel_name}** in **{selected_guild_name}**!"
                            )
                            st.balloons()
                        except requests.HTTPError as e:
                            st.error(
                                f"❌ Discord rejected the message "
                                f"({e.response.status_code}): {e.response.text}"
                            )
                        except requests.RequestException as e:
                            st.error(f"❌ Failed to send message: {e}")

        except requests.HTTPError as e:
            st.error(
                f"❌ Discord API error ({e.response.status_code}): {e.response.text}"
            )
        except Exception as e:
            st.error(f"An unexpected error occurred: {e}")
            st.exception(e)

    st.divider()
    st.markdown(
        "<div style='text-align: center; color: gray; padding: 20px;'>"
        "<small>Discord Post Manager | Discord REST API &amp; Streamlit</small>"
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
