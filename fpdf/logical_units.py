"""Internal PDF logical-unit mapping and compact TrueType construction.

This module implements the TrueType side of the PDF Logical Units v4 model:
semantic CIDs and embedded glyph IDs are independent namespaces. It is internal
and may change without notice.
"""

# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportCallIssue=false, reportArgumentType=false

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any, Iterable, Optional

from fontTools import subset as ftsubset
from fontTools.misc.transform import Transform
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from .errors import FPDFException

MAX_CID = 0xFFFF
MAX_GLYPHS = 0xFFFF
LOGICAL_FONT_RESOURCE_BASE = 0x10000000


@dataclass(frozen=True)
class LogicalComponent:
    glyph_id: int
    x: int
    y: int


@dataclass(frozen=True)
class VisualUnitKey:
    advance_width: int
    components: tuple[LogicalComponent, ...]


@dataclass(frozen=True)
class SemanticUnitKey:
    unicode: tuple[int, ...]
    visual: VisualUnitKey


@dataclass(frozen=True)
class LogicalSemanticRecord:
    unicode: tuple[int, ...]
    visual_index: int


@dataclass(frozen=True)
class LogicalMappedUnit:
    resource_id: int
    cid: int


@dataclass(frozen=True)
class CompactLogicalFont:
    font_bytes: bytes
    visual_gids: tuple[int, ...]


@dataclass(frozen=True)
class LogicalShapedUnit:
    mapped: LogicalMappedUnit
    cluster: int
    visual_x: int
    visual_y: int
    visual_order: int
    advance_width: int
    is_space: bool
    run_x_advance: int
    run_y_advance: int


def map_harfbuzz_logical_units(
    text: str,
    glyph_infos: Iterable[Any],
    glyph_positions: Iterable[Any],
    mapper: "LogicalFontMapper",
) -> list[LogicalShapedUnit]:
    infos = list(glyph_infos)
    positions = list(glyph_positions)
    if len(infos) != len(positions):
        raise FPDFException(
            "HarfBuzz returned mismatched glyph info and position arrays"
        )
    if not infos:
        return []

    clusters = sorted({int(info.cluster) for info in infos})
    cluster_unicode: dict[int, tuple[int, ...]] = {}
    for index, cluster in enumerate(clusters):
        end = clusters[index + 1] if index + 1 < len(clusters) else len(text)
        if cluster < 0 or cluster > end or end > len(text):
            raise FPDFException("HarfBuzz returned an invalid text cluster")
        cluster_unicode[cluster] = tuple(ord(char) for char in text[cluster:end])

    groups: dict[int, dict[str, Any]] = {}
    pen_x = 0
    pen_y = 0
    visual_order = 0
    for info, position in zip(infos, positions):
        cluster = int(info.cluster)
        group = groups.get(cluster)
        if group is None:
            group = {
                "start_x": pen_x,
                "start_y": pen_y,
                "visual_order": visual_order,
                "glyphs": [],
            }
            groups[cluster] = group
            visual_order += 1
        group["glyphs"].append(
            (
                int(info.codepoint),
                pen_x,
                pen_y,
                int(position.x_advance),
                int(position.y_advance),
                int(position.x_offset),
                int(position.y_offset),
            )
        )
        pen_x += int(position.x_advance)
        pen_y += int(position.y_advance)

    result: list[LogicalShapedUnit] = []
    for cluster in clusters:
        group = groups[cluster]
        start_x = int(group["start_x"])
        start_y = int(group["start_y"])
        min_x = 0
        max_x = 0
        for _, glyph_pen_x, _, x_advance, _, _, _ in group["glyphs"]:
            local_x = glyph_pen_x - start_x
            min_x = min(min_x, local_x, local_x + x_advance)
            max_x = max(max_x, local_x, local_x + x_advance)

        components = []
        for (
            glyph_id,
            glyph_pen_x,
            glyph_pen_y,
            _x_advance,
            _y_advance,
            x_offset,
            y_offset,
        ) in group["glyphs"]:
            components.append(
                LogicalComponent(
                    glyph_id=glyph_id,
                    x=glyph_pen_x - start_x + x_offset - min_x,
                    y=glyph_pen_y - start_y + y_offset,
                )
            )

        visual = VisualUnitKey(
            advance_width=max_x - min_x,
            components=tuple(components),
        )
        unicode = cluster_unicode[cluster]
        result.append(
            LogicalShapedUnit(
                mapped=mapper.add(unicode, visual),
                cluster=cluster,
                visual_x=start_x + min_x,
                visual_y=start_y,
                visual_order=int(group["visual_order"]),
                advance_width=visual.advance_width,
                is_space=unicode == (0x20,),
                run_x_advance=pen_x,
                run_y_advance=pen_y,
            )
        )
    return result


