from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from fontTools.ttLib import TTFont
from pypdf import PdfReader

from fpdf import FPDF
from fpdf.fonts import TTFFont
from fpdf.logical_units import (
    LogicalComponent,
    LogicalFontMapper,
    VisualUnitKey,
    build_compact_logical_font,
    map_harfbuzz_logical_units,
    source_font_bytes,
)

HERE = Path(__file__).resolve().parent


def _font():
    pdf = FPDF()
    pdf.add_font(family="KhmerOS", fname=HERE / "KhmerOS.ttf")
    pdf.set_font("KhmerOS", size=12)
    assert isinstance(pdf.current_font, TTFFont)
    return pdf, pdf.current_font


def _source_visual(font, char):
    glyph_name = font.ttfont.getBestCmap()[ord(char)]
    glyph_id = font.ttfont.getGlyphID(glyph_name)
    advance = int(font.ttfont["hmtx"].metrics[glyph_name][0])
    return VisualUnitKey(
        advance_width=advance,
        components=(LogicalComponent(glyph_id, 0, 0),),
    )


def test_distinct_semantics_share_one_visual_gid():
    _pdf, font = _font()
    mapper = LogicalFontMapper(font)
    visual = _source_visual(font, "A")

    first = mapper.add((ord("A"),), visual)
    second = mapper.add((ord("A"), 0x0301), visual)

    assert first.resource_id == second.resource_id
    assert first.cid != second.cid
    assert len(mapper.shards) == 1
    assert len(mapper.shards[0].semantics) == 2
    assert len(mapper.shards[0].visuals) == 1

    compact = build_compact_logical_font(
        source_font_bytes(font.ttfont), mapper.shards[0]
    )
    assert len(compact.visual_gids) == 1


def test_changed_advance_uses_synthetic_compact_glyph():
    _pdf, font = _font()
    mapper = LogicalFontMapper(font)
    source = _source_visual(font, "A")
    changed = VisualUnitKey(
        advance_width=source.advance_width - 1,
        components=source.components,
    )

    mapper.add((ord("A"),), source)
    mapper.add((ord("B"),), changed)
    shard = mapper.shards[0]

    compact = build_compact_logical_font(source_font_bytes(font.ttfont), shard)
    compact_font = TTFont(BytesIO(compact.font_bytes), recalcTimestamp=False)

    assert compact.visual_gids[0] != compact.visual_gids[1]
    assert compact.visual_gids[1] == compact_font["maxp"].numGlyphs - 1
    assert compact_font["maxp"].numGlyphs == shard.compact_glyphs.glyph_count()


def test_multi_component_visual_builds_composite_glyph():
    _pdf, font = _font()
    mapper = LogicalFontMapper(font)
    first = _source_visual(font, "A")
    second = _source_visual(font, "B")
    visual = VisualUnitKey(
        advance_width=first.advance_width + second.advance_width,
        components=(
            first.components[0],
            LogicalComponent(
                second.components[0].glyph_id,
                first.advance_width,
                20,
            ),
        ),
    )

    mapper.add((ord("A"), ord("B")), visual)
    compact = build_compact_logical_font(
        source_font_bytes(font.ttfont), mapper.shards[0]
    )
    compact_font = TTFont(BytesIO(compact.font_bytes), recalcTimestamp=False)
    glyph = compact_font["glyf"][
        compact_font.getGlyphOrder()[compact.visual_gids[0]]
    ]

    assert glyph.isComposite()
    assert len(glyph.components) == 2
    assert glyph.components[1].x == first.advance_width
    assert glyph.components[1].y == 20


def test_semantic_and_compact_gid_capacity_shard_independently():
    _pdf, font = _font()
    first = _source_visual(font, "A")
    second = _source_visual(font, "B")

    semantic_mapper = LogicalFontMapper(font, semantic_capacity=1)
    semantic_mapper.add((ord("A"),), first)
    semantic_mapper.add((ord("B"),), first)
    assert len(semantic_mapper.shards) == 2

    gid_mapper = LogicalFontMapper(font, embedded_glyph_capacity=2)
    gid_mapper.add((ord("A"),), first)
    gid_mapper.add((ord("B"),), second)
    assert len(gid_mapper.shards) == 2


def test_harfbuzz_clusters_emit_semantic_order_with_visual_positions():
    _pdf, font = _font()
    mapper = LogicalFontMapper(font)
    first = _source_visual(font, "A")
    second = _source_visual(font, "B")

    infos = [
        SimpleNamespace(cluster=1, codepoint=second.components[0].glyph_id),
        SimpleNamespace(cluster=0, codepoint=first.components[0].glyph_id),
    ]
    positions = [
        SimpleNamespace(
            x_advance=second.advance_width,
            y_advance=0,
            x_offset=0,
            y_offset=0,
        ),
        SimpleNamespace(
            x_advance=first.advance_width,
            y_advance=0,
            x_offset=0,
            y_offset=0,
        ),
    ]

    units = map_harfbuzz_logical_units("AB", infos, positions, mapper)

    assert [unit.cluster for unit in units] == [0, 1]
    assert [unit.visual_order for unit in units] == [1, 0]
    assert units[0].visual_x == second.advance_width
    assert units[1].visual_x == 0
    assert [record.unicode for record in mapper.shards[0].semantics] == [
        (ord("A"),),
        (ord("B"),),
    ]


def test_khmer_shaping_embeds_logical_font_and_extracts_unicode():
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font(family="KhmerOS", fname=HERE / "KhmerOS.ttf")
    pdf.set_font("KhmerOS", size=30)
    pdf.set_text_shaping(True)

    text = "សួស្តី"
    pdf.cell(text=text)
    output = bytes(pdf.output())

    page = PdfReader(BytesIO(output)).pages[0]
    assert page.extract_text().strip() == text

    fonts = page["/Resources"]["/Font"]
    logical_fonts = [
        font_ref.get_object()
        for font_ref in fonts.values()
        if "Logical" in str(font_ref.get_object().get("/BaseFont", ""))
    ]
    assert logical_fonts
    descendant = logical_fonts[0]["/DescendantFonts"][0].get_object()
    assert descendant["/Subtype"] == "/CIDFontType2"
    assert "/CIDToGIDMap" in descendant
