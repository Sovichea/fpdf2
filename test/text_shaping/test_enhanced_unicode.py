# pylint: disable=protected-access

import re
from pathlib import Path
from types import SimpleNamespace

from pypdf import PdfReader

from fpdf import FPDF
from fpdf.fonts import TTFFont

HERE = Path(__file__).resolve().parent


def _force_logical_capacity(monkeypatch, capacity):
    original = TTFFont._get_or_create_logical_glyph_on

    def limited(self, target, unicode, advance_width, components):
        key = self._logical_key(unicode, advance_width, components)
        if key not in target._logical_records and len(target._logical_records) >= capacity:
            return None
        return original(self, target, unicode, advance_width, components)

    monkeypatch.setattr(TTFFont, "_get_or_create_logical_glyph_on", limited)


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


def test_enhanced_unicode_rtl_run_shards_are_page_resources(
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

    referenced_fonts = {
        f"/F{font_id.decode()}"
        for font_id in re.findall(rb"/F(\d+)\s+[0-9.]+\s+Tf", data)
    }
    page_fonts = set(PdfReader(str(output)).pages[0]["/Resources"]["/Font"].keys())

    assert len(referenced_fonts) > 1
    assert referenced_fonts <= page_fonts
    assert b" TJ " in data or b"] TJ" in data


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


def _logical_font():
    pdf = FPDF()
    pdf.add_font(family="KhmerOS", fname=HERE / "KhmerOS.ttf")
    font = pdf.fonts["khmeros"]
    assert isinstance(font, TTFFont)
    return font


def _logical_visual(font, char="A"):
    glyph_name = font.cmap[ord(char)]
    glyph_id = font.ttfont.getGlyphID(glyph_name)
    advance = int(font.ttfont["hmtx"].metrics[glyph_name][0])
    return advance, ((glyph_id, 0, 0),), glyph_name


def test_enhanced_unicode_v4_distinct_semantics_share_visual():
    font = _logical_font()
    advance, components, glyph_name = _logical_visual(font)

    first = font._get_or_create_logical_glyph((ord("A"),), advance, components)
    second = font._get_or_create_logical_glyph(
        (ord("A"), 0x0301), advance, components
    )

    assert first is not None and second is not None
    assert first[0] is second[0]
    assert first[2] != second[2]
    assert first[1].glyph_name == second[1].glyph_name == glyph_name
    assert len(first[0]._logical_glyphs) == 1
    assert first[0]._logical_embedded_glyph_count(first[0]) == 2


def test_enhanced_unicode_v4_changed_advance_is_synthetic():
    font = _logical_font()
    advance, components, _ = _logical_visual(font)
    record = font._get_or_create_logical_glyph(
        (ord("A"),), advance - 1, components
    )

    assert record is not None
    assert record[1].glyph_name.startswith(".fpdf2.logical.")


def test_enhanced_unicode_v4_real_semantic_cid_limit():
    font = _logical_font()
    advance, components, _ = _logical_visual(font)

    for index in range(0x10000):
        font._get_or_create_logical_glyph(
            (ord("A"), index), advance, components
        )

    assert len(font.get_logical_shards()) == 2
    first, second = font.get_logical_shards()
    assert len(first._logical_records) == 0xFFFF
    assert len(second._logical_records) == 1
    assert len(first._logical_glyphs) == 1
    assert len(second._logical_glyphs) == 1


def test_enhanced_unicode_v4_large_document_reuse_does_not_shard():
    font = _logical_font()
    advance, components, _ = _logical_visual(font)
    semantics = [(ord("A"), index) for index in range(128)]

    for occurrence in range(1_000_000):
        font._get_or_create_logical_glyph(
            semantics[occurrence % len(semantics)],
            advance,
            components,
        )

    assert len(font.get_logical_shards()) == 1
    shard = font.get_logical_shards()[0]
    assert len(shard._logical_records) == len(semantics)
    assert len(shard._logical_glyphs) == 1
    assert shard._logical_embedded_glyph_count(shard) <= 3


def test_enhanced_unicode_v4_real_compact_gid_limit():
    font = _logical_font()
    advance, components, _ = _logical_visual(font)
    glyph_id = components[0][0]

    pairs = (
        (x, y)
        for x in range(-128, 128)
        for y in range(-128, 128)
        if (x, y) != (0, 0)
    )
    for index, (x, y) in enumerate(pairs):
        if index >= 65_534:
            break
        font._get_or_create_logical_glyph(
            (ord("A"), index),
            advance,
            ((glyph_id, x, y),),
        )

    assert len(font.get_logical_shards()) == 2
    first, second = font.get_logical_shards()
    assert first._logical_embedded_glyph_count(first) == 0xFFFF
    assert len(first._logical_records) == 65_533
    assert len(second._logical_records) == 1
    assert second._logical_embedded_glyph_count(second) == 3
