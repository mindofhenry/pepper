"""Anthropic Haiku client. Generates book discussion prompts."""
import json
import logging
from typing import Optional

from anthropic import AsyncAnthropic

import config

log = logging.getLogger("bookclub.anthropic")

# Haiku is cheapest and plenty smart for short prompt generation.
MODEL = "claude-haiku-4-5-20251001"

_client: Optional[AsyncAnthropic] = None


def _get_client() -> AsyncAnthropic:
    """Lazy-init the Anthropic client on first use."""
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


async def generate_discussion_prompts(
    title: str,
    authors: list[str],
    end_chapter: Optional[int],
    end_page: Optional[int],
) -> list[str]:
    """Generate 4 discussion prompts for a book section. Returns list of prompt strings."""
    author_str = ", ".join(authors) if authors else "unknown author"
    if end_chapter and end_page:
        endpoint = f"through chapter {end_chapter} (page {end_page})"
    elif end_chapter:
        endpoint = f"through chapter {end_chapter}"
    else:
        endpoint = f"through page {end_page}"

    system = (
        "You generate discussion prompts for a small friends' book club. "
        "Prompts should be open-ended, thoughtful, and specific to the book. "
        "Avoid generic questions that work for any book. "
        "Avoid spoilers beyond the reading section. "
        "Return JSON only, no prose."
    )
    user = (
        f"Book: {title} by {author_str}\n"
        f"Reading section: {endpoint}\n\n"
        f"Generate exactly 4 discussion prompts for this section. "
        f"Return JSON in this exact format:\n"
        f'{{"prompts": ["prompt 1", "prompt 2", "prompt 3", "prompt 4"]}}'
    )

    client = _get_client()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=800,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    # Haiku returns content as a list of blocks; take the first text block.
    text = ""
    for block in response.content:
        if block.type == "text":
            text = block.text
            break

    # Strip markdown fences if Haiku wraps the JSON.
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        data = json.loads(text)
        prompts = data.get("prompts", [])
        if not isinstance(prompts, list) or not all(isinstance(p, str) for p in prompts):
            raise ValueError("prompts field malformed")
        return prompts
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("Failed to parse Haiku response: %s | raw: %s", e, text[:300])
        return []
