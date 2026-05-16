# EngagementBot

Automated episodic content pipeline for Facebook. Reads narrative arc stories from DynamoDB, generates a caption and carousel images via AI, posts to a Facebook page, and marks the block complete — all on a cron schedule via AWS Lambda + EventBridge. No intervention required between posts.

**Your only recurring job:** author story YAML files and import them into DynamoDB.

---

## How It Works

```
EventBridge (cron)
  → Lambda
      → DynamoDB: find oldest in_progress story with a pending block
      → OpenAI: generate caption + image prompts from block template
      → Google Gemini: generate carousel images
      → Facebook Graph API: post carousel
      → DynamoDB: mark block complete; mark story complete if last block
```

One run = one block = one Facebook post. If no pending blocks exist anywhere, the Lambda exits cleanly and the schedule keeps firing.

---

## Operations

### 1. Checking Run Status

**Tail live logs (best for debugging while manually triggering):**
```bash
sam logs --stack-name engagement-bot --tail
```

**View recent logs (past hour):**
```bash
sam logs --stack-name engagement-bot --since 1h
```

**View logs from a specific time range:**
```bash
sam logs --stack-name engagement-bot --since 2h --until 1h
```

Logs are structured JSON. Key events to look for:

| `msg` field | Meaning |
|---|---|
| `run_start` | Lambda invoked |
| `stories_found` | How many in-progress stories found in DynamoDB |
| `block_selected` | Which story and block is being processed this run |
| `content_generation_complete` | OpenAI succeeded; shows caption preview and image prompts |
| `image_generation_complete` | Images generated; shows count and file paths |
| `publishing_complete` | Posted to Facebook; shows `post_id` |
| `story_update_complete` | Block and story state updated in DynamoDB |
| `run_complete` with `status: ok` | Block posted successfully |
| `run_complete` with `status: noop` | No pending blocks — nothing to do |
| `run_complete` with `status: dry_run` | Dry run completed; content generated, not posted |

**CloudWatch directly (AWS Console):**
Log group: `/aws/lambda/engagement-bot-engagement`

---

### 2. Viewing Post History

All story and block state lives in DynamoDB. The easiest way to inspect it:

**AWS Console:** DynamoDB → Tables → `engagement-bot-stories` → Explore items

Filter by `story_id` to see all blocks for a story. Completed blocks have `status: complete` and fields `caption`, `image_prompts`, `posted_at`, and `facebook_post_id`.

**AWS CLI — view all items for a story:**
```bash
aws dynamodb query \
  --table-name engagement-bot-stories \
  --key-condition-expression "story_id = :sid" \
  --expression-attribute-values '{":sid": {"S": "05162026-bride-of-the-drowned-king"}}' \
  --region us-west-2
```

**AWS CLI — list all in-progress stories:**
```bash
aws dynamodb query \
  --table-name engagement-bot-stories \
  --index-name StatusCreatedAtIndex \
  --key-condition-expression "story_status = :s" \
  --expression-attribute-values '{":s": {"S": "in_progress"}}' \
  --region us-west-2
```

---

### 3. Dry-Run Testing

Dry-run mode generates content and images but **skips posting and does not update DynamoDB** — the block stays `pending` and can be re-run.

**To enable dry-run:** Edit `samconfig.toml` — set `"DryRun=true"` → `bash scripts/deploy.sh`

**To disable dry-run (production mode):** Set `"DryRun=false"` → `bash scripts/deploy.sh`

**What dry-run returns:**
```json
{
  "status": "dry_run",
  "story_id": "05162026-bride-of-the-drowned-king",
  "block_id": 1,
  "caption_preview": "First 200 characters of the generated caption...",
  "image_prompts": ["Full prompt 1", "Full prompt 2", "Full prompt 3"]
}
```

> **Note:** The response only includes the first 200 characters of the caption. To see the full caption, check CloudWatch logs — look for the `content_generation_complete` log entry.

**Trigger a dry-run manually:**
```bash
bash scripts/invoke.sh
```

---

### 4. Triggering an On-Demand Run

Invoke the Lambda directly without waiting for the EventBridge schedule:

```bash
bash scripts/invoke.sh
```

Prints `SUCCESS`, `NOOP`, or the error message. The run uses whatever `DRY_RUN` value is configured in the deployed function. To change the behavior, update `samconfig.toml` and redeploy.

**To see logs in real time**, open a second terminal and run:
```bash
sam logs --stack-name engagement-bot --tail
```
before triggering the invoke.

---

### 5. Managing Stories

#### Creating a story

**AGENT-DRIVEN CREATION**
Use this prompt in a new Claude session (Opus 4.7 recommended):
```
Review the project context files as needed. I want to create a new story file in this folder:
  c:\Users\joshm\Desktop\Code\EngagementBot\stories
Refer to this guide:
  c:\Users\joshm\Desktop\Code\EngagementBot\story-file-guide.md
and ask me questions to guide the draft.
```

**MANUAL/REFERENCE**
See [`story-file-guide.md`](story-file-guide.md) for the full schema and authoring guide. Quick version:

