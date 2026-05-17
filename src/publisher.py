"""Facebook Graph API: upload images and create a carousel post."""

import json
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com/v19.0"
_MAX_RETRIES = 3
_RETRY_DELAY = 5  # seconds between retries


def publish_carousel(
    caption: str,
    image_paths: list[str],
    page_id: str,
    access_token: str,
) -> str:
    """Upload images as unpublished photos, then create a carousel post.

    Returns:
        The Facebook post ID string.
    """
    logger.info(
        "publish_carousel: page_id=%s image_count=%d caption_len=%d",
        page_id, len(image_paths), len(caption),
    )

    media_fbids = []
    for idx, path in enumerate(image_paths):
        file_size = os.path.getsize(path) if os.path.exists(path) else -1
        logger.info(
            "Uploading photo %d/%d — path=%s size_bytes=%d",
            idx + 1, len(image_paths), path, file_size,
        )
        fbid = upload_photo(path, page_id, access_token)
        media_fbids.append(fbid)
        logger.info("Photo %d/%d uploaded — media_fbid=%s", idx + 1, len(image_paths), fbid)

    logger.info(
        "All photos uploaded — media_fbids=%s; creating carousel post",
        media_fbids,
    )
    post_id = create_post(caption, media_fbids, page_id, access_token)
    logger.info("Carousel post created — post_id=%s page_id=%s", post_id, page_id)
    return post_id


def upload_photo(image_path: str, page_id: str, access_token: str) -> str:
    """Upload a single photo as unpublished. Returns the media_fbid."""
    url = f"{GRAPH_BASE}/{page_id}/photos"
    params = {"access_token": access_token, "published": "false"}

    logger.debug("upload_photo: url=%s path=%s", url, image_path)

    last_exc = None
    for attempt in range(1, _MAX_RETRIES + 1):
        logger.info("upload_photo attempt %d/%d — %s", attempt, _MAX_RETRIES, image_path)
        try:
            with open(image_path, "rb") as f:
                resp = requests.post(url, params=params, files={"source": f}, timeout=60)
        except requests.RequestException as exc:
            logger.warning(
                "upload_photo attempt %d/%d network error: %s", attempt, _MAX_RETRIES, exc
            )
            last_exc = exc
            if attempt < _MAX_RETRIES:
                logger.info("Retrying in %ds...", _RETRY_DELAY)
                time.sleep(_RETRY_DELAY)
            continue

        logger.debug(
            "upload_photo response: status=%d headers=%s body=%s",
            resp.status_code, dict(resp.headers), resp.text[:500],
        )

        if resp.ok:
            media_fbid = resp.json()["id"]
            logger.info("upload_photo OK — media_fbid=%s", media_fbid)
            return media_fbid

        logger.warning(
            "upload_photo attempt %d/%d HTTP error: status=%d body=%s",
            attempt, _MAX_RETRIES, resp.status_code, resp.text[:300],
        )
        if attempt < _MAX_RETRIES:
            logger.info("Retrying in %ds...", _RETRY_DELAY)
            time.sleep(_RETRY_DELAY)

    fb_error = resp.text[:500] if not last_exc else str(last_exc)
    logger.error(
        "upload_photo failed after %d attempts — path=%s facebook_error=%s",
        _MAX_RETRIES, image_path, fb_error,
    )
    raise requests.HTTPError(
        f"Facebook API error uploading photo {image_path}: {fb_error}",
        response=resp if not last_exc else None,
    )


def create_post(
    caption: str,
    media_fbids: list[str],
    page_id: str,
    access_token: str,
) -> str:
    """Create a carousel post with the given attached media. Returns the post ID."""
    url = f"{GRAPH_BASE}/{page_id}/feed"

    logger.info(
        "create_post: page_id=%s media_fbids=%s caption_len=%d",
        page_id, media_fbids, len(caption),
    )
    logger.debug("create_post caption preview: %s", caption[:200])

    # Build payload as a list of tuples so attached_media uses indexed array
    # parameters (attached_media[0]=..., attached_media[1]=...) which Facebook
    # parses reliably. A single JSON-string value is accepted but silently drops
    # the attachments, producing a text-only post.
    payload = [
        ("message", caption),
        ("published", "true"),
        ("access_token", access_token),
    ]
    for i, fbid in enumerate(media_fbids):
        payload.append((f"attached_media[{i}]", json.dumps({"media_fbid": fbid})))

    logger.debug("create_post payload fields: %s", [k for k, _ in payload])

    last_resp = None
    for attempt in range(1, _MAX_RETRIES + 1):
        logger.info("create_post attempt %d/%d", attempt, _MAX_RETRIES)
        try:
            resp = requests.post(url, data=payload, timeout=30)
            last_resp = resp
        except requests.RequestException as exc:
            logger.warning(
                "create_post attempt %d/%d network error: %s", attempt, _MAX_RETRIES, exc
            )
            if attempt < _MAX_RETRIES:
                logger.info("Retrying in %ds...", _RETRY_DELAY)
                time.sleep(_RETRY_DELAY)
            continue

        logger.debug(
            "create_post response: status=%d body=%s",
            resp.status_code, resp.text[:500],
        )

        if resp.ok:
            post_id = resp.json()["id"]
            logger.info("create_post OK — post_id=%s", post_id)
            return post_id

        logger.warning(
            "create_post attempt %d/%d HTTP error: status=%d body=%s",
            attempt, _MAX_RETRIES, resp.status_code, resp.text[:300],
        )
        if attempt < _MAX_RETRIES:
            logger.info("Retrying in %ds...", _RETRY_DELAY)
            time.sleep(_RETRY_DELAY)

    fb_error = last_resp.text[:500] if last_resp else "no response"
    logger.error(
        "create_post failed after %d attempts — page_id=%s facebook_error=%s",
        _MAX_RETRIES, page_id, fb_error,
    )
    raise requests.HTTPError(
        f"Facebook API error posting to page {page_id}: {fb_error}",
        response=last_resp,
    )
