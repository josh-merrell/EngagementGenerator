"""Lambda entry point. Orchestrates the full pipeline."""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from generator import generate_content
from story_file import (
    find_pending_block,
    list_stories,
    load_config,
    load_story,
    mark_block_complete,
    mark_story_complete,
)
from publisher import publish_carousel
from stylizer import generate_images

logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

_SSM_ENV_VARS = {
    "OPENAI_API_KEY": "SSM_OPENAI_API_KEY",
    "GOOGLE_API_KEY": "SSM_GOOGLE_API_KEY",
    "FACEBOOK_PAGE_ACCESS_TOKEN": "SSM_FACEBOOK_TOKEN",
}

_LOCK_STORY_ID = "SYSTEM"
_LOCK_SK = "LOCK"
_LOCK_TTL_SECONDS = 960  # 16 min — Lambda timeout is 15 min, this gives a 1 min buffer


def _load_secrets():
    """Fetch SecureString parameters from SSM and inject into os.environ."""
    ssm = boto3.client("ssm")
    for env_key, ssm_env_key in _SSM_ENV_VARS.items():
        param_name = os.environ[ssm_env_key]
        value = ssm.get_parameter(Name=param_name, WithDecryption=True)["Parameter"]["Value"]
        os.environ[env_key] = value


def _log(msg: str, **kwargs):
    payload = {"msg": msg, **kwargs}
    print(json.dumps(payload), flush=True)


def _acquire_lock(ddb, table: str) -> bool:
    """Atomically write a lock item to DynamoDB. Returns False if a valid lock exists."""
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(seconds=_LOCK_TTL_SECONDS)).isoformat()
    try:
        ddb.put_item(
            TableName=table,
            Item={
                "story_id": {"S": _LOCK_STORY_ID},
                "sk": {"S": _LOCK_SK},
                "locked_at": {"S": now.isoformat()},
                "expires_at": {"S": expires_at},
            },
            ConditionExpression="attribute_not_exists(story_id) OR expires_at < :now",
            ExpressionAttributeValues={":now": {"S": now.isoformat()}},
        )
        _log("lock_acquired", expires_at=expires_at)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            _log("lock_held")
            return False
        raise


def _release_lock(ddb, table: str):
    try:
        ddb.delete_item(
            TableName=table,
            Key={"story_id": {"S": _LOCK_STORY_ID}, "sk": {"S": _LOCK_SK}},
        )
        _log("lock_released")
    except Exception as exc:
        _log("lock_release_failed", error=str(exc))


def lambda_handler(event, context):
    run_start = time.monotonic()
    _log("run_start", event=event)

    _load_secrets()

    table = os.environ["DDB_TABLE"]
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"

    _log("env_loaded", table=table, dry_run=dry_run)

    ddb = boto3.client("dynamodb")
    if not _acquire_lock(ddb, table):
        _log("run_complete", status="already_running",
             total_ms=round((time.monotonic() - run_start) * 1000))
        return {"status": "already_running"}

    try:
        return _run(table, dry_run, run_start)
    finally:
        _release_lock(ddb, table)


