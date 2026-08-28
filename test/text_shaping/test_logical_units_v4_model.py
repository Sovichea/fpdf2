from dataclasses import dataclass


@dataclass(frozen=True)
class VisualUnitKey:
    glyph_id: int
    advance: int


@dataclass(frozen=True)
class SemanticUnitKey:
    unicode: tuple[int, ...]
    visual: VisualUnitKey


def test_distinct_semantics_can_share_visual_identity():
    visual = VisualUnitKey(glyph_id=17, advance=600)

    first = SemanticUnitKey((ord("f"), ord("i")), visual)
    second = SemanticUnitKey((0xFB01,), visual)

    assert first != second
    assert first.visual == second.visual


def test_distinct_visuals_do_not_share_visual_identity():
    first = VisualUnitKey(glyph_id=17, advance=600)
    second = VisualUnitKey(glyph_id=17, advance=610)

    assert first != second
