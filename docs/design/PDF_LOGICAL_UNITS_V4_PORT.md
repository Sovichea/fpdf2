# PDF logical units v4 port for fpdf2

This note maps the Krilla logical-unit v4 architecture onto fpdf2's current
TrueType shaping and PDF output pipeline.

Reference architecture:
Sovichea/krilla, branch `pdf-logical-unit`, `PDF_LOGICAL_UNITS_V4.md`.

## Existing fpdf2 behavior

fpdf2 already has several pieces that v4 needs:

- HarfBuzz shaping reports source glyph IDs, cluster Unicode, advances, and
  offsets.
- Type0 fonts use two-byte `Identity-H` content codes.
- `/ToUnicode` maps each used code to the Unicode cluster.
- TrueType descendants already emit an explicit `/CIDToGIDMap`.
- fontTools subsets source fonts before embedding them.

The important limitation is that `SubsetMap` currently uses one `Glyph`
object for two independent identities:

1. semantic identity, through the Unicode tuple attached to the glyph;
2. visual identity, through the source glyph ID/name.

Because `Glyph.__hash__` hashes only `glyph_id`, shaped units that use the
same source glyph but carry different authoritative Unicode cannot reliably be
treated as distinct semantic CIDs. Conversely, the current object model has no
first-class representation for a visual unit that combines multiple positioned
source glyphs into one PDF character.

## v4 mapping

The port should keep fpdf2's public text APIs and split the internal mapping
into these namespaces:

```text
PDF two-byte code = semantic CID
semantic CID      -> Unicode tuple via /ToUnicode
semantic CID      -> compact embedded GID via /CIDToGIDMap
compact GID       -> source-backed or synthetic visual glyph
```

### Internal keys

`VisualUnitKey` should contain only visual construction data. For an exact
source-backed unit this is the source glyph ID plus nominal advance. For a
synthetic unit it is the ordered component list, component offsets, and logical
advance.

`SemanticUnitKey` should contain the authoritative Unicode tuple plus the
`VisualUnitKey`.

Unicode must not participate in visual deduplication. This allows multiple
semantic CIDs to share one embedded GID while retaining distinct
`/ToUnicode` mappings.

### Exact source-backed reuse

A shaped unit can directly reuse a compact source glyph only when:

- it has exactly one source component;
- x/y offsets are zero;
- y advance is zero; and
- shaped x advance equals that glyph's nominal advance.

Otherwise the unit needs a synthetic TrueType composite glyph whose metrics
and component placement reproduce the shaped visual exactly.

### Compact embedded font

For each logical-font shard, collect:

- `.notdef`;
- source glyphs needed by exact source-backed visual units;
- transitive dependencies of source composite glyphs;
- source glyphs referenced by synthetic composite units;
- one synthetic glyph per unique synthetic `VisualUnitKey`.

Subset/remap source glyphs densely first. Append synthetic glyphs after the
compact source subset. Build `/CIDToGIDMap` from semantic CID to that compact
GID.

### Capacity

Track semantic-CID capacity separately from compact-GID capacity. The original
source font's glyph count must not consume embedded-GID capacity. Shard when
either namespace would exceed the two-byte limit.

## Suggested implementation slices

1. Refactor `SubsetMap` into separate semantic and visual maps without changing
   PDF output for current one-glyph units. Add unit tests proving that distinct
   Unicode tuples can share one visual GID.
2. Move font subsetting/remapping behind a compact-GID builder and assert the
   generated `/CIDToGIDMap` against the compact font's final glyph order.
3. Add synthetic TrueType composite construction for positioned or
   multi-component logical units.
4. Add per-shard capacity accounting and resource switching while preserving
   existing `Tf` and `TJ` behavior.
5. Run render and extraction regression tests for English, Khmer, Arabic,
   Devanagari, ligatures, marks, and mixed-direction text.

## Validation requirements

A v4 implementation should not be promoted on semantic tests alone. At minimum:

- visual comparison in two independent renderers;
- extraction comparison in Poppler and PDFium;
- Khmer selection/copy/search checks;
- qpdf syntax validation;
- existing fpdf2 text-shaping tests;
- targeted tests for semantic-CID reuse, shared visual GIDs, synthetic fallback,
  transitive composite dependencies, and both capacity limits.

This document is an implementation map, not a claim that the port is complete.
