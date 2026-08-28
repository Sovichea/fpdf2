# Experimental Enhanced Unicode PDF logical units

This branch contains an experimental implementation of the Typsastra Enhanced Unicode PDF architecture for fpdf2.

The goal is to preserve authored Unicode independently from shaped glyph identity. The PDF backend receives source-ordered logical units containing both exact Unicode and the already-shaped visual construction, then creates one semantic PDF character identity for each logical unit.

The experiment is opt-in so existing fpdf2 behavior and reference PDFs remain unchanged by default.

~~~python
pdf.set_text_shaping(True, enhanced_unicode=True)
~~~

The current implementation targets horizontal TrueType fonts with a glyf table. Unsupported cases fall back to the existing per-glyph shaping path.

## Motivation

Traditional PDF text pipelines commonly reduce shaped text to glyph IDs and coordinates before the PDF text encoder decides how to populate /ToUnicode. That representation is sufficient for painting but is not sufficient for exact source semantics in all scripts.

A shaped cluster can have relationships such as:

~~~text
many Unicode scalars -> one glyph
one source cluster   -> several glyphs
logical order        != visual glyph order
~~~

Once source association has been reduced to independent glyph IDs, the PDF writer may have to guess which visual glyph should own which Unicode substring.

The enhanced pipeline keeps source and visual identity together:

~~~text
source Unicode
    -> HarfBuzz shaping
    -> source-ordered logical units
    -> semantic CID + visual identity
    -> compact source-backed or synthetic glyph
    -> explicit /CIDToGIDMap
    -> exact /ToUnicode
    -> source-order Tj/TJ serialization
~~~

## Logical-unit contract

Conceptually each unit is:

~~~text
LogicalUnit {
    text: exact authored Unicode
    glyphs: positioned shaped glyphs
    visual_x: visual origin
    visual_y: visual origin
}
~~~

The invariants are:

1. The logical text is authoritative for extraction and search semantics.
2. The positioned glyph construction is authoritative for appearance.
3. Logical units are serialized in source order.
4. The PDF layer does not reshape the text.
5. /ActualText is not required for normal logical-unit encoding.
6. Unsupported units use the existing fpdf2 glyph-oriented path instead of failing PDF generation.

## Why fpdf2 is a good fit

fpdf2 already contains most of the required machinery:

- HarfBuzz shaping and cluster tracking in TTFFont.perform_harfbuzz_shaping().
- Unicode tuples on Glyph for ligatures and substitutions.
- SubsetMap allocation of 16-bit PDF character codes.
- Identity-H Type0 fonts.
- /ToUnicode generation from Glyph.unicode tuples.
- CIDToGIDMap generation.
- fontTools subsetting.
- TTGlyphPen support for building TrueType glyphs.
- positioned PDF text output.

The experiment therefore changes the identity boundary rather than replacing the shaping or PDF stack.

### Existing path

~~~text
source text
    -> HarfBuzz
    -> shaped Glyph records
    -> per-glyph SubsetMap identity
    -> PDF
~~~

### Enhanced path

~~~text
source text
    -> HarfBuzz
    -> logical-unit planning
    -> SemanticUnitKey + VisualUnitKey
    -> compact logical font shard
    -> explicit CIDToGIDMap + /ToUnicode
    -> logical-order PDF text
~~~

## Semantic and visual identity

Version 4 separates semantic and visual identity.

~~~text
VisualUnitKey = (
    advance width,
    positioned component list
)

SemanticUnitKey = (
    exact Unicode tuple,
    VisualUnitKey
)
~~~

The positioned component list contains source glyph IDs and their offsets. Unicode never participates in visual deduplication, so different semantic CIDs can safely share one compact embedded GID.

This gives the following rules:

~~~text
same Unicode + same visual construction -> reusable logical identity
same Unicode + different visual construction -> different logical identity
different Unicode + same visual construction -> different logical identity
~~~

A visual construction does not determine its Unicode semantics.

## Compact source-backed and synthetic glyphs

Version 4 embeds only the source glyphs actually referenced by the document, their transitive TrueType composite dependencies, and one synthetic glyph per unique visual construction that cannot reuse a source glyph exactly.

An exact source glyph is reused when a visual unit has one component, zero x/y offsets, and a logical advance equal to the source glyph's nominal advance.

~~~text
one exact source component
    -> compact source GID

positioned / changed-advance / multi-component visual
    -> compact synthetic GID
~~~

Semantic CIDs and compact embedded GIDs are independent namespaces:

~~~text
PDF code = semantic CID
semantic CID -> authoritative Unicode through /ToUnicode
semantic CID -> compact GID through /CIDToGIDMap
compact GID -> visual outline
~~~

A high source GID is densely remapped by fontTools and therefore does not consume the same numbered embedded GID. Capacity is tracked independently for the 65,535 semantic CIDs and the 65,535 compact embedded glyphs. Repeated semantic units reuse their CID and repeated visual constructions reuse their compact GID.

### Synthetic left side bearing

Synthetic composites recalculate their bounds and store:

~~~text
leftSideBearing = synthetic.xMin
~~~

This preserves TrueType phantom-point geometry for positioned marks and composites.

## v0.3.1 oversized-unit guard

TrueType composite component offsets are signed 16-bit values. A very wide logical unit can exceed the representable component-coordinate range.

The implementation carries the Typsastra v0.3.1 guard:

~~~text
max_logical_width = i16::MAX - 2 * units_per_em
~~~

A logical unit is rejected when its visual width exceeds this value or when any component x/y offset falls outside signed 16-bit coordinates.