class CompactGlyphTracker:
    def __init__(self, ttfont: TTFont) -> None:
        self.ttfont = ttfont
        self.source_gids: set[int] = {0}
        self.synthetic_visuals: set[VisualUnitKey] = set()
        self._dependency_cache: dict[int, frozenset[int]] = {}

    def _dependencies(
        self, gid: int, visiting: Optional[set[int]] = None
    ) -> frozenset[int]:
        if gid in self._dependency_cache:
            return self._dependency_cache[gid]
        glyph_order = self.ttfont.getGlyphOrder()
        if gid < 0 or gid >= len(glyph_order):
            raise FPDFException(
                f"Logical unit references invalid source glyph ID {gid}"
            )
        if visiting is None:
            visiting = set()
        if gid in visiting:
            raise FPDFException("Cyclic TrueType composite glyph dependency")
        visiting.add(gid)
        deps = {gid}
        glyf = self.ttfont["glyf"]
        glyph = glyf[glyph_order[gid]]
        if glyph.isComposite():
            for component in glyph.components:
                deps.update(
                    self._dependencies(
                        self.ttfont.getGlyphID(component.glyphName), visiting
                    )
                )
        visiting.remove(gid)
        result = frozenset(deps)
        self._dependency_cache[gid] = result
        return result

    def _source_backed(self, visual: VisualUnitKey) -> bool:
        if len(visual.components) != 1:
            return False
        component = visual.components[0]
        if component.x != 0 or component.y != 0:
            return False
        name = self.ttfont.getGlyphName(component.glyph_id)
        nominal_advance = int(self.ttfont["hmtx"].metrics[name][0])
        return visual.advance_width == nominal_advance

    def plan(self, visual: VisualUnitKey) -> tuple[frozenset[int], bool]:
        for component in visual.components:
            if not (
                -0x8000 <= component.x <= 0x7FFF and -0x8000 <= component.y <= 0x7FFF
            ):
                raise FPDFException(
                    "Logical TrueType component translation exceeds signed 16-bit range"
                )
        source_gids: set[int] = set()
        for component in visual.components:
            source_gids.update(self._dependencies(component.glyph_id))
        synthetic = not self._source_backed(visual)
        return frozenset(source_gids), synthetic

    def can_commit(self, visual: VisualUnitKey, capacity: int = MAX_GLYPHS) -> bool:
        source_gids, synthetic = self.plan(visual)
        source_count = len(self.source_gids | set(source_gids))
        synthetic_count = len(self.synthetic_visuals)
        if synthetic and visual not in self.synthetic_visuals:
            synthetic_count += 1
        return source_count + synthetic_count <= capacity

    def commit(self, visual: VisualUnitKey) -> None:
        source_gids, synthetic = self.plan(visual)
        self.source_gids.update(source_gids)
        if synthetic:
            self.synthetic_visuals.add(visual)

    def glyph_count(self) -> int:
        return len(self.source_gids) + len(self.synthetic_visuals)

    def is_source_backed(self, visual: VisualUnitKey) -> bool:
        return self._source_backed(visual)


class LogicalFontShard:
    def __init__(self, font: Any, index: int) -> None:
        self.font = font
        self.index = index
        self.resource_id = LOGICAL_FONT_RESOURCE_BASE + (font.i << 16) + index
        self.visuals: list[VisualUnitKey] = []
        self.visual_map: dict[VisualUnitKey, int] = {}
        self.semantics: list[LogicalSemanticRecord] = []
        self.compact_glyphs = CompactGlyphTracker(font.ttfont)

    def plan_addition(
        self,
        visual: VisualUnitKey,
        semantic_capacity: int,
        embedded_glyph_capacity: int,
    ) -> bool:
        if len(self.semantics) >= min(semantic_capacity, MAX_CID):
            return False
        if visual in self.visual_map:
            return True
        return self.compact_glyphs.can_commit(visual, embedded_glyph_capacity)

    def add(self, unicode: tuple[int, ...], visual: VisualUnitKey) -> int:
        visual_index = self.visual_map.get(visual)
        if visual_index is None:
            self.compact_glyphs.commit(visual)
            visual_index = len(self.visuals)
            self.visuals.append(visual)
            self.visual_map[visual] = visual_index
        cid = len(self.semantics) + 1
        if cid > MAX_CID:
            raise FPDFException("Logical font semantic CID capacity exceeded")
        self.semantics.append(LogicalSemanticRecord(unicode, visual_index))
        return cid


