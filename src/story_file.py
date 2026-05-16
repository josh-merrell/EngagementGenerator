"""DynamoDB operations for story and block state management."""

import logging
import os

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)

_table = None


def _get_table():
    global _table
    if _table is None:
        ddb = boto3.resource("dynamodb")
        _table = ddb.Table(os.environ["DDB_TABLE"])
    return _table


def load_config() -> dict:
    """Load runtime config from the SYSTEM/CONFIG item in DynamoDB."""
    table = _get_table()
    resp = table.get_item(Key={"story_id": "SYSTEM", "sk": "CONFIG"})
    item = resp.get("Item")
    if not item:
        raise RuntimeError(
            "Config not found in DynamoDB — run scripts/import-config.py first."
        )
    return {
        "llm": {
            "model": item["llm_model"],
            "temperature": float(item.get("llm_temperature", 0.8)),
            "max_tokens": int(item.get("llm_max_tokens", 1000)),
        },
        "images": {
            "model": item["images_model"],
            "count": int(item.get("images_count", 5)),
            "aspect_ratio": item.get("images_aspect_ratio", "4:5"),
            "style": item.get("images_style"),
        },
    }


def list_stories() -> list[str]:
    """Return story_ids with status 'in_progress', sorted by created_at ascending."""
    table = _get_table()
    resp = table.query(
        IndexName="StatusCreatedAtIndex",
        KeyConditionExpression=Key("story_status").eq("in_progress"),
        ScanIndexForward=True,
    )
    story_ids = [item["story_id"] for item in resp.get("Items", [])]
    logger.info("list_stories: found %d in_progress stories", len(story_ids))
    return story_ids


def load_story(story_id: str) -> dict:
    """Load a story and all its blocks from DynamoDB.

    Returns a dict shaped like the old project YAML:
        {"project": {...meta...}, "blocks": [...blocks...]}
    """
    table = _get_table()
    resp = table.query(KeyConditionExpression=Key("story_id").eq(story_id))
    items = resp.get("Items", [])

    meta = None
    blocks = []
    for item in items:
        sk = item["sk"]
        if sk == "STORY#META":
            meta = {k: v for k, v in item.items() if k not in ("story_id", "sk")}
        elif sk.startswith("BLOCK#"):
            block = {k: v for k, v in item.items() if k not in ("story_id", "sk")}
            block["id"] = int(block["id"])
            if "image_count" in block:
                block["image_count"] = int(block["image_count"])
            if isinstance(block.get("image_prompts"), set):
                block["image_prompts"] = list(block["image_prompts"])
            blocks.append(block)

    if meta is None:
        raise RuntimeError(f"Story '{story_id}' not found in DynamoDB")

    blocks.sort(key=lambda b: b["id"])
    logger.info("load_story: story_id=%s blocks=%d", story_id, len(blocks))
    return {"project": meta, "blocks": blocks}


def find_pending_block(story: dict) -> dict | None:
    """Return the lowest-id pending block, or None if all are complete."""
    for block in story["blocks"]:  # already sorted by id
        if block.get("status") == "pending":
            return block
    return None


def mark_block_complete(
    story_id: str,
    block_id: int,
    caption: str,
    image_prompts: list[str],
    posted_at: str,
    post_id: str,
) -> None:
    """Mark a block as complete and store generated content."""
    table = _get_table()
    sk = f"BLOCK#{block_id:03d}"
    table.update_item(
        Key={"story_id": story_id, "sk": sk},
        UpdateExpression=(
            "SET #status = :complete, caption = :caption, "
            "image_prompts = :prompts, posted_at = :posted_at, "
            "facebook_post_id = :post_id"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":complete": "complete",
            ":caption": caption,
            ":prompts": image_prompts,
            ":posted_at": posted_at,
            ":post_id": post_id,
        },
    )
    logger.info("mark_block_complete: story_id=%s block_id=%d", story_id, block_id)


def mark_story_complete(story_id: str) -> None:
    """Set story_status to 'complete' on the STORY#META item."""
    table = _get_table()
    table.update_item(
        Key={"story_id": story_id, "sk": "STORY#META"},
        UpdateExpression="SET story_status = :complete",
        ExpressionAttributeValues={":complete": "complete"},
    )
    logger.info("mark_story_complete: story_id=%s", story_id)
