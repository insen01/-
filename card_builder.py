"""Assemble raw LLM output into SillyTavern v2 spec character card."""
import copy

REQUIRED_FIELDS = ["name", "first_mes"]

DEFAULTS = {
    "description": "",
    "personality": "",
    "scenario": "",
    "mes_example": "",
    "system_prompt": "",
    "post_history_instructions": "",
    "tags": [],
    "creator_notes": "",
    "character_version": "1.0",
    "creator": "charcard-generator",
    "alternate_greetings": [],
}

ENTRY_DEFAULTS = {
    "enabled": True,
    "insertion_order": 0,
    "case_sensitive": False,
    "priority": 10,
    "comment": "",
    "selective": False,
    "secondary_keys": [],
    "constant": False,
    "position": "before_char",
}


def build(card_dict: dict) -> dict:
    """Normalize LLM output into a valid SillyTavern v2 character card.

    Args:
        card_dict: Raw dict from LLM, may have missing/extra fields.

    Returns:
        Clean dict conforming to SillyTavern chara_card_v2 spec.
    """
    data = copy.deepcopy(card_dict)

    # Extract _image_prompt before normalization
    image_prompt = data.pop("_image_prompt", "")

    # Validate required fields
    for field in REQUIRED_FIELDS:
        if not data.get(field):
            raise ValueError(f"Missing required field: {field}")

    # Fill defaults for optional fields
    for key, default in DEFAULTS.items():
        if key not in data or data[key] is None:
            data[key] = default

    # Normalize character_book / world book entries
    char_book = data.get("character_book", {})
    if not isinstance(char_book, dict):
        char_book = {}

    book_name = char_book.get("name", "World Book")
    book_desc = char_book.get("description", "Lorebook for this character's world")
    raw_entries = char_book.get("entries", [])

    normalized_entries = []
    for i, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            continue
        norm = copy.deepcopy(ENTRY_DEFAULTS)
        norm["id"] = i
        norm["name"] = entry.get("name", f"Entry {i}")
        norm["content"] = entry.get("content", "")
        norm["keys"] = entry.get("keys", [])
        norm["priority"] = entry.get("priority", 10)
        norm["position"] = entry.get("position", "before_char")
        norm["selective"] = entry.get("selective", False)
        norm["constant"] = entry.get("constant", False)
        norm["insertion_order"] = entry.get("insertion_order", i)
        normalized_entries.append(norm)

    data["character_book"] = {
        "name": book_name,
        "description": book_desc,
        "entries": normalized_entries,
    }

    # Wrap in spec envelope
    card = {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": data,
    }

    # Attach image prompt for downstream use (not in final spec)
    card["_image_prompt"] = image_prompt

    return card
