"""The item's name in its quality colour, drawn as a picture: Discord can't colour a bot's text.

A wide, transparent PNG at twice the size it shows at: Discord fits a gallery image to the card's
width, so the fixed width keeps the name the same size on every item and sharp on high-DPI screens.
The font is Philosopher Bold (SIL Open Font License, assets/Philosopher-OFL.txt), close to WoW's.
"""
from __future__ import annotations

import io
import pathlib

from PIL import Image, ImageDraw, ImageFont

FONT = pathlib.Path(__file__).resolve().parent / "assets" / "Philosopher-Bold.ttf"
FILENAME = "title.png"
WIDTH, HEIGHT = 1000, 84
ICON = 64
TEXT_X = ICON + 22
FONT_SIZE, MIN_FONT_SIZE = 50, 30


def _font(name: str, room: int) -> ImageFont.FreeTypeFont:
    """The largest size up to FONT_SIZE at which the name fits."""
    size = FONT_SIZE
    font = ImageFont.truetype(str(FONT), size)
    while size > MIN_FONT_SIZE and font.getlength(name) > room:
        size -= 2
        font = ImageFont.truetype(str(FONT), size)
    return font


def render(name: str, colour: int, icon: bytes | None = None) -> bytes:
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x = 0
    if icon:
        try:
            pic = Image.open(io.BytesIO(icon)).convert("RGBA").resize((ICON, ICON), Image.LANCZOS)
        except OSError:
            pic = None
        if pic is not None:
            top = (HEIGHT - ICON) // 2
            mask = Image.new("L", (ICON, ICON), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, ICON - 1, ICON - 1), radius=8, fill=255)
            img.paste(pic, (0, top), mask)
            draw.rounded_rectangle((0, top, ICON - 1, top + ICON - 1), radius=8, outline=(20, 20, 20, 255), width=2)
            x = TEXT_X
    font = _font(name, WIDTH - x - 8)
    fill = f"#{colour:06x}"
    # A dark shadow as in game, which also keeps light colours readable on Discord's light theme.
    draw.text((x + 3, HEIGHT // 2 + 3), name, font=font, fill=(0, 0, 0, 200), anchor="lm")
    draw.text((x, HEIGHT // 2), name, font=font, fill=fill, anchor="lm")
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()
