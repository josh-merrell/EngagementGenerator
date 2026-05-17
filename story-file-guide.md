# Story File Authoring Guide

A **story** is a narrative arc you define as a local YAML file, then import into DynamoDB. Each run, the Lambda finds the next pending block across all in-progress stories, generates content, posts it to Facebook, and marks the block complete in DynamoDB — all automatically.

**Human role:** You create story YAML files and import them once. After that, the system is fully hands-off until all blocks are complete.

**Before authoring blocks**, read [`branding/narrative-styling-guide.md`](branding/narrative-styling-guide.md). It defines the creative identity, emotional tone, visual style, and audience calibration for all content on this page. Your templates, `image_style`, and `caption_notes` should reflect those standards.

**System behavior when no work remains:** If no story has pending blocks, the scheduled Lambda run will detect there is nothing to do, log a message, and exit cleanly. No error, no post, no retry.

---

## Workflow

```
1. Author story YAML locally
2. python3 scripts/import-story.py stories/my-arc.yaml
3. Lambda runs on schedule → posts next pending block → marks it complete in DynamoDB
4. Repeat until all blocks complete → story_status set to "complete"
```

To **view state** at any time: open the AWS Console → DynamoDB → `engagement-bot-stories` → Explore items, filter on `story_id`.

To **revert a block** (regenerate it): `python3 scripts/revert-block.py <story_id> <block_id>`

---

## Story YAML Format

The local file is the source of truth for authoring. After importing, the DynamoDB items are the live state.

```yaml
project:
  title: "Your Arc Title"                 # Required. Passed to the LLM as context.
  description: "One-sentence summary"     # Optional. Helps maintain arc consistency.
  default_image_count: 3                  # Optional. Default carousel images per post.
  characters: |                           # Optional. Character definitions applied to every block.
    Define each recurring character: their narrative voice/role and their visual appearance.
    Injected into every prompt so captions and image prompts stay consistent across episodes.
    See "Defining Characters" below for guidance.
  narrative_style: |                      # Optional. Story-specific narrative guidance.
    Overrides the brand default from narrative-styling-guide.md for this story only.
    Use to define unique tone, character dynamics, or emotional register.
  image_style: |                          # Optional. Story-specific image style.
    Overrides the brand default from image-styling-guide.md for this story only.
    Use to define a consistent visual aesthetic across all blocks in this story.

blocks:
  - id: 1
    status: pending                       # pending | complete (set by Lambda after posting)
    template: |
      [Your outline for this episode — see "Writing Good Templates" below]
    caption_notes: null                   # Optional. Per-episode caption guidance.
    image_count: null                     # Optional. Overrides default_image_count.

  - id: 2
    status: pending
    template: |
      [Outline for episode 2]
```

> **Styling is story-level, not block-level.** Visual and narrative style is set once on the story and applied consistently across all blocks. This ensures aesthetic continuity throughout the arc. Use `caption_notes` for per-episode operational instructions (hashtags, word count, episode-specific hooks).

### story_id

The `story_id` in DynamoDB is derived from your **filename without extension**:

```
stories/01-my-arc.yaml  →  story_id: "01-my-arc"
```

Use a numeric prefix to control posting order — stories are processed oldest-first (by `created_at` at import time). If you want one story to run before another, import it first, or use a prefix like `01-`, `02-`.

---

## Field Reference

### Project-level fields

| Field | Required | Description |
|---|---|---|
| `title` | Yes | Name of this arc. Passed to the LLM as context. |
| `description` | No | One-sentence arc summary. Helps maintain consistency across blocks. |
| `default_image_count` | No | How many carousel images per post (default comes from DDB config). |
| `characters` | No | Character definitions injected into every prompt. Defines each character's narrative voice, role, and visual appearance so they remain consistent across all episodes. See "Defining Characters" below. |
| `narrative_style` | No | Story-specific narrative guidance. Overrides brand default from `narrative-styling-guide.md`. Applied identically to every block. |
| `image_style` | No | Story-specific image style. Overrides brand default from `image-styling-guide.md`. Applied identically to every block. |

### Block-level fields (you write)

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Sequential integer. Must be unique within the story. |
| `status` | No | `pending` (default if omitted). Set to `complete` by the Lambda. |
| `template` | Yes | Your episode outline. Consumed by the LLM to generate caption + image prompts. |
| `caption_notes` | No | Per-episode caption instructions: tone, word count override (brand default is 180–240 words — see `branding/narrative-styling-guide.md`), hashtags, hooks. |
| `image_count` | No | Override `default_image_count` for this block. |

> **Image style is set at the story level, not per block.** This ensures visual continuity across all episodes in the arc. If a story has no `image_style`, the brand default from `branding/image-styling-guide.md` applies.

### Fields written by the Lambda (visible in DynamoDB)

