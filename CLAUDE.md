# EngagementBot — Claude Code Session Guide

## What This Project Is
An automated content pipeline: reads user-authored narrative arc stories from DynamoDB, generates episodic captions via OpenAI, generates a carousel of images via Google Gemini, posts to a Facebook page via the Graph API, and marks the block complete in DynamoDB. Runs on a configurable schedule via AWS Lambda + EventBridge — fully hands-off.

## Tech Stack
| Concern | Choice |
|---|---|
| Language | Python 3.12 |
| Content LLM | OpenAI API (model configurable via DynamoDB config) |
| Image generation | Google Gemini API (`gemini-2.5-flash-image`, configurable via DynamoDB config) |
| Social platform | Facebook Graph API (carousel post) |
| Scheduler | AWS Lambda + EventBridge Scheduler |
| Story & config state | DynamoDB (`engagement-bot-stories` table) |
| Secrets | AWS SSM Parameter Store (SecureString, fetched at Lambda runtime) |
| IaC | AWS SAM (`template.yaml` + `samconfig.toml`) |

## Project Docs
- [README.md](README.md) — operational runbook (status, dry-run, deploy, story management)
- [PROJECT.md](PROJECT.md) — full architecture and design decisions
- [TASKS.md](TASKS.md) — phased task list with current status
- [story-file-guide.md](story-file-guide.md) — how to author a story file
- [memory/](memory/) — Claude Code session memory (auto-managed)

## Deployed Infrastructure
| Resource | Value |
|---|---|
| AWS region | `us-west-2` |
| CloudFormation stack | `engagement-bot` |
| Lambda function | `engagement-bot-engagement` |
| CloudWatch log group | `/aws/lambda/engagement-bot-engagement` |
| DynamoDB table | `engagement-bot-stories` |
| S3 bucket (SAM artifacts only) | `engagement-bot-bucket` |
| EventBridge schedule | `engagement-bot-posting-schedule` |
| IAM Lambda role | `engagement-bot-lambda-role` |

## SSM Secrets (SecureString)
Fetched at Lambda startup in `handler.py:_load_secrets()`. Do not use `{{resolve:ssm-secure:...}}` in `template.yaml` for Lambda env vars — CloudFormation doesn't support it there.

| Secret | SSM Path |
|---|---|
| OpenAI API key | `/engagement-bot/openai-api-key` |
| Google Gemini API key | `/engagement-bot/google-api-key` |
| Facebook Page Access Token | `/engagement-bot/facebook-page-access-token` |

To update a secret: `bash scripts/setup-secrets.sh` (no redeploy needed).

## Lambda Environment Variables
Set via `samconfig.toml` parameter_overrides. Non-secret only — secrets come from SSM.

```
DDB_TABLE                  # engagement-bot-stories
FACEBOOK_PAGE_ID           # numeric page ID
DRY_RUN                    # "true" | "false"
SSM_OPENAI_API_KEY         # SSM path (not the key itself)
SSM_GOOGLE_API_KEY         # SSM path
SSM_FACEBOOK_TOKEN         # SSM path
```

## Build & Deploy
```bash
bash scripts/deploy.sh     # bake-branding.py → sam build → update stack → sam deploy
```
`deploy.sh` runs `scripts/bake-branding.py` first, embedding both branding guides into `src/branding.py` before the Lambda is packaged. Any change to a branding file requires a redeploy to take effect.

After deploy, `deploy.sh` automatically runs `import-config.py`. For a fresh deploy, also import stories:
```bash
python scripts/import-story.py stories/01-my-arc.yaml  # writes story + blocks to DDB
```
Config changes only — no Lambda redeploy needed:
```bash
# Edit config/config.yaml, then:
python scripts/import-config.py
```