```yaml
project:
  title: "Your Arc Title"
  description: "One-sentence summary of the overall story."
  default_image_count: 3

blocks:
  - id: 1
    status: pending
    template: |
      What happens in this episode, the tone, key visuals, narrative position.
    image_style: null       # Optional: "cinematic, dramatic lighting"
    caption_notes: null     # Optional: "Under 100 words. End with a hook."
    image_count: null       # Optional: override default_image_count for this block
```

Save story files under `stories/` locally. The filename (without `.yaml`) becomes the `story_id` in DynamoDB.

**Styling:** brand-level image and narrative style are baked into the Lambda from `branding/` at deploy time. To give a story its own visual identity, add `image_style` and/or `narrative_style` under `project:` in the YAML — these override the brand defaults for every block in that story. See [`story-file-guide.md`](story-file-guide.md) for the schema.

#### Importing a story into DynamoDB

```bash
python scripts/import-story.py stories/your-arc.yaml
```

This writes a `STORY#META` item and one `BLOCK#xxx` item per block to DynamoDB. Re-running overwrites all items for that `story_id` — **do not re-import a story that has completed blocks**, as it will erase their recorded output.

The Lambda will pick it up on the next scheduled run (or immediately if manually invoked).

#### Which story runs next?

When multiple in-progress stories exist, the Lambda:
1. Queries the `StatusCreatedAtIndex` GSI for all stories with `story_status = "in_progress"`
2. Returns them sorted by `created_at` ascending — **oldest imported story first**
3. Iterates through the list and processes the **first story that has at least one pending block**

**One block per run** — the lowest-numbered `pending` block in that story.

Stories are processed serially, not interleaved. If `01-origin-story` still has pending blocks, `02-summer-arc` won't be touched until it's fully complete. Import stories in the order you want them processed.

**Example:**
```
Imported first:  01-origin-story          ← runs until complete
Imported second: 02-summer-arc            ← runs next
Imported third:  03-finale               ← runs last
```

#### Reverting a block (regenerate it)

To reset a completed block back to `pending` so it reruns:

```bash
python scripts/revert-block.py <story_id> <block_id>
```

Example:
```bash
python scripts/revert-block.py 05162026-bride-of-the-drowned-king 3
```

This clears the `caption`, `image_prompts`, `posted_at`, and `facebook_post_id` fields and sets `status: pending`. If the story was `complete`, it's also reset to `in_progress`.

#### Completed stories

When the last block in a story is posted, the Lambda sets `story_status: complete` on the `STORY#META` item. The story no longer appears in the active queue. It remains in DynamoDB and can be inspected or reverted at any time.

#### Pausing a story

To stop a story from being processed without deleting it, change its `story_status` from `in_progress` to `paused` in DynamoDB:

**AWS Console:** DynamoDB → `engagement-bot-stories` → find the `STORY#META` item → edit `story_status` to `paused`

**AWS CLI:**
```bash
aws dynamodb update-item \
  --table-name engagement-bot-stories \
  --key '{"story_id": {"S": "your-story-id"}, "sk": {"S": "STORY#META"}}' \
  --update-expression "SET story_status = :p" \
  --expression-attribute-values '{":p": {"S": "paused"}}' \
  --region us-west-2
```

To resume, set `story_status` back to `in_progress`.

---

### 6. Deploying Changes

#### Code or infrastructure changes

```bash
bash scripts/deploy.sh
```

`scripts/deploy.sh` runs `scripts/bake-branding.py` (embedding brand guides into the Lambda), then `sam build`, then `sam deploy`. It only deletes the existing stack first if it's in a terminal failure state (e.g. `ROLLBACK_COMPLETE`) — otherwise it updates the stack in place, which preserves the DynamoDB table and its data.

> **If the stack is deleted** (e.g. after a failed first deploy), the DynamoDB table is also deleted. You'll need to re-run `import-config.py` and `import-story.py` after redeploying.

#### Branding guide changes

Brand style guides live in `branding/` and are baked into the Lambda at deploy time. Changes require a redeploy:

```bash
# Edit branding/narrative-styling-guide.md or branding/image-styling-guide.md, then:
bash scripts/deploy.sh
```

To preview what gets embedded without deploying:
```bash
python scripts/bake-branding.py   # regenerates src/branding.py locally
```

#### Config changes (`config.yaml`)

No redeploy needed. Edit `config/config.yaml` locally, then:
```bash
python scripts/import-config.py
```
Takes effect on the next Lambda run.

#### Schedule changes

Edit the `ScheduleCron` `Default` value in `template.yaml`, then:
```bash
bash scripts/deploy.sh
```

Current schedule: `cron(0 18,2 ? * * *)` = daily at 18:00 UTC and 02:00 UTC.

> **Note:** The schedule is defined in `template.yaml` (not `samconfig.toml`) because SAM's parameter parser splits on spaces, which breaks cron expressions.

#### Parameter changes (page ID, alert email, dry-run)

Edit the relevant value in `samconfig.toml` → `parameter_overrides`, then `bash scripts/deploy.sh`.

#### Secrets (API keys)

