#!/usr/bin/env python3
"""Write config.yaml settings into DynamoDB as the SYSTEM/CONFIG item.

Run this whenever you change config/config.yaml — no Lambda redeploy needed.

Usage:
    python3 scripts/import-config.py [path/to/config.yaml]

Defaults to config/config.yaml if no path given.
"""
import os
import sys
from decimal import Decimal
from pathlib import Path

import boto3
import yaml

TABLE = os.environ.get("DDB_TABLE", "engagement-bot-stories")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")

config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config/config.yaml")
if not config_path.exists():
    print(f"Error: file not found: {config_path}")
    sys.exit(1)

with open(config_path, encoding="utf-8") as f:
    config = yaml.safe_load(f)

llm = config.get("llm", {})
images = config.get("images", {})

if not llm.get("model"):
    print("Error: config must have llm.model")
    sys.exit(1)
if not images.get("model"):
    print("Error: config must have images.model")
    sys.exit(1)

item = {
    "story_id": "SYSTEM",
    "sk": "CONFIG",
    "llm_model": llm["model"],
    "llm_temperature": Decimal(str(llm.get("temperature", 0.8))),
    "llm_max_tokens": int(llm.get("max_tokens", 1000)),
    "images_model": images["model"],
    "images_count": int(images.get("count", 5)),
    "images_aspect_ratio": images.get("aspect_ratio", "4:5"),
}
if images.get("style"):
    item["images_style"] = images["style"]

ddb = boto3.resource("dynamodb", region_name=REGION)
table = ddb.Table(TABLE)

print(f"Writing SYSTEM/CONFIG to table {TABLE!r} ...")
table.put_item(Item=item)

print("Done.")
print(f"  LLM   : {item['llm_model']}  temp={item['llm_temperature']}  max_tokens={item['llm_max_tokens']}")
print(f"  Images: {item['images_model']}  count={item['images_count']}  ratio={item['images_aspect_ratio']}")
