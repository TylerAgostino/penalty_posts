import asyncio
import io
import os
import threading
from typing import List, Optional

import discord
import streamlit as st

# Page configuration
st.set_page_config(page_title="Discord Post Manager", page_icon="📝", layout="wide")

# Check authentication
# Note: st.user is a dict-like object. If empty, user is not logged in.
# OIDC is available in Streamlit 1.40.0+ when configured in .streamlit/config.toml
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


# Global bot client and connection state
@st.cache_resource
def get_bot_state():
    """Initialize and return bot state dictionary"""
    return {
        "client": None,
        "ready": False,
        "connected": False,
        "user": None,
        "error": None,
        "loop": None,
        "thread": None,
    }


def start_bot_background(token, state):
    """Start the Discord bot in a background thread"""

    async def run_bot():
        intents = discord.Intents.default()
        intents.guilds = True
        intents.messages = True
        intents.members = True

        client = discord.Client(intents=intents)
        state["client"] = client

        @client.event
        async def on_ready():
            state["ready"] = True
            state["connected"] = True
            state["user"] = client.user

        @client.event
        async def on_disconnect():
            state["connected"] = False

        @client.event
        async def on_resumed():
            state["connected"] = True

        try:
            await client.start(token)
        except Exception as e:
            state["error"] = str(e)
            state["ready"] = False
            state["connected"] = False

    # Create new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    state["loop"] = loop

    try:
        loop.run_until_complete(run_bot())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


# Get guilds synchronously
def get_guilds(client):
    """Get list of guilds the bot is in, filtered by ALLOWED_GUILD_IDS if set"""
    if client and client.is_ready():
        guilds = client.guilds

        # Check if guild filtering is enabled
        allowed_guild_ids_str = os.getenv("ALLOWED_GUILD_IDS")
        if allowed_guild_ids_str:
            try:
                # Parse comma-separated guild IDs
                allowed_guild_ids = [
                    int(guild_id.strip())
                    for guild_id in allowed_guild_ids_str.split(",")
                    if guild_id.strip()
                ]
                # Filter guilds by allowed IDs
                guilds = [guild for guild in guilds if guild.id in allowed_guild_ids]
            except ValueError:
                st.error(
                    "❌ Invalid ALLOWED_GUILD_IDS format. Must be comma-separated numeric guild IDs."
                )
                return []

        return guilds
    return []


# Get channels in a guild
def get_channels(guild):
    """Get text channels in a guild"""
    return [
        channel
        for channel in guild.channels
        if isinstance(channel, discord.TextChannel)
    ]


def get_guild_members(guild):
    """Get non-bot members of a guild, sorted by display name"""
    if not guild:
        return []
    return sorted(
        [member for member in guild.members if not member.bot],
        key=lambda m: m.display_name.lower(),
    )


def format_member_label(member):
    """Format a member for display in the selector"""
    if member.nick:
        return f"{member.nick} (@{member.name})"
    return f"@{member.name}"


def build_mention(member):
    """Build a Discord mention string for a member"""
    return f"<@{member.id}>"


# Send message to Discord
async def send_discord_message(
    client, channel_id: int, content: str, files: Optional[List] = None
):
    """Send a message to a Discord channel"""
    if not client or not client.is_ready():
        return False

    channel = client.get_channel(channel_id)
    if not channel:
        return False

    try:
        discord_files = []
        if files:
            for file_info in files:
                file_name, file_bytes = file_info
                discord_file = discord.File(io.BytesIO(file_bytes), filename=file_name)
                discord_files.append(discord_file)

        if content or discord_files:
            await channel.send(
                content=content if content else None, files=discord_files
            )
            return True
        else:
            return False
    except Exception as e:
        st.error(f"Failed to send message: {e}")
        return False


def run_async_in_bot_loop(state, coro):
    """Run a coroutine in the bot's event loop"""
    if not state["loop"] or not state["client"]:
        return None

    future = asyncio.run_coroutine_threadsafe(coro, state["loop"])
    try:
        return future.result(timeout=30)
    except Exception as e:
        st.error(f"Error executing async operation: {e}")
        return None