| Field | Description |
|---|---|
| `caption` | The generated caption that was posted to Facebook. |
| `image_prompts` | List of image generation prompts sent to Gemini. |
| `posted_at` | ISO 8601 timestamp of when the post went live. |
| `facebook_post_id` | Facebook Graph API post ID. |

---

## Defining Characters

The `characters` field is the authoritative reference the LLM uses for every caption and image prompt in your story. Without it, character appearance and voice can drift across episodes. With it, descriptions stay anchored.

**What to include for each character:**

- **Name or role** — how you'll refer to them throughout (e.g., "ARIA (protagonist)", "THE WARDEN")
- **Narrative voice/role** — personality, how they speak, what they represent emotionally
- **Visual appearance** — physical description that image prompts can use consistently: hair, build, clothing, any distinctive details
- **Image composition notes** — any constraints (e.g., always shown from behind, face obscured, specific garment in this episode)

**Format:** Freetext is fine. Structuring each character as a labeled block (name, then narrative, then visual) makes it easiest for the LLM to apply correctly.

**Example:**

```yaml
characters: |
  MIRA (protagonist):
  Narrative: Quiet and observant, speaks only when certain. Carries old grief with
  practiced composure; her interiority is the reader's interiority. Refer to her
  as "she" or "her" — never by name in captions.
  Visual: Slender feminine figure, long copper-red hair worn loose or braided,
  pale freckled skin. Wears dark practical traveling clothes — long coat, worn
  leather boots. Show from behind or in silhouette; no face visible. Prompt
  language: "elegant feminine silhouette seen from behind", "graceful figure in
  a dark traveling coat", "no face visible".

  THE KEEPER (antagonist/love interest):
  Narrative: Ancient and exact. His danger is in his precision — he says only
  what is true, and the truth is always worse than a lie. Do not describe him
  as menacing; describe him as certain.
  Visual: Tall imposing masculine figure, dark formal attire with silver details,
  iron-gray hair worn short. Moves with unnatural stillness. Always show in
  deep shadow or from behind — no face visible. Prompt language: "tall figure
  in dark formal attire", "commanding presence in shadow", "broad-shouldered
  silhouette, face entirely obscured".
```

> **Characters are story-level, not block-level.** Define them once on the `project:` section. The same definitions are injected into every block's prompt automatically.

---

## Writing Good Templates

The `template` is your episode brief. The LLM uses it — plus the story `title`, `description`, and captions from completed blocks — to generate the caption and image prompts.

> **Tone and style reference:** See [`branding/narrative-styling-guide.md`](branding/narrative-styling-guide.md) for the emotional pillars, romantic dynamics, visual atmosphere, and caption style that all blocks should reflect.

**Include in each template:**

- **What happens in this episode** — the scene, moment, or idea being conveyed
- **Tone and emotion** — what feeling should this post create?
- **Key visual elements** — characters, setting, objects, lighting, mood
- **Narrative position** — where is this in the arc? (opening, rising tension, climax, resolution)
- **Any specific lines or phrases** you want verbatim in the caption (wrap in quotes)

**You do NOT need to include:**

- Hashtag lists (use `caption_notes`)
- Image style/mood (use `image_style`)
- Explicit format or length instructions (use `caption_notes`)
- Prior episode recaps — the Lambda reads completed blocks for continuity automatically

**Hard rule — never include in Key visuals or anywhere in the template:**

- **Facial features or expressions of any kind.** Do not describe a character's face, eyes, gaze, mouth, lips, expression, or any other facial attribute. The image styling guide enforces a strict no-face rule across all generated images. Facial descriptions in the template will cause the LLM to generate image prompts that violate this rule, producing unusable output.
- Instead, direct emotional weight entirely through **posture, body language, hands, clothing, and environment.** A character "standing rigid at the threshold" conveys dread. "Her hand at her side, fingers half-curled" conveys restraint. "His silhouette filling the doorway, unmoving" conveys threat. These are the tools — not the face.

**Strong template example:**

```yaml
template: |
  Episode 3 — The Confrontation.

  Maya finally confronts her mentor, Dr. Voss, in his cluttered laboratory late at night.
  She's discovered he's been publishing her research under his name. The tone is tense and
  bittersweet — there's still affection beneath the betrayal. Dr. Voss is defensive but
  clearly ashamed. The conversation ends ambiguously: Maya leaves without resolution,
  stepping out into a rainy street.

  Key visuals: dimly lit lab with papers everywhere, two figures facing each other across
  a cluttered desk, rain-streaked window, warm indoor light vs. cold blue street outside.

  Narrative position: emotional midpoint — the comfortable illusion breaks.
```

**Weak template (avoid):**

```yaml
template: |
  Something about the confrontation happens. It's emotional.
```

---