## Key Behavioral Facts
- **Story selection:** `story_file.py:list_stories()` queries the `StatusCreatedAtIndex` GSI for `story_status="in_progress"`, sorted by `created_at` ascending (oldest first). The handler iterates in that order and processes the **first story with any pending block**.
- **One block per run:** Only the lowest-numbered `pending` block in the selected story is processed per Lambda invocation.
- **Concurrency lock:** `handler.py` uses an atomic DynamoDB conditional PutItem on `SYSTEM/LOCK` to prevent concurrent Lambda runs. Lock TTL is 16 minutes (Lambda timeout is 15 minutes).
- **Dry-run mode:** Runs OpenAI + Gemini image generation but skips Facebook posting and does not update DynamoDB. Block stays `pending`. Caption preview is truncated to 200 chars in the response/logs; full output requires DEBUG log level.
- **No-op run:** If no stories have pending blocks, Lambda logs and exits cleanly — not an error.
- **Secrets at runtime:** `handler.py:_load_secrets()` calls SSM at the start of every invocation and sets `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `FACEBOOK_PAGE_ACCESS_TOKEN` in `os.environ` before any other module uses them.
- **Styling priority:** Brand-level style guides (`branding/`) are baked into `src/branding.py` at deploy time and embedded in the OpenAI system prompt. Story-level `narrative_style` / `image_style` on `STORY#META` supersede the brand defaults when present. No block-level style overrides exist — styling is intentionally story-wide for visual continuity.

## DynamoDB Table Schema
Table: `engagement-bot-stories` | PK: `story_id` (S) | SK: `sk` (S)

| Item type | story_id | sk | Key attributes |
|---|---|---|---|
| Config | `SYSTEM` | `CONFIG` | `llm_model`, `images_model`, `images_count`, ... |
| Lock | `SYSTEM` | `LOCK` | `locked_at`, `expires_at` |
| Story meta | `<story_id>` | `STORY#META` | `title`, `story_status`, `created_at`, `narrative_style`?, `image_style`? |
| Block | `<story_id>` | `BLOCK#001` | `id`, `status`, `template`, `caption_notes`?, `image_count`?, `caption`, ... |

GSI `StatusCreatedAtIndex`: PK=`story_status`, SK=`created_at` (KEYS_ONLY projection)

## Branding & Styling System
Brand-level guidance lives in `branding/` as human-editable markdown:
- `branding/narrative-styling-guide.md` — tone, character, romantic dynamics, caption style
- `branding/image-styling-guide.md` — visual aesthetic, composition, palette, prompt language

`scripts/bake-branding.py` reads both files and writes `src/branding.py` with `NARRATIVE_STYLE` and `IMAGE_STYLE` string constants. `deploy.sh` runs this automatically before `sam build`. Changes to branding files require a redeploy.

Story-level `narrative_style` / `image_style` on `STORY#META` override brand defaults for that story. Set in the story YAML `project:` section and imported via `import-story.py`.

## Directory Layout
```
EngagementBot/
├── src/
│   ├── handler.py          # Lambda entry point; orchestrates pipeline + DDB lock
│   ├── story_file.py       # DynamoDB read/write, story and block management
│   ├── generator.py        # OpenAI content generation (caption + image prompts)
│   ├── stylizer.py         # Google Gemini image generation
│   ├── publisher.py        # Facebook Graph API carousel posting
│   ├── branding.py         # AUTO-GENERATED — do not edit; run bake-branding.py to update
│   └── requirements.txt    # Lambda dependencies (used by sam build)
├── branding/
│   ├── narrative-styling-guide.md  # Brand narrative/tone/character standards
│   └── image-styling-guide.md      # Brand image generation standards
├── config/
│   └── config.yaml         # Runtime config source — apply with import-config.py
├── scripts/
│   ├── deploy.sh           # bake-branding.py → sam build → sam deploy
│   ├── invoke.sh           # Invoke Lambda and display result
│   ├── bake-branding.py    # Embed branding guides into src/branding.py
│   ├── import-config.py    # Write config.yaml → DynamoDB SYSTEM/CONFIG
│   ├── import-story.py     # Write a YAML story file → DynamoDB
│   ├── revert-block.py     # Reset a completed block back to pending
│   └── setup-secrets.sh    # Store API keys in SSM (run once, or to rotate)
├── stories/                # Local story YAML files (source of truth for authoring)
├── template.yaml           # SAM/CloudFormation template
├── samconfig.toml          # SAM deploy config (stack name, params, region)
├── CLAUDE.md               # This file
├── README.md               # Operational runbook
├── PROJECT.md              # Architecture doc
└── TASKS.md                # Task tracker
```

## How to Pick Up a Session
1. Read this file.
2. Read [TASKS.md](TASKS.md) — find the first unchecked item.
3. Read [README.md](README.md) for operational context if the task is ops/deploy related.
4. Check `memory/` for session notes.
5. For architecture questions, read [PROJECT.md](PROJECT.md).
