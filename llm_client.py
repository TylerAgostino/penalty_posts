"""LLM client for Penalty Posts - uses Ollama with Strands Agents harness SDK."""

import json
import os
from typing import Dict, List, Optional

from strands import Agent
from strands.models.ollama import OllamaModel

# Default configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://192.168.1.152:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "hf.co/unsloth/Qwen3-Coder-Next-GGUF:UD-Q4_K_M")


def _format_thread_conversation(messages: List[Dict]) -> str:
    """Format thread messages into a conversation string for the prompt."""
    lines = []
    for msg in messages:
        author = msg.get("author", {})
        name = author.get("username", "Unknown")
        content = msg.get("content", "")
        if content:
            lines.append(f"{name}: {content}")
    return "\n\n".join(lines)


def _load_few_shot_examples_from_discord(
    token: str, example_message_ids: List[str]
) -> List[Dict]:
    """
    Load few-shot examples from Discord message IDs.

    Args:
        token: Discord bot token
        example_message_ids: List of message IDs containing examples

    Returns:
        List of example dicts with 'conversation' and 'expected_post' keys
    """
    import discord_helpers as dh

    examples = []
    for msg_id in example_message_ids:
        try:
            # Fetch the message from Discord
            # Note: We need to construct channel_id - this would come from a configuration
            # For now, we'll assume messages are stored with their channel context
            msg = dh.fetch_single_message(token, 1239988445326348460, msg_id)
            if msg and msg.get("content"):
                content = msg.get("content", "")

                # Parse CONVERSATION: and EXPECTED_OUTPUT: markers
                if "CONVERSATION:" in content and "EXPECTED_OUTPUT:" in content:
                    parts = content.split("EXPECTED_OUTPUT:")
                    conversation_part = parts[0].replace("CONVERSATION:", "").strip()
                    expected_post = parts[1].strip() if len(parts) > 1 else ""

                    examples.append(
                        {
                            "conversation": conversation_part,
                            "expected_post": expected_post,
                        }
                    )
                else:
                    # Fallback: use entire message content as conversation example
                    examples.append({"conversation": content, "expected_post": ""})
        except Exception as e:
            import streamlit as st

            st.warning(f"Failed to load example message {msg_id}: {e}")
            continue

    return examples


def _load_few_shot_examples_from_files() -> List[Dict[str, str]]:
    """Load few-shot examples from the examples directory (fallback)."""
    examples_dir = os.path.join(os.path.dirname(__file__), "data", "few_shot_examples")

    if not os.path.exists(examples_dir):
        return []

    examples = []
    for filename in sorted(os.listdir(examples_dir)):
        if filename.endswith(".json"):
            try:
                with open(
                    os.path.join(examples_dir, filename), "r", encoding="utf-8"
                ) as f:
                    example = json.load(f)
                    if "conversation" in example and "expected_post" in example:
                        examples.append(example)
            except (json.JSONDecodeError, OSError):
                continue

    return examples


def _extract_race_identifier_from_tags(thread: Dict) -> str:
    """
    Extract race identifier from thread tags.

    Looks for tags that match patterns like:
    - S##R# (e.g., S24R1, S25R2)
    - Race X of Y
    - Event X

    Returns a formatted identifier or placeholder if not found.
    """
    import re

    forum_channel = thread.get("_forum_channel", {})
    applied_tag_ids = thread.get("applied_tags", [])

    # Get tag name map from the forum channel
    available_tags = forum_channel.get("available_tags", [])
    tag_map = {str(tag["id"]): tag["name"].upper() for tag in available_tags}

    # Check each applied tag for race identifier patterns
    for tag_id in applied_tag_ids:
        tag_name = tag_map.get(str(tag_id), "")

        # Pattern 1: S##R# format (e.g., S24R1, S25R2)
        match = re.search(r"(S\d{2}R\d)", tag_name)
        if match:
            return match.group(1)

        # Pattern 2: "Round X" or "Race X"
        match = re.search(r"(?:ROUND|RACE)\s*(\d+)", tag_name, re.IGNORECASE)
        if match:
            round_num = match.group(1)
            return f"S##R{round_num}"

    # If no race identifier found, return obvious placeholder
    return "S##R# - Track Name - Feature Lap #"