def _run(table: str, dry_run: bool, run_start: float) -> dict:
    # ── Load config ────────────────────────────────────────────────────────
    t0 = time.monotonic()
    config = load_config()
    _log("config_loaded",
         elapsed_ms=round((time.monotonic() - t0) * 1000),
         llm_model=config.get("llm", {}).get("model"),
         image_count=config.get("images", {}).get("count"),
         aspect_ratio=config.get("images", {}).get("aspect_ratio"))

    # ── List stories ───────────────────────────────────────────────────────
    t0 = time.monotonic()
    story_ids = list_stories()
    _log("stories_found",
         elapsed_ms=round((time.monotonic() - t0) * 1000),
         count=len(story_ids),
         story_ids=story_ids)

    if not story_ids:
        _log("run_complete", status="noop", reason="no_stories",
             total_ms=round((time.monotonic() - run_start) * 1000))
        return {"status": "noop", "reason": "no_stories"}

    # ── Find a pending block ───────────────────────────────────────────────
    for story_id in story_ids:
        _log("loading_story", story_id=story_id)

        t0 = time.monotonic()
        story = load_story(story_id)
        proj_meta = story["project"]
        _log("story_loaded",
             elapsed_ms=round((time.monotonic() - t0) * 1000),
             story_id=story_id,
             title=proj_meta.get("title"),
             story_status=proj_meta.get("story_status"),
             total_blocks=len(story["blocks"]),
             complete_blocks=sum(1 for b in story["blocks"] if b.get("status") == "complete"),
             pending_blocks=sum(1 for b in story["blocks"] if b.get("status") == "pending"))

        block = find_pending_block(story)
        if block is None:
            _log("story_skipped", story_id=story_id, reason="no_pending_blocks")
            continue

        _log("block_selected",
             story_id=story_id,
             block_id=block["id"],
             block_status=block.get("status"),
             has_image_style=bool(block.get("image_style")),
             has_caption_notes=bool(block.get("caption_notes")),
             image_count_override=block.get("image_count"),
             template_length=len(block.get("template", "")))

        prior_blocks = [b for b in story["blocks"] if b.get("status") == "complete"]
        _log("prior_blocks", count=len(prior_blocks), ids=[b["id"] for b in prior_blocks])

        # ── Content generation ─────────────────────────────────────────────
        _log("content_generation_start")
        t0 = time.monotonic()
        try:
            caption, image_prompts = generate_content(block, story, config, prior_blocks)
        except Exception as exc:
            _log("content_generation_failed", error=str(exc), error_type=type(exc).__name__)
            raise
        gen_ms = round((time.monotonic() - t0) * 1000)

        title_header = proj_meta.get("title", "").upper()
        total_blocks = len(story["blocks"])
        caption = f"~~ {title_header} ({block['id']}/{total_blocks}) ~~\n\n{caption}"

        _log("content_generation_complete",
             elapsed_ms=gen_ms,
             caption_length=len(caption),
             caption_preview=caption[:200],
             image_prompt_count=len(image_prompts),
             image_prompts=image_prompts)

        # ── Image generation ───────────────────────────────────────────────
        _log("image_generation_start", prompt_count=len(image_prompts))
        t0 = time.monotonic()
        try:
            image_paths = generate_images(image_prompts, config, block)
        except Exception as exc:
            _log("image_generation_failed", error=str(exc), error_type=type(exc).__name__)
            raise
        img_ms = round((time.monotonic() - t0) * 1000)
        _log("image_generation_complete",
             elapsed_ms=img_ms,
             image_count=len(image_paths),
             paths=image_paths)

        # ── Dry-run exit ───────────────────────────────────────────────────
        if dry_run:
            _log("dry_run_exit",
                 story_id=story_id,
                 block_id=block["id"],
                 caption_preview=caption[:200],
                 image_prompt_count=len(image_prompts),
                 total_ms=round((time.monotonic() - run_start) * 1000))
            return {
                "status": "dry_run",
                "story_id": story_id,
                "block_id": block["id"],
                "caption_preview": caption[:200],
                "image_prompts": image_prompts,
            }

        # ── Publishing ─────────────────────────────────────────────────────
        page_id = os.environ["FACEBOOK_PAGE_ID"]
        _log("publishing_start", page_id=page_id, image_count=len(image_paths))
        t0 = time.monotonic()
        try:
            post_id = publish_carousel(caption, image_paths, page_id,
                                       os.environ["FACEBOOK_PAGE_ACCESS_TOKEN"])
        except Exception as exc:
            _log("publishing_failed", error=str(exc), error_type=type(exc).__name__)
            raise
        pub_ms = round((time.monotonic() - t0) * 1000)
        posted_at = datetime.now(timezone.utc).isoformat()
        _log("publishing_complete",
             elapsed_ms=pub_ms,
             post_id=post_id,
             posted_at=posted_at)

        # ── Update story state ─────────────────────────────────────────────
        _log("story_update_start", story_id=story_id, block_id=block["id"])
        t0 = time.monotonic()
        mark_block_complete(story_id, block["id"], caption, image_prompts, posted_at, post_id)

        remaining_pending = [
            b for b in story["blocks"]
            if b.get("status") == "pending" and b["id"] != block["id"]
        ]
        story_complete = not remaining_pending
        if story_complete:
            mark_story_complete(story_id)

        _log("story_update_complete",
             elapsed_ms=round((time.monotonic() - t0) * 1000),
             story_complete=story_complete)

        total_ms = round((time.monotonic() - run_start) * 1000)
        _log("run_complete",
             status="ok",
             story_id=story_id,
             block_id=block["id"],
             post_id=post_id,
             posted_at=posted_at,
             story_complete=story_complete,
             total_ms=total_ms,
             gen_ms=gen_ms,
             img_ms=img_ms,
             pub_ms=pub_ms)

        return {
            "status": "ok",
            "story_id": story_id,
            "block_id": block["id"],
            "post_id": post_id,
            "story_complete": story_complete,
        }

    _log("run_complete",
         status="noop",
         reason="all_blocks_complete",
         total_ms=round((time.monotonic() - run_start) * 1000))
    return {"status": "noop", "reason": "all_blocks_complete"}
