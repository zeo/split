"""Build the icon set from a master rendered on a green screen: key out the green, trim, then export."""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent
SIZE = 1024
# how far green rises above red and blue: chrome sits near 0, the screen near 200
SOLID, CLEAR = 24, 96


def key(source: Image.Image) -> Image.Image:
    rgb = np.asarray(source.convert("RGB"), dtype=np.float32)
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    spill = green - np.maximum(red, blue)
    alpha = np.clip((CLEAR - spill) / (CLEAR - SOLID), 0, 1)
    # pull leftover green out of the antialiased rim so it does not glow on dark taskbars
    rgb[..., 1] = np.minimum(green, np.maximum(red, blue) + 6)
    # keep only the tile itself; stray specks on the screen would widen the crop
    solid = Image.fromarray(((alpha > 0.5) * 255).astype(np.uint8)).copy()
    ImageDraw.floodfill(solid, (solid.width // 2, solid.height // 2), 128)
    tile = solid.point(lambda v: 255 if v == 128 else 0).filter(ImageFilter.MaxFilter(5))
    alpha *= np.asarray(tile, dtype=np.float32) / 255
    image = np.dstack([rgb, alpha * 255]).round().astype(np.uint8)
    keyed = Image.fromarray(image, "RGBA")
    return keyed.crop(keyed.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox())


def main() -> None:
    master = key(Image.open(sys.argv[1])) if len(sys.argv) > 1 else Image.open(HERE / "icon-1024.png")
    side = max(master.size)
    square = Image.new("RGBA", (side, side))
    square.paste(master, ((side - master.width) // 2, (side - master.height) // 2))
    icon = square.resize((SIZE, SIZE), Image.LANCZOS)
    icon.save(HERE / "icon-1024.png")
    icon.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.resize((180, 180), Image.LANCZOS).save(HERE.parent / "web" / "favicon.png")


if __name__ == "__main__":
    main()
