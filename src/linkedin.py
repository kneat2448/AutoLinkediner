"""LinkedIn posting (Phase 3): image upload, post creation, and first-comment source link.

Docs: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
"""
from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import quote

from src import config, http

log = logging.getLogger(__name__)

API = "https://api.linkedin.com"
# "little" text format reserves these characters; they must be backslash-escaped in commentary.
_LITTLE_RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")
_HASHTAG = re.compile(r"(?<![\w\\])\\#(\w+)")


class LinkedInError(RuntimeError):
    pass


def escape_commentary(text: str) -> str:
    """Escape little-text reserved characters, keeping real #hashtags as hashtags."""
    escaped = _LITTLE_RESERVED.sub(r"\\\1", text)
    return _HASHTAG.sub(r"#\1", escaped)


def _headers(json_body: bool = True) -> dict[str, str]:
    if not config.LINKEDIN_ACCESS_TOKEN:
        raise LinkedInError("LINKEDIN_ACCESS_TOKEN is not set")
    headers = {
        "Authorization": f"Bearer {config.LINKEDIN_ACCESS_TOKEN}",
        "LinkedIn-Version": config.LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def person_urn() -> str:
    """The authenticated member's URN, from /v2/userinfo (OpenID Connect `sub`)."""
    resp = http.get(f"{API}/v2/userinfo", headers={"Authorization": f"Bearer {config.LINKEDIN_ACCESS_TOKEN}"})
    return f"urn:li:person:{resp.json()['sub']}"


def upload_image(owner: str, png: bytes) -> str:
    """initializeUpload → PUT bytes → return the image URN."""
    init = http.post(
        f"{API}/rest/images?action=initializeUpload",
        headers=_headers(),
        json={"initializeUploadRequest": {"owner": owner}},
    ).json()["value"]
    http.request(
        "PUT",
        init["uploadUrl"],
        headers={"Authorization": f"Bearer {config.LINKEDIN_ACCESS_TOKEN}", "Content-Type": "image/png"},
        data=png,
        timeout=120,
    )
    return init["image"]


def create_post(author: str, text: str, image_urn: str | None, alt_text: str = "") -> str:
    """Create a public post; returns the post URN from the x-restli-id header."""
    body: dict = {
        "author": author,
        "commentary": escape_commentary(text),
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if image_urn:
        body["content"] = {"media": {"id": image_urn, "altText": alt_text[:4000]}}
    resp = http.post(f"{API}/rest/posts", headers=_headers(), json=body, retries=1)
    urn = resp.headers.get("x-restli-id", "")
    if not urn:
        raise LinkedInError("Post created but no x-restli-id header returned")
    return urn


def add_comment(actor: str, post_urn: str, text: str) -> bool:
    """Best-effort first comment (used for the source link). Returns False if not permitted."""
    try:
        http.post(
            f"{API}/rest/socialActions/{quote(post_urn, safe='')}/comments",
            headers=_headers(),
            json={"actor": actor, "object": post_urn, "message": {"text": text}},
            retries=1,
        )
        return True
    except Exception:
        log.warning("linkedin: could not add first comment; skipping")
        return False


def publish(text: str, png: bytes | None, source_url: str, alt_text: str = "") -> str:
    """Full Phase-3 flow. Returns the public URL of the new post."""
    author = person_urn()
    image_urn = upload_image(author, png) if png else None
    post_urn = create_post(author, text, image_urn, alt_text)
    log.info("linkedin: published %s", post_urn)
    if source_url:
        add_comment(author, post_urn, f"Source: {source_url}")
    return f"https://www.linkedin.com/feed/update/{post_urn}/"


def token_age_days(today: date | None = None) -> int | None:
    """Days since LINKEDIN_TOKEN_ISSUED (YYYY-MM-DD), or None if unset/invalid."""
    try:
        issued = date.fromisoformat(config.LINKEDIN_TOKEN_ISSUED)
    except ValueError:
        return None
    return ((today or config.now().date()) - issued).days


def main() -> None:
    """``python -m src.linkedin --check``: verify the token works without posting anything."""
    import argparse

    parser = argparse.ArgumentParser(description="LinkedIn helpers")
    parser.add_argument("--check", action="store_true", help="verify the access token (posts nothing)")
    args = parser.parse_args()
    config.setup_logging()
    if not args.check:
        parser.error("use --check")
    urn = person_urn()
    age = token_age_days()
    log.info("linkedin: token OK for %s; token age: %s days; API version %s",
             urn, "unknown" if age is None else age, config.LINKEDIN_VERSION)


if __name__ == "__main__":
    main()