## Per-Block Overrides

### `caption_notes`

```yaml
caption_notes: "Use a cliffhanger ending. Include: #SerialFiction #MayaAndVoss"
```

> **Caption length default is 180–240 words** (see `branding/narrative-styling-guide.md`).
> Only specify a length in `caption_notes` when you want to deliberately deviate — e.g.,
> `"Under 110 words"` for a quiet arc opener, `"Under 300 words"` for a peak release moment.
> If no length is specified, the brand default applies.

### `image_count`

```yaml
image_count: 4    # More images for a visually rich episode
image_count: 1    # Single image for a quieter moment
```

---

## Complete Example — 4-Block Arc

```yaml
project:
  title: "The Cartographer's Secret"
  description: >
    A short episodic story about Elara, a mapmaker who discovers that one of her maps
    leads to a place that shouldn't exist. Four episodes: discovery, journey, arrival, revelation.
  default_image_count: 3
  image_style: >
    Painterly digital illustration with an antique ink-and-candlelight aesthetic.
    Warm amber and sepia tones against cool midnight blue. Cartographic details woven
    into environments — maps as wallpaper, as floor, as sky. Atmospheric, slightly
    surreal, prestige gothic fantasy quality. No photorealism.

blocks:
  - id: 1
    status: pending
    template: |
      Episode 1 — Discovery.

      Elara is working late in her map shop, a cozy cluttered space full of scrolls and
      ink. While archiving old stock, she unrolls a map she's never seen before — drawn
      in her own handwriting, but depicting a city she has no memory of making. The map
      is dated three years in the future.

      Tone: mysterious, quietly unsettling, wonder with an edge of dread.
      Visuals: warm candlelit map room, scrolls everywhere, Elara's face illuminated as
      she holds up the strange map, close-up of the map's impossible details.
    caption_notes: "Open with a rhetorical question. No hashtags in episode 1. Under 100 words."

  - id: 2
    status: pending
    template: |
      Episode 2 — The Journey Begins.

      Elara has decided to find the city on the map. She's packed light and is setting
      out at dawn from her village. There's excitement but also fear — she told no one.
      The road curves into unfamiliar hills. She's holding the map, comparing it to the landscape.

      Tone: adventurous, slightly lonely, determined.
      Visuals: dawn light, open road, rolling hills, Elara from behind walking away,
      her hands comparing real landscape to the mysterious map.
    caption_notes: "Reference the previous post. Include: #TheCartographersSecret"

  - id: 3
    status: pending
    template: |
      Episode 3 — Arrival.

      Elara arrives at the location marked on the map. The city IS there — but abandoned,
      frozen in time. Architecture is beautiful but decayed, overgrown with vines. The streets
      feel recently inhabited. She finds a door with her name carved into it.

      Tone: awe, unease, the feeling of a dream you can't wake from.
      Visuals: crumbling beautiful city, overgrown plaza, Elara small against tall
      architecture, close-up of her name carved on the door.
    caption_notes: "Build suspense. End mid-scene — she's reaching for the door handle. Under 130 words."
    image_count: 4

  - id: 4
    status: pending
    template: |
      Episode 4 — The Revelation. (Final episode)

      Elara opens the door and finds a room filled with maps — all in her handwriting,
      all of places that shouldn't exist. On the central table: a map of her own village,
      annotated in red, with a note: "Start here." She realizes she didn't find the city.
      The city found her. This has happened before.

      Tone: revelatory, unsettling resolution, open-ended (leave room for a sequel arc).
      Visuals: room of maps overwhelming in scale, Elara at the center, close-up of the
      note, final image — her face reflecting understanding.
    caption_notes: >
      Final episode. Thank readers for following along. Tease a possible continuation.
      Include: #TheCartographersSecret #SerialFiction #Finale
```

Import with:
```bash
python3 scripts/import-story.py stories/the-cartographers-secret.yaml
```

---

## Tips and Gotchas

- **Block order matters.** The Lambda always runs the lowest-numbered `pending` block. Number blocks in the order you want them posted.
- **story_id comes from the filename.** `01-my-arc.yaml` → `story_id = "01-my-arc"`. Re-importing the same file will overwrite all items for that story_id.
- **Do not edit completed blocks in the YAML and re-import.** Completed block items in DynamoDB have `caption`, `image_prompts`, and `posted_at` that record what actually ran. Re-importing overwrites them.
- **To regenerate a completed block:** Use `python3 scripts/revert-block.py <story_id> <block_id>`. This resets the block to `pending` in DynamoDB — no file change needed.
- **The description field earns its keep.** A good `description` helps the LLM maintain voice and consistency across all blocks, especially for long arcs.
- **Keep your source YAML files.** Store them in a `stories/` directory. They're your authoring source of truth; the DynamoDB items are the live state.
