"""OpenAI content generation: build prompt, call LLM, parse response."""

import json
import logging

import openai

from branding import IMAGE_STYLE, NARRATIVE_STYLE

logger = logging.getLogger(__name__)
_client: openai.OpenAI | None = None


def _get_client() -> openai.OpenAI:
    global _client
    if _client is None:
        _client = openai.OpenAI()
    return _client


# Brand style guidance is baked in at deploy time from branding/ markdown files.
# Story-level overrides (narrative_style, image_style on STORY#META) supersede these
# defaults when present — they are injected into the user message by build_prompt().
_SYSTEM_PROMPT = f"""You are a creative social media writer and visual director producing episodic narrative content for the Read Me After Dark Facebook page.

You will be given:
- A story title and description (the overall arc)
- Captions from prior episodes (for narrative continuity)
- A template/outline for the current episode
- Optional caption notes (tone, length, hashtags, etc.)
- The number of carousel images to generate
- Style guidance: brand defaults are embedded below; the user message will note any story-specific overrides that supersede them

Your task: produce a Facebook caption and one image generation prompt per carousel image.

Respond ONLY with valid JSON in this exact shape:
{{
  "caption": "<the full post caption>",
  "image_prompts": ["<prompt 1>", "<prompt 2>", ...]
}}

Rules:
- caption: engaging, narrative-driven. Follow any caption_notes provided. Apply the active narrative style guidance.
- image_prompts: one prompt per image slot. Each prompt must:
  1. Be self-contained and usable directly by an image generation model.
  2. Cover a DISTINCT visual moment from the episode — a different subject, setting, scale, or narrative beat than every other prompt in the set. No two prompts may depict the same scene, character pose, or focal element.
  3. Vary scale across the set: include at least one wide environmental shot and one close or intimate composition.
  4. Apply the active image style guidance.
- Do not include any text outside the JSON object.

---
BRAND NARRATIVE STYLE — apply to all content unless the user message specifies a story override:

{NARRATIVE_STYLE}

---
BRAND IMAGE STYLE — apply to all image prompts unless the user message specifies a story override:

{IMAGE_STYLE}"""


def generate_content(
    block: dict,
    story: dict,
    config: dict,
    prior_blocks: list[dict],
) -> tuple[str, list[str]]:
    """Generate a caption and image prompts for the given block.

    Returns:
        (caption, image_prompts)
    """
    llm_cfg = config["llm"]
    logger.info(
        "generate_content: block_id=%d model=%s max_tokens=%s prior_blocks=%d",
        block["id"],
        llm_cfg.get("model"),
        llm_cfg.get("max_tokens", 2500),
        len(prior_blocks),
    )

    prompt = build_prompt(block, story, config, prior_blocks)
    logger.info("Prompt built — length=%d chars", len(prompt))
    logger.debug("Full prompt:\n%s", prompt)

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    logger.info("Calling OpenAI API — model=%s", llm_cfg["model"])

    try:
        response = _get_client().chat.completions.create(
            model=llm_cfg["model"],
            max_completion_tokens=llm_cfg.get("max_tokens", 2500),
            response_format={"type": "json_object"},
            messages=messages,
        )
    except Exception as exc:
        logger.error("OpenAI API call failed: %s (%s)", exc, type(exc).__name__)
        raise

    usage = response.usage
    logger.info(
        "OpenAI response received — prompt_tokens=%d completion_tokens=%d total_tokens=%d finish_reason=%s",
        usage.prompt_tokens if usage else -1,
        usage.completion_tokens if usage else -1,
        usage.total_tokens if usage else -1,
        response.choices[0].finish_reason,
    )

    raw = response.choices[0].message.content
    logger.debug("Raw LLM response (%d chars):\n%s", len(raw), raw)

    caption, image_prompts = parse_response(raw)
    logger.info(
        "Parsed response — caption_len=%d image_prompt_count=%d",
        len(caption), len(image_prompts),
    )
    for i, p in enumerate(image_prompts):
        logger.info("image_prompt[%d] (%d chars): %s", i, len(p), p[:120])

    return caption, image_prompts


def build_prompt(
    block: dict,
    story: dict,
    config: dict,
    prior_blocks: list[dict],
) -> str:
    """Construct the full LLM user prompt."""
    proj_meta = story.get("project", story)
    image_count = (
        block.get("image_count")
        or proj_meta.get("default_image_count")
        or config["images"]["count"]
    )

    logger.debug(
        "build_prompt: title=%r image_count=%d prior_blocks=%d "
        "has_characters=%s has_story_narrative_style=%s has_story_image_style=%s",
        proj_meta.get("title"), image_count, len(prior_blocks),
        bool(proj_meta.get("characters")),
        bool(proj_meta.get("narrative_style")),
        bool(proj_meta.get("image_style")),
    )

    parts = [f"Story title: {proj_meta.get('title', 'Untitled')}"]
    if proj_meta.get("description"):
        parts.append(f"Story description: {proj_meta['description'].strip()}")
    if proj_meta.get("characters"):
        parts.append(
            f"\nCHARACTER DEFINITIONS — apply consistently to every caption and image prompt in this story:\n"
            f"{proj_meta['characters'].strip()}"
        )

    if prior_blocks:
        parts.append("\nPrior episode captions (for narrative continuity):")
        for pb in prior_blocks:
            excerpt = pb.get("template", "").strip()[:300]
            parts.append(f"  Episode {pb['id']}: {excerpt}")
            logger.debug("  Including prior block id=%d excerpt_len=%d", pb["id"], len(excerpt))

    parts += [
        f"\nCurrent episode template/outline:\n{block['template'].strip()}",
        f"\nCarousel images to generate: {image_count}. Each image prompt must cover a "
        f"DIFFERENT visual moment — vary subject, scale, and narrative beat across all "
        f"{image_count} prompts. No two prompts may show the same scene or focal element.",
    ]

    if block.get("caption_notes"):
        parts.append(f"Caption notes: {block['caption_notes'].strip()}")

    # Story-level style overrides — these supersede the brand defaults in the system prompt.
    if proj_meta.get("narrative_style"):
        parts.append(
            f"\nSTORY NARRATIVE STYLE — supersedes the brand default above:\n"
            f"{proj_meta['narrative_style'].strip()}"
        )
    if proj_meta.get("image_style"):
        parts.append(
            f"\nSTORY IMAGE STYLE — supersedes the brand default above:\n"
            f"{proj_meta['image_style'].strip()}"
        )

    return "\n".join(parts)


def parse_response(response_text: str) -> tuple[str, list[str]]:
    """Extract caption and image_prompts from the JSON LLM response."""
    logger.debug("Parsing LLM response (%d chars)", len(response_text))
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as exc:
        logger.error("LLM response is not valid JSON: %s | raw: %r", exc, response_text[:500])
        raise ValueError(f"LLM response was not valid JSON: {response_text!r}") from exc

    logger.debug("Parsed JSON keys: %s", list(data.keys()))

    caption = data.get("caption", "").strip()
    image_prompts = [p.strip() for p in data.get("image_prompts", []) if p.strip()]

    if not caption:
        logger.error("LLM response missing 'caption' — raw: %r", response_text[:500])
        raise ValueError("LLM response missing 'caption' field")
    if not image_prompts:
        logger.error("LLM response missing 'image_prompts' — raw: %r", response_text[:500])
        raise ValueError("LLM response missing 'image_prompts' field")

    logger.info("parse_response OK — caption_len=%d prompts=%d", len(caption), len(image_prompts))
    return caption, image_prompts