class LogicalFontMapper:
    def __init__(
        self,
        font: Any,
        semantic_capacity: int = MAX_CID,
        embedded_glyph_capacity: int = MAX_GLYPHS,
    ) -> None:
        self.font = font
        self.semantic_capacity = semantic_capacity
        self.embedded_glyph_capacity = embedded_glyph_capacity
        self.semantic_records: dict[SemanticUnitKey, LogicalMappedUnit] = {}
        self.shards: list[LogicalFontShard] = []

    def clone_for_font(self, font: Any) -> "LogicalFontMapper":
        clone = LogicalFontMapper(
            font,
            semantic_capacity=self.semantic_capacity,
            embedded_glyph_capacity=self.embedded_glyph_capacity,
        )
        clone.semantic_records = dict(self.semantic_records)
        for old in self.shards:
            shard = LogicalFontShard(font, old.index)
            shard.visuals = list(old.visuals)
            shard.visual_map = dict(old.visual_map)
            shard.semantics = list(old.semantics)
            shard.compact_glyphs.source_gids = set(old.compact_glyphs.source_gids)
            shard.compact_glyphs.synthetic_visuals = set(
                old.compact_glyphs.synthetic_visuals
            )
            shard.compact_glyphs._dependency_cache = dict(
                old.compact_glyphs._dependency_cache
            )
            clone.shards.append(shard)
        return clone

    def add(self, unicode: tuple[int, ...], visual: VisualUnitKey) -> LogicalMappedUnit:
        key = SemanticUnitKey(unicode, visual)
        existing = self.semantic_records.get(key)
        if existing is not None:
            return existing

        shard: Optional[LogicalFontShard] = self.shards[-1] if self.shards else None
        if shard is None or not shard.plan_addition(
            visual, self.semantic_capacity, self.embedded_glyph_capacity
        ):
            shard = LogicalFontShard(self.font, len(self.shards))
            if not shard.plan_addition(
                visual, self.semantic_capacity, self.embedded_glyph_capacity
            ):
                raise FPDFException(
                    "One logical visual exceeds the physical TrueType font capacity"
                )
            self.shards.append(shard)

        cid = shard.add(unicode, visual)
        result = LogicalMappedUnit(shard.resource_id, cid)
        self.semantic_records[key] = result
        return result


def _subset_options() -> ftsubset.Options:
    options = ftsubset.Options(notdef_outline=True, recommended_glyphs=False)
    options.drop_tables += [
        "FFTM",
        "GDEF",
        "GPOS",
        "GSUB",
        "MATH",
        "hdmx",
        "meta",
        "sbix",
        "CBDT",
        "CBLC",
        "EBDT",
        "EBLC",
        "EBSC",
        "SVG ",
        "CPAL",
        "COLR",
    ]
    return options


def build_compact_logical_font(
    source_font_bytes: bytes,
    shard: LogicalFontShard,
) -> CompactLogicalFont:
    ttfont = TTFont(BytesIO(source_font_bytes), recalcTimestamp=False, lazy=False)
    source_order = ttfont.getGlyphOrder()
    required_names = [
        source_order[gid] for gid in sorted(shard.compact_glyphs.source_gids)
    ]

    subsetter = ftsubset.Subsetter(_subset_options())
    subsetter.populate(glyphs=required_names)
    subsetter.subset(ttfont)

    visual_gids: list[int] = []
    for visual in shard.visuals:
        if shard.compact_glyphs.is_source_backed(visual):
            source_gid = visual.components[0].glyph_id
            source_name = source_order[source_gid]
            compact_gid = ttfont.getGlyphID(source_name)
            visual_gids.append(compact_gid)
            continue

        if not 0 <= visual.advance_width <= 0xFFFF:
            raise FPDFException(
                "Logical unit advance does not fit TrueType hmtx"
            )

        pen = TTGlyphPen(ttfont.getGlyphSet())
        for component in visual.components:
            source_name = source_order[component.glyph_id]
            pen.addComponent(
                source_name,
                Transform(1, 0, 0, 1, component.x, component.y),
            )
        synthetic_name = f"fpdfLogical{len(visual_gids):05d}"
        while synthetic_name in ttfont.getGlyphOrder():
            synthetic_name += "_"
        synthetic_glyph = pen.glyph()
        ttfont["glyf"][synthetic_name] = synthetic_glyph
        synthetic_glyph.recalcBounds(ttfont["glyf"])
        ttfont["hmtx"].metrics[synthetic_name] = (
            visual.advance_width,
            synthetic_glyph.xMin,
        )
        visual_gids.append(len(ttfont.getGlyphOrder()) - 1)

    output = BytesIO()
    ttfont.save(output)
    ttfont.close()
    return CompactLogicalFont(output.getvalue(), tuple(visual_gids))


def source_font_bytes(ttfont: TTFont) -> bytes:
    output = BytesIO()
    ttfont.save(output)
    return output.getvalue()
