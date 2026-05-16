#!/usr/bin/env python3
"""Import a local YAML story file into DynamoDB.

The story_id is derived from the filename (without extension).

Usage:
    python scripts/import-story.py <path/to/story.yaml>

Example:
    python scripts/import-story.py stories/01-my-arc.yaml
    → story_id: "01-my-arc"

Story YAML format:
    project:
      title: "The Arc Title"
      description: "Optional description"
      characters: "Optional character definitions (appearance, voice, role) applied to all blocks"
      narrative_style: "Optional story-specific narrative style (overrides brand default)"
      image_style: "Optional story-specific image style (overrides brand default)"
      default_image_count: 3
    blocks:
      - id: 1
        status: pending
        template: "Episode outline..."
        caption_notes: "Optional per-episode caption guidance"
        image_count: 3  # optional override
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
import yaml

TABLE = os.environ.get("DDB_TABLE", "engagement-bot-stories")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")

if len(sys.argv) != 2:
    print(__doc__)
    sys.exit(1)

story_path = Path(sys.argv[1])
if not story_path.exists():
    print(f"Error: file not found: {story_path}")
    sys.exit(1)

story_id = story_path.stem

with open(story_path, encoding="utf-8") as f:
    data = yaml.safe_load(f)

proj_meta = data.get("project", {})
blocks = data.get("blocks", [])

if not proj_meta.get("title"):
    print("Error: story file must have a 'project.title' field")
    sys.exit(1)

ddb = boto3.resource("dynamodb", region_name=REGION)
table = ddb.Table(TABLE)

created_at = datetime.now(timezone.utc).isoformat()

meta_item = {
    "story_id": story_id,
    "sk": "STORY#META",
    "title": proj_meta["title"],
    "story_status": "in_progress",
    "created_at": created_at,
}
for opt in ("description", "tone", "style_notes"):
    if proj_meta.get(opt):
        meta_item[opt] = proj_meta[opt]
# Story-level character definitions and style overrides
for story_field in ("characters", "narrative_style", "image_style"):
    if proj_meta.get(story_field):
        meta_item[story_field] = proj_meta[story_field]
if proj_meta.get("default_image_count"):
    meta_item["default_image_count"] = int(proj_meta["default_image_count"])

print(f"Writing STORY#META — story_id={story_id!r} title={proj_meta['title']!r}")
for field in ("characters", "narrative_style", "image_style"):
    if meta_item.get(field):
        print(f"  {field}: {meta_item[field][:60]}...")
table.put_item(Item=meta_item)

for block in blocks:
    block_id = int(block["id"])
    sk = f"BLOCK#{block_id:03d}"

    block_item = {
        "story_id": story_id,
        "sk": sk,
        "id": block_id,
        "status": block.get("status", "pending"),
        "template": block["template"],
    }
    if block.get("caption_notes"):
        block_item["caption_notes"] = block["caption_notes"]
    if block.get("image_count"):
        block_item["image_count"] = int(block["image_count"])

    print(f"  Writing {sk} (status={block_item['status']})")
    table.put_item(Item=block_item)

print(f"\nDone. Imported {len(blocks)} block(s) for story '{story_id}'.")
print(f"  Table   : {TABLE}")
print(f"  story_id: {story_id!r}")