Re-run `scripts/setup-secrets.sh` to overwrite the SSM parameter:
```bash
bash scripts/setup-secrets.sh
```
No redeploy needed — secrets are fetched from SSM at Lambda runtime.

---

## Infrastructure Reference

### Key Resources

| Resource | Name |
|---|---|
| CloudFormation stack | `engagement-bot` |
| Lambda function | `engagement-bot-engagement` |
| CloudWatch log group | `/aws/lambda/engagement-bot-engagement` |
| DynamoDB table | `engagement-bot-stories` |
| EventBridge schedule | `engagement-bot-posting-schedule` |
| SNS alert topic | `engagement-bot-alerts` |
| S3 bucket (SAM artifacts) | `engagement-bot-bucket` |
| AWS region | `us-west-2` |
| IAM Lambda role | `engagement-bot-lambda-role` |

### DynamoDB Table (`engagement-bot-stories`)

| Item type | `story_id` | `sk` | Key attributes |
|---|---|---|---|
| Config | `SYSTEM` | `CONFIG` | `llm_model`, `images_model`, `images_count`, ... |
| Lock | `SYSTEM` | `LOCK` | `locked_at`, `expires_at` |
| Story metadata | `<story_id>` | `STORY#META` | `title`, `story_status`, `created_at` |
| Block | `<story_id>` | `BLOCK#001` | `id`, `status`, `template`, `caption`, ... |

GSI `StatusCreatedAtIndex`: PK=`story_status`, SK=`created_at` — used to list in-progress stories.

### SSM Parameter Paths

All stored as `SecureString`. Fetched at Lambda runtime.

| Parameter | Path |
|---|---|
| OpenAI API key | `/engagement-bot/openai-api-key` |
| Google Gemini API key | `/engagement-bot/google-api-key` |
| Facebook Page Access Token | `/engagement-bot/facebook-page-access-token` |

---

## Troubleshooting

**`No stories found — nothing to do` (noop)**
No stories in DynamoDB have `story_status = "in_progress"` with any `pending` blocks. Import a new story or revert a completed block.

**`Config not found in DynamoDB`**
The `SYSTEM/CONFIG` item is missing. Run `python scripts/import-config.py` to create it.

**`GOOGLE_API_KEY environment variable not set`**
The SSM parameter `/engagement-bot/google-api-key` is missing or the Lambda IAM role lacks `ssm:GetParameter`. Check SSM in the AWS Console and verify the role policy.

**`Gemini returned no image in response`**
The Gemini model returned a response with no image part — usually a safety filter trigger. Check the `image_generation_failed` log entry for the prompt that failed. Try rephrasing the `image_style` or `template` in the story file.

**`LLM response was not valid JSON`**
OpenAI returned something other than the expected JSON structure. Usually transient — re-invoke manually. If persistent, check the raw response in DEBUG logs.

**`SSM Secure reference is not supported` (during `sam deploy`)**
Do not use `{{resolve:ssm-secure:...}}` syntax in `template.yaml` for Lambda environment variables — CloudFormation doesn't support it there. Secrets are fetched at runtime via `boto3` in `handler.py`.

**Facebook posting fails with error 190 or 102**
The Page Access Token has expired (~60 days). Re-generate a long-lived token and update SSM:
```bash
bash scripts/setup-secrets.sh
```

**`sam build` fails**
Ensure you are in the `EngagementBot/` directory. Python 3.12 must be installed and on PATH. On Windows, SAM CLI installs as `sam.cmd` — `scripts/deploy.sh` handles this automatically.

---

## Development Notes

### Adding a new content provider (replacing OpenAI)

`generator.py` is self-contained. Swap the implementation of `generate_content()` — the signature and return type `(caption: str, image_prompts: list[str])` must stay the same. Update the `llm_*` fields in DynamoDB config as needed.

### Adding a new image provider (replacing Gemini)

`stylizer.py` is self-contained. Swap the implementation of `generate_images()` — it must return `list[str]` of absolute `/tmp` file paths. Update the `images_model` field in DynamoDB config as needed.

### Adding a new publishing target (beyond Facebook)

`publisher.py` is self-contained. The handler calls `publish_carousel(caption, image_paths, page_id, token)` and expects a `post_id: str` back. Add additional publishers alongside it and call them from `handler.py`.

### Dry-run caption preview limitation

The dry-run response and logs only include the first 200 characters of the generated caption. To inspect the full output without posting, temporarily set `logging.getLogger().setLevel(logging.DEBUG)` in `handler.py` — the raw LLM JSON response is logged in full at DEBUG level. Revert before deploying (DEBUG logging is very verbose in CloudWatch).

### Story selection order

`story_file.py:list_stories()` queries the `StatusCreatedAtIndex` GSI sorted by `created_at` ascending. The handler processes the oldest in-progress story that has a pending block. Import stories in the order you want them processed.

### Updating brand style guides

`branding/narrative-styling-guide.md` and `branding/image-styling-guide.md` are the source of truth for visual and narrative brand standards. Their content is embedded into `src/branding.py` by `scripts/bake-branding.py` and compiled into the Lambda package at deploy time. Edit the markdown files, then redeploy — no DynamoDB changes needed.
