"""Embed character card JSON into a PNG file as tEXt metadata chunk."""
import base64
import json
import os
from PIL import Image
from PIL.PngImagePlugin import PngInfo


def embed(card_json: dict, png_path: str, output_path: str) -> str:
    """Write character card JSON into PNG metadata and save.

    Args:
        card_json: Complete character card dict (v2 spec envelope).
        png_path: Path to source PNG image (portrait).
        output_path: Destination path for the final character card PNG.

    Returns:
        output_path on success.
    """
    # Remove internal fields before embedding
    clean = {k: v for k, v in card_json.items() if not k.startswith("_")}
    json_str = json.dumps(clean, ensure_ascii=False)
    encoded = base64.b64encode(json_str.encode("utf-8")).decode("ascii")

    img = Image.open(png_path)
    pnginfo = PngInfo()
    pnginfo.add_text("chara", encoded)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    img.save(output_path, "PNG", pnginfo=pnginfo)
    return output_path


def build_placeholder_card(output_path: str, width: int = 512, height: int = 512) -> str:
    """Generate a solid-color placeholder PNG when no portrait is available."""
    from PIL import ImageDraw
    img = Image.new("RGBA", (width, height), (30, 30, 40, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([2, 2, width - 3, height - 3], outline=(80, 80, 100, 200), width=2)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    img.save(output_path, "PNG")
    return output_path
