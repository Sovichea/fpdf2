# Enhanced Unicode experimental validation

This document records the focused validation performed while adapting the Typsastra v3 logical-unit architecture to fpdf2.

The checks are intentionally split into semantic, visual, and sharding categories. Passing one category does not imply that every PDF consumer will behave identically.

## Development environment

The prototype was exercised with:

- fpdf2 shaping/layout behavior equivalent to the branch implementation;
- system HarfBuzz for shaping;
- fontTools for TrueType manipulation and subsetting;
- Poppler pdftotext for extraction checks;
- Poppler rendering at 180 or 200 DPI for pixel comparisons;
- pypdf as an additional extraction consumer.

The branch itself is based on fpdf2 2.8.8.

## Khmer extraction

Test text:

~~~text
ក្ស សួស្តី ពិភពលោក
~~~

With the legacy glyph-oriented path, one development font produced:

~~~text
pypdf: ក្ស សួស្តី ពិភពលោ\x0bក
~~~

Poppler also fragmented parts of the string according to visual glyph placement.

With enhanced logical units, the logical CID and /ToUnicode entry carry the complete source sequence for each unit. The tested Khmer output extracted as:

~~~text
ក្ស សួស្តី ពិភពលោក
~~~

No /ActualText replacement layer was used.

## RTL extraction

Test Arabic text:

~~~text
مرحبا بالعالم
~~~

The logical-unit output serializes CIDs in source order and uses positive TJ adjustments when the next source unit must move backward visually.

Poppler extracted the expected Arabic text, with its normal directional control wrappers where applicable.

pypdf can interpret the same source-order positioning differently and return a visually reversed sequence for some RTL runs. This is recorded as a consumer difference rather than hidden by the test suite.

## Visual equivalence

The first synthetic-composite implementation showed visible mark displacement in Khmer.

The cause was a synthetic left side bearing of zero. After recalculating the composite bounds and setting:

~~~text
leftSideBearing = xMin
~~~

forced-sharding comparisons produced the following at 180 DPI:

| Script | Different pixels | Difference bounding box |
| --- | ---: | --- |
| Hebrew | 0 | none |
| Arabic | 0 | none |
| Khmer | 0 | none |

This compares the enhanced run using forced logical shards against the same enhanced run with normal capacity.

## v0.3.1 width guard

The v0.3.1 fix prevents a single logical unit from creating a TrueType composite whose component coordinates exceed signed 16-bit limits.

For a 1000 UPEM font:

~~~text
i16 maximum:         32767
two-em safety:        2000
maximum unit width:  30767
~~~

A synthetic test unit with a 31000-unit visual width was rejected before any new glyph was added.

Expected behavior:

~~~text
logical planning -> unsupported
synthetic glyph count -> unchanged
renderer -> legacy shaped-glyph fallback
~~~

## Forced font sharding

Real fonts usually have enough free TrueType GIDs that ordinary text will not reach a shard boundary. To test the allocator, development runs artificially limited each logical shard to a small number of synthetic glyphs.

### Capacity 2

A Khmer sentence was forced across six logical fonts.

Results:

- all shard Type0 fonts were embedded;
- every shard had a /ToUnicode map;
- page resources resolved every /F... Tf reference;
- Poppler extraction was exact;
- rendering was pixel-identical to the unsharded enhanced output.

Arabic under the same forced-sharding model also retained exact Poppler extraction and pixel-identical rendering.

## Pristine shard source

A critical sharding test verified that a new shard starts from the original font program rather than a mutated previous logical font.

Example development result:

~~~text
original source glyphs:       3317
base after logical additions: 3319
new shard starting glyphs:    3317
~~~

Without this rule, reaching the real 16-bit GID limit would copy a nearly full font into the next shard and leave little or no capacity.

## Sharding-policy experiments

Several policies were compared under artificially small capacities.

### Global reuse

~~~text
semantic key -> first allocated shard/CID
~~~

Advantages:

- minimum duplication;
- stable canonical record;
- good LTR behavior.

Weakness:

- a reordered or RTL logical run can cross several PDF fonts and text-show operations.

### Sticky shard

~~~text
once a newer shard is active, keep allocating there
~~~

This reduced some back-switching but duplicated repeated logical identities aggressively.

For a repeated Latin stress case:

~~~text
ABCD
EFGH
ABCD
~~~

with capacity 4, sticky allocation used 12 logical glyph records for 8 unique semantic + visual keys.

### Run rollover

Starting a fresh shard when the current shard cannot hold a complete run had similar duplication costs.

### Run affinity

Run affinity searches existing shards for one that can absorb the entire shaping run with the fewest missing identities. It can therefore reuse an older shard instead of duplicating a complete repeated run.

This improved coherence but could still duplicate ordinary LTR units unnecessarily.

### Geometry-aware run affinity

The selected policy retains global allocation unless both conditions are true:

1. normal global allocation would split the shaping run across PDF fonts;
2. source order moves backward in visual x somewhere in the run.

Only then is run affinity used.

Forced-capacity results:

| Case | Global font switches | Geometry-aware switches | Poppler extraction | Pixel difference |
| --- | ---: | ---: | --- | ---: |
| Hebrew, capacity 10 | 4 | 2 | exact | 0 |
| Arabic, capacity 10 | 6 | 2 | exact | 0 |
| Khmer, capacity 10 | 4 | 4 | exact | 0 |
| Devanagari, capacity 10 | 2 | 2 | exact | 0 |
| Thai, capacity 10 | 2 | 2 | exact | 0 |
| Latin partial reuse | 2 | 2 | exact | 0 |

The policy protects reordered runs from avoidable intra-run font boundaries while retaining global deduplication for ordinary forward-moving runs.

## Resource bug found during sharding

The first forced-sharding PDFs serialized the generated shard fonts but did not expose them in the page /Resources dictionary. Content streams referenced names such as:

~~~text
/F268500993 30 Tf
~~~

while the page only provided /F1.

The fix expands the page font-resource set for any used parent TrueType font to include its generated logical shards.

After the fix, readers resolved the shard fonts and exact extraction returned.

## Opt-in regression strategy

The implementation is enabled with:

~~~python
pdf.set_text_shaping(True, enhanced_unicode=True)
~~~

This is deliberate. Existing fpdf2 reference PDFs continue to exercise the unchanged default shaping path, while dedicated enhanced-Unicode tests validate the new representation independently.

The focused regression suite covers:

- exact Khmer extraction;
- forced sharding and page font resources;
- geometry-aware RTL run coherence;
- v0.3.1 oversized-unit fallback.

Additional development checks covered:

- synthetic-composite left side bearing;
- pristine source-font cloning for new shards;
- repeated-key reuse;
- multipage shard resources;
- Khmer, Arabic, Hebrew, Devanagari, Thai, and Latin stress cases.

## Local focused test result

The dedicated regression file was executed against the local port with the same logical-unit/sharding implementation and a system HarfBuzz bridge:

~~~text
4 passed
~~~

The forced-capacity extraction tests returned exact Khmer text and expected Poppler RTL text, and 180 DPI Hebrew, Arabic, and Khmer comparisons had zero differing pixels.

## Interpretation of results

These experiments support the architectural claim that preserving source Unicode and shaped visual geometry together can solve extraction problems that are difficult to repair after a pipeline has collapsed text into independent glyph identities.

They do not establish universal reader behavior or PDF/UA conformance. Cross-reader selection, copy, search, accessibility, tagged-PDF structure, and additional font technologies require separate validation.
