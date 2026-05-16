#!/usr/bin/env python3
"""Reset a completed block back to pending so it reruns on the next invoke.

Usage:
    python3 scripts/revert-block.py <story_id> <block_id>

Example:
    python3 scripts/revert-block.py 01-my-arc 3
"""
import os
import sys

import boto3

TABLE = os.environ.get("DDB_TABLE", "engagement-bot-stories")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")

if len(sys.argv) != 3:
    print(__doc__)
    sys.exit(1)

story_id = sys.argv[1]
block_id = int(sys.argv[2])
block_sk = f"BLOCK#{block_id:03d}"

ddb = boto3.resource("dynamodb", region_name=REGION)
table = ddb.Table(TABLE)

resp = table.get_item(Key={"story_id": story_id, "sk": block_sk})
block = resp.get("Item")

if block is None:
    print(f"Error: block {block_id} not found for story '{story_id}'")
    sys.exit(1)

if block.get("status") != "complete":
    print(f"Block {block_id} has status '{block.get('status')}' — nothing to revert.")
    sys.exit(0)

print(f"Reverting block {block_id} for story '{story_id}' ...")
table.update_item(
    Key={"story_id": story_id, "sk": block_sk},
    UpdateExpression=(
        "SET #status = :pending "
        "REMOVE caption, image_prompts, posted_at, facebook_post_id"
    ),
    ExpressionAttributeNames={"#status": "status"},
    ExpressionAttributeValues={":pending": "pending"},
)
print(f"  Block {block_id}: complete → pending")

meta_resp = table.get_item(Key={"story_id": story_id, "sk": "STORY#META"})
meta = meta_resp.get("Item", {})
if meta.get("story_status") == "complete":
    table.update_item(
        Key={"story_id": story_id, "sk": "STORY#META"},
        UpdateExpression="SET story_status = :in_progress",
        ExpressionAttributeValues={":in_progress": "in_progress"},
    )
    print("  Story status: complete → in_progress")

print(f"\nDone. Block {block_id} will rerun on the next Lambda invocation.")
