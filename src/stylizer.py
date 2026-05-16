"""Google Gemini image generation."""

import logging
import os
import tempfile

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gemini-2.0-flash-preview-image-generation"

_ASPECT_RATIO_MAP = {
    "1:1": "1:1",
    "4:3": "4:3",
    "3:4": "3:4",
    "16:9": "16:9",
    "9:16": "9:16",
    "4:5": "4:5",
}

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise EnvironmentError("GOOGLE_API_KEY environment variable not set")
        _client = genai.Client(api_key=api_key)
    return _client


def _generate_one_image(model_name: str, prompt: str) -> bytes:
    """Call Gemini and return raw image bytes."""
    response = _get_client().models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )
    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.mime_type.startswith("image/"):
            return part.inline_data.data
    raise RuntimeError("Gemini returned no image in response")


def generate_images(
    image_prompts: list[str],
    config: dict,
    block: dict,
) -> list[str]:
    """Generate carousel images from prompts and save to /tmp.

    Uses the image_count from the block (falling back to config default).
    If fewer prompts than image_count are provided, the last prompt is reused.

    Returns:
        List of absolute /tmp file paths to the generated images.
    """
    img_cfg = config["images"]
    proj_meta = config.get("project", {})

    model_name = img_cfg.get("model", _DEFAULT_MODEL)
    image_count = (
        block.get("image_count")
        or proj_meta.get("default_image_count")
        or img_cfg["count"]
    )
    aspect_ratio = _ASPECT_RATIO_MAP.get(img_cfg.get("aspect_ratio", "4:5"), "4:5")

    logger.info(
        "generate_images: requested image_count=%d aspect_ratio=%s input_prompts=%d model=%s",
        image_count, aspect_ratio, len(image_prompts), model_name,
    )

    # Pad or trim prompt list to match image_count
    prompts = list(image_prompts)
    if len(prompts) < image_count:
        logger.info(
            "Padding prompt list from %d to %d (reusing last prompt)",
            len(prompts), image_count,
        )
        while len(prompts) < image_count:
            prompts.append(prompts[-1])
    elif len(prompts) > image_count:
        logger.info("Trimming prompt list from %d to %d", len(prompts), image_count)
        prompts = prompts[:image_count]

    logger.info("Gemini client ready — beginning image generation loop")
    paths = []

    for i, prompt in enumerate(prompts):
        full_prompt = f"{prompt} [aspect ratio: {aspect_ratio}]"
        logger.info("Generating image %d/%d (prompt_len=%d)", i + 1, image_count, len(full_prompt))
        logger.debug("Image %d prompt: %s", i + 1, full_prompt)

        try:
            image_bytes = _generate_one_image(model_name, full_prompt)
        except Exception as exc:
            logger.error(
                "Image %d/%d generation failed — prompt=%r error=%s (%s)",
                i + 1, image_count, prompt[:80], exc, type(exc).__name__,
            )
            raise

        tmp_path = os.path.join(tempfile.gettempdir(), f"carousel_{i}.png")
        with open(tmp_path, "wb") as f:
            f.write(image_bytes)

        file_size = os.path.getsize(tmp_path)
        logger.info(
            "Image %d/%d saved — path=%s size_bytes=%d",
            i + 1, image_count, tmp_path, file_size,
        )
        paths.append(tmp_path)

    logger.info("Image generation complete — %d image(s) saved to /tmp", len(paths))
    return paths
