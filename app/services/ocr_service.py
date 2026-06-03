import logging
from io import BytesIO

from PIL import Image, ImageEnhance, ImageFilter

logger = logging.getLogger(__name__)

# Max dimension sent to the LLM (keeps token count manageable while retaining detail)
_MAX_DIMENSION = 2048


def load_image_from_bytes(data: bytes) -> Image.Image:
    """Load a PIL Image from raw bytes, raising ValueError on failure."""
    try:
        img = Image.open(BytesIO(data))
        img.load()  # force decode
        return img
    except Exception as exc:
        raise ValueError(f"Invalid image data: {exc}") from exc


def preprocess_image(img: Image.Image) -> Image.Image:
    """Resize, normalise, and sharpen an image before sending it to the LLM."""
    # Normalise colour mode
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Downscale if too large
    w, h = img.size
    if max(w, h) > _MAX_DIMENSION:
        ratio = _MAX_DIMENSION / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    # Enhance contrast slightly
    img = ImageEnhance.Contrast(img).enhance(1.2)

    # Sharpen
    img = img.filter(ImageFilter.SHARPEN)

    return img