The caller then uses the existing shaped-glyph output path.

This protects repeated-fill and similar runs from producing invalid composite glyphs.

## Logical-order PDF serialization

Logical CIDs are written in source order, not visual glyph order.

A unit begins at its shaped visual origin. Consecutive units in the same logical font are grouped and positioned with TJ adjustments when necessary.

For two units:

~~~text
expected_x = current.visual_x + current.advance_width
visual_displacement = next.visual_x - expected_x
TJ_adjustment = -visual_displacement * font.scale
~~~

A positive TJ adjustment can move the following source-ordered CID backward visually. This allows an RTL run to retain source-order PDF codes while preserving shaped appearance.

When no adjustment is needed, the implementation uses ordinary Tj output.

## Font sharding

A TrueType font has a 16-bit glyph-ID space. Synthetic logical glyphs cannot grow indefinitely inside one embedded font.

Each TTFFont therefore owns zero or more logical font shards. A shard starts from a pristine copy of the source font rather than from the previous logical shard.

~~~text
source TTFont
    |-- base logical font
    |-- logical shard 1
    |-- logical shard 2
    ...
~~~

Every shard has its own:

- SubsetMap
- synthetic glyph table
- CID namespace
- CIDToGIDMap
- /ToUnicode

### Pristine-source requirement

The source-font snapshot is captured before the first synthetic glyph is added.

This is necessary because copying a nearly full logical font into a new shard would reproduce the exhausted glyph table and provide no useful new GID capacity.

## Geometry-aware sharding policy

Global semantic-key reuse is the default policy because it minimizes duplicate synthetic glyphs.

A problem appears when a source-ordered reordered or RTL run crosses font boundaries. Some PDF extractors can treat separate font and text-show operations as independent geometric runs and reconstruct them in visual order.

The experiment therefore uses a hybrid policy.

First, it forecasts the font sequence that normal global allocation would produce. If the run remains in one font, normal allocation is used.

If the run spans fonts, the implementation checks whether logical order moves backward in visual x:

~~~text
next.visual_x < current.visual_x
~~~

If not, global allocation is retained.

If yes, the allocator attempts to keep the complete shaping run in one shard.

Candidate selection prefers:

1. the shard requiring the fewest new logical identities;
2. the current shard when duplication cost is equal;
3. the newer shard when the first two criteria are equal.

If no existing shard can contain the complete run but a fresh shard can, a new shard is created before the run is emitted.

If the run itself is larger than a complete fresh shard, the implementation falls back to global sharding.

### Local duplication is allowed

Run affinity can create the same semantic + visual identity in more than one PDF font.

~~~text
("A", visual X)
    -> shard 0, CID 42
    -> shard 3, CID 17
~~~

Both mappings still have exact /ToUnicode entries and identical visual construction. CIDs are font-local, so this relaxes a deduplication optimization rather than the semantic invariant.

The first allocated record remains the canonical target for ordinary global reuse.

## Page resources

Logical shards are selected during text rendering, after the parent font has already been registered with the document resource catalog.

During PDF output, all generated logical shards are serialized as normal Type0/CIDFontType2 font resources. A page that uses a parent TrueType font also receives that parent's generated logical shard resources.

This is intentionally conservative. A future refinement can track exact per-page shard usage and include only the shards actually referenced by that page.

## Fallback conditions

The enhanced path currently falls back to existing fpdf2 rendering when any of the following applies:

- enhanced Unicode mode is not enabled;
- the font does not contain a TrueType glyf table;
- color-font rendering is active;
- character or word spacing requires the legacy path;
- total-pages substitution is being rendered;
- HarfBuzz cluster planning cannot produce complete source-owned units;
- a logical unit exceeds the v0.3.1 width or signed 16-bit coordinate limits;
- a synthetic glyph cannot be constructed or allocated;
- a TJ displacement cannot be represented within the chosen quantization tolerance.

The fallback is per shaped fragment, so unsupported content does not abort document generation.

## Current limitations

This branch is an experiment, not a claim of complete Unicode PDF or PDF/UA conformance.

Known limitations include:

- CFF/CFF2 logical synthetic glyphs are not implemented.
- The current implementation is for horizontal text.
- Character spacing and word spacing stay on the legacy path.
- Total-pages substitution stays on the legacy path.
- Page resources currently include all shards for a used parent font rather than exact shard usage.
- Some extractors interpret RTL positioning differently. Poppler handled the tested source-order TJ model correctly; pypdf can report visual/reversed order for some RTL runs.
- Heavily vocalized Hebrew and Arabic can expose extraction behavior around zero-advance mark units even without sharding. This suggests a separate experiment on whether some mark clusters should be coalesced with their owning base into one PDF logical unit.
- Accurate text semantics do not by themselves establish full PDF/UA conformance. Structure, metadata, language, tagging, reading order, and other requirements remain separate concerns.

## Reference implementation

This experiment adapts the architecture from the Typsastra Enhanced Unicode engine.

- Typsastra release: enhanced-unicode-v0.3.1
- Typst tested revision: 75202cf09a26a5ef5dfd0f26ab7a4fe007e1be39
- Krilla tested revision: d05158cf3ebead248745f846d0397e84dfb9f2d0
- fpdf2 discussion: #1933

The conceptual source of truth remains:

~~~text
authored Unicode -> shaped visual geometry -> source-ordered logical units -> PDF
~~~

The key architectural rule is that authored Unicode identity must survive every boundary instead of being reconstructed from glyph identity at the end of the pipeline.
