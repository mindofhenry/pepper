"""Google Books API client. Thin wrapper around the REST endpoint."""
import logging
from typing import Optional, TypedDict

import aiohttp

import config

log = logging.getLogger("pepper.services.google_books")

BASE_URL = "https://www.googleapis.com/books/v1/volumes"


class BookResult(TypedDict):
    """Normalized book data we care about. Ignores fields we don't use."""
    google_id: str
    title: str
    authors: list[str]
    description: Optional[str]
    page_count: Optional[int]
    thumbnail_url: Optional[str]
    info_link: Optional[str]
    published_date: Optional[str]


def _parse_volume(volume: dict) -> BookResult:
    """Extract the fields we care about from a Google Books volume response."""
    info = volume.get("volumeInfo", {})
    image_links = info.get("imageLinks", {})
    return BookResult(
        google_id=volume.get("id", ""),
        title=info.get("title", "Unknown title"),
        authors=info.get("authors", []),
        description=info.get("description"),
        page_count=info.get("pageCount"),
        # Google returns http URLs; Discord embeds need https.
        thumbnail_url=(image_links.get("thumbnail") or "").replace("http://", "https://") or None,
        info_link=info.get("infoLink"),
        published_date=info.get("publishedDate"),
    )


async def search(query: str, max_results: int = 5) -> list[BookResult]:
    """Search Google Books for the given query. Returns up to max_results books."""
    params = {
        "q": query,
        "maxResults": str(max_results),
        "printType": "books",
    }
    if config.GOOGLE_BOOKS_API_KEY:
        params["key"] = config.GOOGLE_BOOKS_API_KEY

    async with aiohttp.ClientSession() as session:
        async with session.get(BASE_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                text = await resp.text()
                log.warning("Google Books %d: %s", resp.status, text[:200])
                return []
            data = await resp.json()

    items = data.get("items", [])
    return [_parse_volume(v) for v in items]
