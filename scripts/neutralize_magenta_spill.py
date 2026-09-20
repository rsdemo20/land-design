"""Replace residual magenta chroma spill in transparent tree textures."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def neutralize_pixel(red: int, green: int, blue: int, alpha: int):
    magenta_excess = min(red, blue) - green
    if alpha == 0 or magenta_excess <= 3 or red < 18 or blue < 18:
        return red, green, blue, alpha

    strength = min(1.0, (magenta_excess - 3) / 28)
    luminance = 0.299 * red + 0.587 * green + 0.114 * blue
    leaf_green = (
        min(255, int(luminance * 0.58)),
        min(255, int(luminance * 1.18 + 12)),
        min(255, int(luminance * 0.44)),
    )
    return (
        round(red + (leaf_green[0] - red) * strength),
        round(green + (leaf_green[1] - green) * strength),
        round(blue + (leaf_green[2] - blue) * strength),
        alpha,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    image = Image.open(args.input).convert("RGBA")
    pixels = image.get_flattened_data()
    image.putdata([neutralize_pixel(*pixel) for pixel in pixels])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output)


if __name__ == "__main__":
    main()
