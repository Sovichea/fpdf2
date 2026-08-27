# pylint: disable=protected-access

import re
from pathlib import Path
from types import SimpleNamespace

from pypdf import PdfReader

from fpdf import FPDF
from fpdf.fonts import TTFFont

HERE = Path(__file__).resolve().parent


def _force_logical_capacity(monkeypatch, capacity):
    monkeypatch.setattr(
        TTFFont,
        "_logical_font_remaining_capacity",
        lambda _self, font: max(0, capacity - len(font._logical_glyphs)),
    )
    monkeypatch.setattr(
        TTFFont,
        "_logical_new_shard_capacity",
        lambda _self: capacity,
    )


def test_enhanced_unicode_extracts_khmer_exactly(tmp_path):
    text = "ក្ស សួស្តី ពិភពលោក"
    output = tmp_path / "khmer-logical.pdf"

    pdf = FPDF()
    pdf.add_page()
    pdf.add_font(family="KhmerOS", fname=HERE / "KhmerOS.ttf")
    pdf.set_font("KhmerOS", size=30)
    pdf.set_text_shaping(True, enhanced_unicode=True)
    pdf.cell(text=text)
    pdf.output(output)

    extracted = PdfReader(str(output)).pages[0].extract_text().strip()
    assert extracted == text


def test_enhanced_unicode_forced_shards_are_page_resources(tmp_path, monkeypatch):
    _force_logical_capacity(monkeypatch, 2)
    text = "ក្ស សួស្តី ពិភពលោក"
    output = tmp_path / "khmer-sharded.pdf"

    pdf = FPDF()
    pdf.set_compression(False)
    pdf.add_page()
    pdf.add_font(family="KhmerOS", fname=HERE / "KhmerOS.ttf")
    pdf.set_font("KhmerOS", size=30)
    pdf.set_text_shaping(True, enhanced_unicode=True)
    pdf.cell(text=text)
    pdf.output(output)
    data = output.read_bytes()

    referenced_fonts = {
        f"/F{font_id.decode()}"
        for font_id in re.findall(rb"/F(\d+)\s+[0-9.]+\s+Tf", data)
    }
    reader = PdfReader(str(output))
    page_fonts = set(reader.pages[0]["/Resources"]["/Font"].keys())

    assert len(referenced_fonts) > 1
    assert referenced_fonts <= page_fonts
    assert reader.pages[0].extract_text().strip() == text


def test_enhanced_unicode_rtl_run_uses_geometry_aware_affinity(
    tmp_path, monkeypatch
):
    _force_logical_capacity(monkeypatch, 10)
    output = tmp_path / "hebrew-sharded.pdf"

    pdf = FPDF()
    pdf.set_compression(False)
    pdf.add_page()
    pdf.add_font(family="SBL_Hbrw", fname=HERE / "SBL_Hbrw.ttf")
    pdf.set_font("SBL_Hbrw", size=28)
    pdf.set_text_shaping(True, direction="rtl", enhanced_unicode=True)
    pdf.cell(text="אבגדהוזח", new_x="LEFT", new_y="NEXT")
    pdf.cell(text="שלום עולם")
    pdf.output(output)
    data = output.read_bytes()

    font_sequence = re.findall(rb"/F(\d+)\s+[0-9.]+\s+Tf", data)
    switches = sum(
        left != right for left, right in zip(font_sequence, font_sequence[1:])
    )

    # The second RTL shaping run cannot fit in the partially occupied base shard.
    # Geometry-aware affinity rolls it into one shard instead of repeatedly
    # switching between the base font and a shard inside the source-ordered run.
    assert len(set(font_sequence)) == 2
    assert switches == 2


def test_enhanced_unicode_rejects_oversized_logical_unit(monkeypatch):
    pdf = FPDF()
    pdf.add_font(family="KhmerOS", fname=HERE / "KhmerOS.ttf")
    font = pdf.fonts["khmeros"]
    assert isinstance(font, TTFFont)

    codepoint, glyph_name = next(iter(font.cmap.items()))
    glyph_id = font.ttfont.getGlyphID(glyph_name)
    upem = int(font.ttfont["head"].unitsPerEm)
    oversized_advance = 0x7FFF - 2 * upem + 1

    monkeypatch.setattr(
        TTFFont,
        "perform_harfbuzz_shaping",
        lambda _self, _text, _font_size_pt, _params: (
            [SimpleNamespace(codepoint=glyph_id, cluster=0)],
            [
                SimpleNamespace(
                    x_advance=oversized_advance,
                    y_advance=0,
                    x_offset=0,
                    y_offset=0,
                )
            ],
        ),
    )

    before = len(font.ttfont.getGlyphOrder())
    result = font.shape_text_logical(chr(codepoint), 12, {"features": {}})

    assert result is None
    assert len(font.ttfont.getGlyphOrder()) == before
