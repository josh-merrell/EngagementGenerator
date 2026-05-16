# EngagementBot — Project Scope

## Goal
A fully automated pipeline that:
1. Reads the next pending block from a user-authored project file (narrative arc)
2. Generates themed content (caption + image prompts) via an LLM
3. Generates a carousel of images via Google Imagen
4. Posts the carousel + caption to a Facebook page
5. Updates the project file (marks block complete, records generated content)
6. Runs on a configurable schedule via AWS Lambda + EventBridge — no user intervention required

---

## Tech Stack

| Concern | Choice |
|---|---|
| Language | Python |
| Content generation | OpenAI API (model configurable; designed to swap easily) |
| Image generation | Google Imagen (via Vertex AI or Gemini API) |
| Social platform | Facebook Graph API (carousel post to a Page) |
| Scheduler host | AWS Lambda + EventBridge Scheduler |
| Project/config storage | S3 (Lambda is stateless; files must persist externally) |
| Secrets | AWS Lambda environment variables (or Secrets Manager) |
| Config format | YAML |

---

## Human vs. System Responsibilities

| Responsibility | Owner |
|---|---|
| Author and upload project files | **Human** — using `project-file-guide.md` as reference |
| Everything else (generate, post, track) | **System** — fully automated |

The human's only recurring input is creating and uploading a new project file when starting a new arc. Once uploaded, the system handles every run without intervention.

**No-op behavior:** If the Lambda runs and finds no project file in S3, or all existing project files have every block marked `complete`, it logs a message and exits cleanly. The schedule continues firing; runs simply no-op until a new project file is uploaded.

---

## Pipeline Overview

```
[EventBridge Scheduler]
        ↓
[Lambda: main handler]
        ↓
[Scan S3 for project files] ── any pending blocks?
        │                              │
       No                            Yes
        │                              ↓
    log + exit         [Read next pending block]
                               ↓
               [Content Generator] ── OpenAI: block template + config → caption + image prompts
                               ↓
               [Stylization Layer] ── Google Imagen: image prompts → N images (carousel)
                               ↓
               [Facebook Publisher] ── Graph API: upload images + create carousel post
                               ↓
               [Update project file on S3] ── replace template with generated caption,
                                              write image_prompts, posted_at, post_id,
                                              mark block complete
                               ↓
               [If last block in project, set project.status = complete]
```

---

## Project File (user-authored)

Lives in S3. Defines the full narrative arc as an ordered list of blocks. Each block contains:

```yaml
# Example structure (format may evolve)
project:
  title: "My Story Arc"
  status: in_progress   # in_progress | complete
  blocks:
    - id: 1
      status: pending    # pending | complete
      template: |
        [User-written prompt/outline for this episode]
      generated_caption: null   # filled in after run
      generated_image_prompts: []  # filled in after run
      posted_at: null   # filled in after run
```

After each run the Lambda edits the block in-place: replaces `template` guidance with actual generated content and sets `status: complete`.

---

## Config File

Lives in S3 (or bundled with the Lambda deployment). Controls runtime behavior:

```yaml
# config.yaml (example structure)
project_file: s3://my-bucket/projects/my-arc.yaml

llm:
  provider: openai
  model: gpt-4o
  temperature: 0.8

images:
  provider: google_imagen
  count: 3          # images per carousel post
  aspect_ratio: "4:5"

facebook:
  page_id: "YOUR_PAGE_ID"

schedule:
  cron: "0 10 * * 1,3,5"   # EventBridge cron expression (UTC)
```

---

## AWS Architecture

```
EventBridge Scheduler
    → Lambda function (Python)
        → S3 (read/write project file and config)
        → OpenAI API (external)
        → Google Imagen API (external)
        → Facebook Graph API (external)
        → CloudWatch Logs (logging)
```

- **Lambda** — stateless execution, uses `/tmp` for image temp storage during a run
- **S3** — persists project files, config, and optionally generated image archives
- **EventBridge Scheduler** — triggers Lambda on the cron from config
- **IAM** — Lambda role needs S3 read/write; no other AWS services required at minimum

---

## Facebook Setup (to be done)
Starting from scratch. Steps required:
1. Create Facebook Developer account / app
2. Configure app with `pages_manage_posts` and `pages_read_engagement` permissions
3. Generate a long-lived Page Access Token
4. Store token as Lambda environment variable

---

## Out of Scope (for now)
- Multi-platform posting (Instagram, X, LinkedIn)
- Analytics or engagement tracking
- Web UI or admin dashboard
- A/B testing content variants
- Video posts
