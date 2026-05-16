# EngagementBot — Task List

## Status Legend
- [ ] Not started
- [~] In progress
- [x] Complete

---

## Phase 0 — Foundation
- [x] Draft project scope (PROJECT.md, CLAUDE.md, TASKS.md)
- [x] Lock tech stack and design decisions
- [x] Initialize Python project structure (pyproject.toml / requirements.txt, .gitignore, .env.example, src layout)
- [x] Define project file YAML schema (blocks, status fields, content slots)
- [x] Define config.yaml schema
- [x] Create example project file and example config

## Phase 1 — Project File Management
- [x] S3 client utility (read/write YAML files from S3)
- [x] Project file scanner — list all project files in S3, find any with pending blocks
- [x] Project file reader — load file, select next pending block
- [x] Project file updater — replace template with generated caption, write image_prompts/posted_at/post_id, mark block complete, set project.status=complete if last block
- [x] No-op path: if no pending blocks found anywhere, log and exit cleanly (not an error)

## Phase 2 — Content Generation
- [x] OpenAI client wrapper (configurable model via config.yaml)
- [x] Prompt builder — combine block template + config directives into LLM prompt
- [x] Response parser — extract caption text and image prompt(s) from LLM output
- [x] Config-driven: easy to swap provider/model without code changes

## Phase 3 — Image Generation (Google Imagen)
- [x] Google Imagen API client (Gemini API — google-generativeai)
- [x] Generate N images from image prompts (count from config)
- [x] Save images to Lambda /tmp during run
- [x] Handle partial failures (some images fail — retry or degrade gracefully)

## Phase 4 — Facebook Publishing
- [ ] Walk through Facebook Developer app setup (separate guide or doc)
- [ ] Obtain and store long-lived Page Access Token
- [x] Facebook Graph API client
- [x] Upload images (one at a time via `/{page-id}/photos?published=false`)
- [x] Create carousel post (`/{page-id}/feed` with `attached_media` list)
- [x] Error handling and retry on transient failures

## Phase 5 — Lambda + AWS Wiring
- [x] Lambda handler entry point (`handler.py`)
- [x] End-to-end pipeline orchestration in handler
- [x] Packaging: SAM + Makefile build method (make build-deploy)
- [x] IAM role: S3 read/write, CloudWatch logs
- [x] EventBridge Scheduler rule (cron from config)
- [x] Environment variables: API keys in SSM; non-secret config in samconfig.toml
- [ ] Deploy and smoke test (dry-run first)

## Phase 6 — Reliability & Ops
- [x] Structured logging (CloudWatch friendly JSON, timing in every step)
- [x] SNS email alert on Lambda error (CloudWatch Alarm → SNS → email)
- [x] Dry-run mode (generate content and log, skip posting)
- [ ] README: setup, deployment, how to author a project file

---

## Refactor — DynamoDB Story State

Replacing S3 YAML project files with DynamoDB for story and block state management. Stories are now referred to as "stories" (not "project files").

### Phase R1 — Schema & Infrastructure
- [x] Define DynamoDB table schema — single table `engagement-bot-stories`, PK: `story_id`, SK: `sk`, GSI `StatusCreatedAtIndex` on `story_status` + `created_at`
- [x] Add DDB table + GSI to `template.yaml`
- [x] Update Lambda IAM role — add DynamoDB read/write permissions
- [x] Add `DDB_TABLE` Lambda environment variable to `template.yaml` and `samconfig.toml`
- [x] Replace S3 lock file with atomic DDB conditional lock (`PutItem` with `ConditionExpression`)

### Phase R2 — Data Layer
- [x] Rewrite `project_file.py` → `story_file.py` with DynamoDB operations
  - [x] `list_stories()` — query GSI for stories with `story_status="in_progress"`, sorted by `created_at`
  - [x] `load_story()` — query all records for a `story_id` (metadata + blocks)
  - [x] `find_pending_block()` — same logic, operates on in-memory data from `load_story()`
  - [x] `mark_block_complete()` — `UpdateItem` on the block record
  - [x] `mark_story_complete()` — `UpdateItem` on the `STORY#META` record
  - [x] `load_config()` — now reads `SYSTEM/CONFIG` item from DynamoDB
  - [x] Remove `save_project()`, `archive_project_file()` — no longer needed

### Phase R3 — Handler Updates
- [x] Update `handler.py` — swap `project_file` imports for `story_file`, replace S3 lock with DDB lock, remove archive logic
- [x] Audit `requirements.txt` — removed `pyyaml` and `python-dotenv`

### Phase R4 — Story Authoring
- [x] Write `scripts/import-story.py` — reads a local YAML story file, writes `STORY#META` + `BLOCK#xxx` items to DynamoDB
- [x] Write `scripts/import-config.py` — writes `config.yaml` → `SYSTEM/CONFIG` item in DynamoDB
- [x] Rewrite `scripts/revert-block.py` — reset block to `pending` via DynamoDB `UpdateItem`
- [x] Rename `project-file-guide.md` → `story-file-guide.md`, update for DDB workflow and import script

### Phase R5 — Documentation
- [ ] Update `README.md` — replace project file / S3 project references with story / DDB workflow; add DDB console instructions
- [x] Update `CLAUDE.md` — infrastructure table, behavioral facts, directory layout
- [ ] Update `branding/narrative-styling-guide.md` — update project file references
- [x] Remove `scripts/push-config.sh` (obsolete)

### Phase R6 — Cleanup & Deploy
- [x] Delete `project_file.py`
- [x] Remove `projects/` S3 prefix config from `config.yaml` and handler
- [ ] Final deploy + smoke test with imported story

---

## Key Decisions Already Made
- Python, OpenAI API (configurable), Google Imagen, Facebook Graph API, AWS Lambda + EventBridge
- Carousel posts (multiple images per post)
- Fully automated (no approval gate)
- Posting frequency controlled by cron expression in config.yaml
- Project files live in S3; Lambda is stateless
- Facebook setup starting from scratch (developer app + token to be created)
