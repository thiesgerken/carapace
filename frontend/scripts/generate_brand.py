# /// script
# requires-python = ">=3.12"
# dependencies = ["fonttools", "uharfbuzz"]
# ///
"""Generate outlined Fraunces wordmarks and copy the canonical turtle to the app.

Run with `uv run frontend/scripts/generate_brand.py /path/to/Fraunces.ttf`.
The font is only needed for regeneration, not at build time or in the browser.
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "assets"
PUBLIC = ROOT / "frontend" / "public"
SVG_NS = "http://www.w3.org/2000/svg"
AXES = {"wght": 600, "opsz": 9, "SOFT": 0, "WONK": 1}
TRACKING_EM = -0.043


def outline(font_path: Path) -> tuple[str, int, tuple[float, float, float, float]]:
    font = instantiateVariableFont(TTFont(font_path), AXES)
    upm = font["head"].unitsPerEm
    hb_font = hb.Font(hb.Face(hb.Blob.from_file_path(str(font_path))))
    hb_font.set_variations(AXES)
    buffer = hb.Buffer()
    buffer.add_str("carapace")
    buffer.guess_segment_properties()
    # Shape before outlining so kerning and ligatures match the browser preview.
    hb.shape(hb_font, buffer, {"kern": True, "liga": True})

    glyphs = font.getGlyphSet()
    order = font.getGlyphOrder()
    pen = SVGPathPen(glyphs, ntos=lambda value: f"{value:.1f}".removesuffix(".0"))
    bounds = BoundsPen(glyphs)
    x = 0.0
    for info, position in zip(buffer.glyph_infos, buffer.glyph_positions, strict=True):
        glyph = glyphs[order[info.codepoint]]
        transform = (1, 0, 0, -1, x + position.x_offset, -position.y_offset)
        glyph.draw(TransformPen(pen, transform))
        glyph.draw(TransformPen(bounds, transform))
        x += position.x_advance + TRACKING_EM * upm
    if bounds.bounds is None:
        raise ValueError("The font produced an empty wordmark")
    return pen.getCommands(), upm, bounds.bounds


def main(font_path: Path) -> None:
    path, upm, (left, top, right, bottom) = outline(font_path)
    (ASSETS / "wordmark.svg").write_text(
        f'<svg xmlns="{SVG_NS}" viewBox="{left:.1f} {top:.1f} {right - left:.1f} {bottom - top:.1f}"'
        ' role="img" aria-label="carapace">\n'
        f'  <path fill="currentColor" d="{path}"/>\n</svg>\n'
    )

    icon = (ASSETS / "icon.svg").read_text()
    (PUBLIC / "icon.svg").write_text(icon)
    ET.register_namespace("", SVG_NS)
    mark = ET.fromstring(icon).find(f"{{{SVG_NS}}}g")
    if mark is None:
        raise ValueError("The canonical icon must contain its artwork in a group")

    scale = 96 / upm
    # Align the feet (y=122 in the square icon) with the text baseline.
    # Including the p descender in the alignment makes the turtle sit too low.
    text_y = 122
    text_x = 180 - left * scale
    box_top = min(43, text_y + top * scale) - 4
    box_bottom = max(122, text_y + bottom * scale) + 4
    box_right = text_x + right * scale + 4
    for variant in ("light", "dark"):
        artwork = ET.tostring(mark, encoding="unicode")
        colour = "#236b86"
        if variant == "dark":
            # Replace in one pass: the dark shell reuses the light skin colour.
            for element in mark.iter():
                fill = element.get("fill")
                match fill:
                    case "#236b86":
                        element.set("fill", "#53b8c8")
                    case "#2f96ad":
                        element.set("fill", "#236b86")
                    case "#53b8c8":
                        element.set("fill", "#71c9d5")
            artwork = ET.tostring(mark, encoding="unicode")
            colour = "#71c9d5"
        logo = (
            f'<svg xmlns="{SVG_NS}" viewBox="8 {box_top:.1f} {box_right - 8:.1f} {box_bottom - box_top:.1f}"'
            ' role="img" aria-label="carapace">\n'
            f"  {artwork}\n"
            f'  <path fill="{colour}" transform="translate({text_x:.3f} {text_y:.3f}) scale({scale:.6f})"'
            f' d="{path}"/>\n'
            "</svg>\n"
        )
        for destination in (ASSETS, PUBLIC):
            (destination / f"logo-{variant}.svg").write_text(logo)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