# Main app
def main():
    st.title("📝 Discord Post Manager")
    st.markdown("Post messages to Discord channels using a shared bot account")

    # Get Discord token from environment
    discord_token = os.getenv("BOT_TOKEN")

    if not discord_token:
        st.error("❌ BOT_TOKEN environment variable not set!")
        st.info("Please set the BOT_TOKEN environment variable with your bot's token")
        st.stop()

    # Get bot state
    state = get_bot_state()

    # Start bot if not already started
    if state["thread"] is None:
        state["thread"] = threading.Thread(
            target=start_bot_background, args=(discord_token, state), daemon=True
        )
        state["thread"].start()
        # Give it a moment to start
        import time

        time.sleep(2)

    # Status indicator (sidebar already has user info at top)
    with st.sidebar:
        st.header("🤖 Bot Status")

        if state["error"]:
            st.error(f"❌ Error: {state['error']}")
        elif state["ready"] and state["connected"]:
            st.success("✅ Connected")
            if state["user"]:
                st.info(f"Logged in as: {state['user'].name}")
        elif state["thread"] and state["thread"].is_alive():
            st.warning("⏳ Connecting...")
        else:
            st.error("❌ Not connected")

        # Refresh button
        if st.button("🔄 Refresh Status"):
            st.rerun()

    # Main form
    with st.container():
        st.header("Create Post")

        # Check if bot is ready
        if not state["ready"] or not state["client"]:
            st.warning("⏳ Waiting for bot to connect...")
            st.info(
                "The bot is connecting to Discord. This may take a few seconds. Click 'Refresh Status' in the sidebar."
            )

            if st.button("🔄 Retry Connection"):
                st.rerun()

            st.stop()

        # Fetch guilds
        try:
            client = state["client"]
            guilds = get_guilds(client)

            if not guilds:
                st.warning(
                    "Bot is not in any servers. Please invite the bot to a server first."
                )
                st.info(
                    "Make sure you've invited the bot to at least one Discord server. "
                    "Check the README for instructions on how to invite the bot."
                )
                st.stop()

            # Guild selection
            guild_names = {guild.name: guild for guild in guilds}
            selected_guild_name = st.selectbox(
                "Select Server (Guild)",
                options=list(guild_names.keys()),
                help="Choose the Discord server to post to",
            )

            if selected_guild_name:
                selected_guild = guild_names[selected_guild_name]

                # Channel selection
                channels = get_channels(selected_guild)

                if not channels:
                    st.warning(f"No text channels found in {selected_guild_name}")
                    st.stop()

                channel_names = {channel.name: channel for channel in channels}
                selected_channel_name = st.selectbox(
                    "Select Channel",
                    options=list(channel_names.keys()),
                    help="Choose the channel to post to",
                )

                if selected_channel_name:
                    selected_channel = channel_names[selected_channel_name]

                    # Message content
                    st.subheader("Message Content")

                    # Member tagging section
                    with st.expander("🏷️ Tag Members", expanded=False):
                        members = get_guild_members(selected_guild)

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

                            selected_member_labels = st.multiselect(
                                "Search and select members to tag",
                                options=list(member_map.keys()),
                                placeholder="Type a name to search...",
                                help="Selected members will be inserted as mentions at the end of your message when you click 'Insert Mentions'.",
                            )

                            if selected_member_labels:
                                mention_preview = " ".join(
                                    build_mention(member_map[label])
                                    for label in selected_member_labels
                                )
                                st.code(mention_preview, language=None)
                                st.caption(
                                    "👆 This is how the mentions will appear in your message."
                                )

                                if st.button("➕ Insert Mentions into Message"):
                                    existing = st.session_state.get("post_content", "")
                                    separator = (
                                        " "
                                        if existing and not existing.endswith(" ")
                                        else ""
                                    )
                                    st.session_state["post_content"] = (
                                        existing + separator + mention_preview
                                    )
                                    st.rerun()

                    message_content = st.text_area(
                        "Post Content",
                        height=200,
                        placeholder="Write your message here...",
                        help="Enter the text content of your post. Use the 'Tag Members' section above to insert member mentions.",
                        key="post_content",
                    )

                    # File uploads
                    st.subheader("Attachments")
                    uploaded_files = st.file_uploader(
                        "Upload files (images, videos, gifs, etc.)",
                        accept_multiple_files=True,
                        help="Upload files to attach to your post",
                    )

                    # Display file info
                    if uploaded_files:
                        st.write("**Selected files:**")
                        for file in uploaded_files:
                            file_size_mb = file.size / (1024 * 1024)
                            st.write(f"- {file.name} ({file_size_mb:.2f} MB)")

                    # Submit button
                    col1, col2 = st.columns([1, 4])
                    with col1:
                        submit_button = st.button(
                            "📤 Send Post", type="primary", use_container_width=True
                        )

                    if submit_button:
                        if not message_content and not uploaded_files:
                            st.error(
                                "Please enter message content or upload at least one file"
                            )
                        else:
                            with st.spinner("Sending message to Discord..."):
                                # Prepare files
                                files_to_send = []
                                if uploaded_files:
                                    for file in uploaded_files:
                                        file_bytes = file.read()
                                        files_to_send.append((file.name, file_bytes))

                                # Send message using bot's event loop
                                success = run_async_in_bot_loop(
                                    state,
                                    send_discord_message(
                                        client,
                                        selected_channel.id,
                                        message_content,
                                        files_to_send if files_to_send else None,
                                    ),
                                )

                                if success:
                                    st.success(
                                        f"✅ Message sent successfully to #{selected_channel_name} in {selected_guild_name}!"
                                    )
                                    st.balloons()
                                else:
                                    st.error(
                                        "Failed to send message. Please check bot permissions and try again."
                                    )

        except Exception as e:
            st.error(f"An error occurred: {e}")
            st.exception(e)

    # Footer
    st.divider()
    st.markdown(
        """
        <div style='text-align: center; color: gray; padding: 20px;'>
            <small>Discord Post Manager | Using py-cord & Streamlit</small>
        </div>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