def _build_generation_prompt(
    conversation: str, examples: List[Dict[str, str]], race_identifier: str = ""
) -> str:
    """Build the prompt for post generation with few-shot examples."""

    system_prompt = f"""You are an expert at writing incident summary posts for a motorsport penalty forum.
Your task is to analyze a thread conversation and write a structured incident report.

The output must follow this exact format:

## Event: {race_identifier}

### Driver(s)

### Incident(s)

### Decision(s)
**__No Action__**

Instructions:
1. Use the race identifier provided above
2. Identify which drivers were involved in the incident
3. Summarize what happened during the incident clearly and concisely
4. State the official decision/penalty if one was made.
5. If no penalty was issued, use "__No Action__"
6. Keep each section factual and focused on the incident details
7. The thread conversation is private among the stewards, not the general community. These stewards may also be involved in the incidents, but not always. Do not reference individual members of the discussions or their opinions"""

    # Build few-shot examples section
    examples_section = ""
    for i, example in enumerate(examples[:3], 1):  # Limit to 3 examples
        examples_section += f"\n\n--- EXAMPLE {i} ---\n"
        examples_section += f"Conversation:\n{example['conversation']}\n\n"
        if example.get("expected_post"):
            examples_section += f"Expected Output:\n{example['expected_post']}"

    user_prompt = f"""Analyze the following Discord thread conversation and write an incident summary post.

{examples_section}

Here is the actual thread conversation:

{conversation}

Please generate the incident report in the required format."""

    return f"{system_prompt}\n\n{user_prompt}"


def _build_agent(system_prompt: str) -> Agent:
    """
    Build a Strands Agent with Ollama model.

    Uses cached model configuration for consistent behavior.
    """
    # Create the Ollama model
    ollama_model = OllamaModel(
        host=OLLAMA_BASE_URL,
        model_id=OLLAMA_MODEL,
        temperature=0.3,  # Low temperature for more consistent outputs
        options={"num_ctx": 8192},  # Large context window
    )

    # Create agent with system prompt (no tools needed for this task)
    agent = Agent(model=ollama_model, system_prompt=system_prompt)

    return agent


def generate_post_from_thread(
    messages: List[Dict],
    thread: Dict,
    token: str = "",
    example_message_ids: Optional[List[str]] = None,
) -> Optional[str]:
    """
    Generate a post draft using LLM based on thread conversation.

    Args:
        messages: List of Discord message objects from the thread
        thread: Thread object containing tag information
        token: Discord bot token (optional, for loading examples)
        example_message_ids: List of Discord message IDs for few-shot examples

    Returns:
        Generated post content as string, or None if generation failed
    """
    import streamlit as st

    if not messages:
        return None

    # Extract race identifier from thread tags
    race_identifier = _extract_race_identifier_from_tags(thread)

    # Format the conversation
    conversation = _format_thread_conversation(messages)

    # Load few-shot examples - try Discord first, then fall back to files
    examples: List[Dict[str, str]] = []

    if example_message_ids is not None and token:
        examples = _load_few_shot_examples_from_discord(token, example_message_ids)

    # Fall back to file-based examples if we don't have enough from Discord
    if len(examples) < 1:
        examples.extend(_load_few_shot_examples_from_files())

    # If still no examples, use an empty list (LLM will generate based on instructions)

    # Build prompt with race identifier
    full_prompt = _build_generation_prompt(conversation, examples, race_identifier)

    try:
        # Build the agent
        agent = _build_agent(full_prompt)

        # Invoke the agent to generate the post
        response = agent(
            "Generate the incident report based on the instructions above."
        )
        return response.message.get('content')[0].get('text') if response else None

    except Exception as e:
        st.error(f"❌ LLM generation failed: {e}")
        return None


def generate_post_for_thread(
    messages: List[Dict],
    thread: Dict,
    token: str = "",
    example_message_ids: Optional[List[str]] = None,
) -> Optional[str]:
    """
    Wrapper for generate_post_from_thread with better error handling.

    This is the main entry point for post generation.
    Returns None if there's an error or no data.
    """
    try:
        return generate_post_from_thread(messages, thread, token, example_message_ids)
    except Exception as e:
        # Catch any unexpected errors
        import streamlit as st

        st.error(f"Unexpected error during post generation: {e}")
        return None
