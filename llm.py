"""SiliconFlow Chat API wrapper — generates structured character card JSON."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Optional

from . import config

SYSTEM_PROMPT = """You are a character card generator for SillyTavern. Given a character description, output valid JSON following this exact schema:

{
  "name": "character name",
  "description": "brief physical and role description (1-2 sentences)",
  "personality": "detailed personality traits, speech style, habits, MBTI if applicable",
  "scenario": "the current situation or context the character is in",
  "first_mes": "the opening dialogue/message from the character (200-500 chars, show personality, set the scene)",
  "mes_example": "<START>{{char}}: example dialogue line 1\\n<START>{{user}}: example user response\\n<START>{{char}}: example dialogue line 2",
  "system_prompt": "any special instructions for the AI playing this character (can be empty string)",
  "post_history_instructions": "instructions after chat history (can be empty string)",
  "tags": ["tag1", "tag2", "tag3"],
  "creator_notes": "notes about this character card",
  "character_version": "1.0",
  "creator": "charcard-generator",
  "alternate_greetings": [],
  "character_book": {
    "name": "World Book",
    "description": "Lorebook for this character's world",
    "entries": [
      {
        "keys": ["keyword1"],
        "content": "lore entry content about this topic",
        "enabled": true,
        "insertion_order": 0,
        "case_sensitive": false,
        "name": "Entry name",
        "priority": 10,
        "id": 0,
        "comment": "",
        "selective": false,
        "secondary_keys": [],
        "constant": false,
        "position": "before_char"
      }
    ]
  },
  "_image_prompt": "detailed anime-style image generation prompt for the character portrait, describing pose, clothing, background, art style, lighting, camera angle"
}

Rules:
- Generate world book entries based on character complexity. No hard limit — simpler characters may have 2-3, complex worlds 8-12.
- first_mes must be engaging and establish the character's personality immediately.
- _image_prompt should be detailed, in English, optimized for anime-style diffusion models, include: art style, character appearance, pose, clothing, background, lighting, camera angle.
- Output ONLY the JSON object, no markdown fences, no explanation.
- All JSON fields must be present, even if empty string/empty array."""

RETRY_SYSTEM_PROMPT = """You are a character card generator. Your previous response was not valid JSON.
Output ONLY valid JSON following the schema below. No markdown, no code fences, no extra text.
Start your response with '{' and end with '}'."""


def generate_card(description: str, model: Optional[str] = None) -> dict:
    """Generate a complete character card from a text description.

    Args:
        description: Character background and description text.
        model: SiliconFlow model ID. Defaults to config.DEFAULT_LLM_MODEL.

    Returns:
        Complete character card dict following SillyTavern v2 spec.
    """
    if not config.SILICONFLOW_API_KEY:
        raise RuntimeError("SILICONFLOW_API_KEY not set")

    model = model or config.DEFAULT_LLM_MODEL
    user_prompt = f"Create a character card for: {description}"

    # First attempt
    try:
        return _call_api(user_prompt, model, SYSTEM_PROMPT)
    except (ValueError, json.JSONDecodeError):
        # Retry with stronger constraints
        return _call_api(user_prompt, model, RETRY_SYSTEM_PROMPT)


def _call_api(user_prompt: str, model: str, system_prompt: str) -> dict:
    """Single API call with JSON parsing."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": config.LLM_TEMPERATURE,
        "max_tokens": config.LLM_MAX_TOKENS,
    }

    url = f"{config.SILICONFLOW_BASE}/chat/completions"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {config.SILICONFLOW_API_KEY}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=config.LLM_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"LLM API HTTP {e.code}: {err_body[:500]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM API network error: {e.reason}")

    # Parse API response JSON
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"LLM API returned non-JSON response: {raw[:200]}")

    content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    content = content.strip()

    # Guard against empty content
    if not content:
        raise ValueError("LLM returned empty content")

    # Strip markdown fences if present
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    try:
        result = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM output not valid JSON: {e}")

    # Validate required fields
    if not result.get("name") or not result.get("first_mes"):
        raise ValueError("LLM output missing required fields: name and first_mes must be non-empty")

    return result
