# Enhanced Unicode PDF size benchmark

This benchmark tests whether the PDF-size behavior observed in Typsastra's
Enhanced Unicode v0.3 architecture also appears when the same logical-unit
model is adapted to fpdf2.

The result is mixed and useful:

> The logical-unit representation can substantially reduce fpdf2 output for
> some complex scripts as text volume grows, but the reduction is not universal.
> fpdf2's existing shaped-glyph path is already compact for several scripts,
> especially Arabic, so the same source-order logical representation can be
> larger there.

This is an implementation and baseline effect, not a contradiction of the
logical-unit architecture. The architecture guarantees semantic continuity.
File-size improvement depends on how expensive the producer's existing visual
glyph representation is and how much state the logical serializer can retain.

## Relation to the Typsastra v0.3 benchmark

Typsastra v0.3 reported the following changes relative to stock Typst on a much
larger unique-paragraph corpus:

| Workload | Typsastra v0.3 change vs stock |
| --- | ---: |
| English | +9.4% |
| Khmer | -86.1% |
| Arabic | -12.8% |
| Devanagari/Hindi | -71.3% |
| Mixed multilingual | -30.7% |

The important implementation change in Typsastra v0.3 was retained text state
plus positioned TJ batching. That eliminated the large v0.2 Latin and Arabic
regressions while retaining source-order logical character codes.

The fpdf2 benchmark below uses a different and much smaller workload, so the
percentages must not be compared directly. It uses the exact text from
Typsastra's unicode-selection fixture as the common corpus.

Reference fixture:

~~~text
tests/fixtures/enhanced-unicode/unicode-selection.typ
~~~

Reference Typsastra benchmark:

~~~text
docs/ENHANCED_UNICODE_ENGINE_BENCHMARKS_V0.3.0.md
~~~

## Method

Two fpdf2 PDFs are generated from identical text and layout:

~~~python
# Existing fpdf2 representation
pdf.set_text_shaping(True, enhanced_unicode=False)

# Experimental logical-unit representation
pdf.set_text_shaping(True, enhanced_unicode=True)
~~~

The benchmark uses A4 pages, 14 pt text, approximately 1.1 em line leading,
and the exact labeled lines from the Typsastra fixture.

The following static Noto fonts were used:

- Noto Sans
- Noto Sans Khmer
- Noto Sans Arabic
- Noto Sans Devanagari
- Noto Sans Thai
- Noto Sans Lao

The full-fixture test uses Noto Sans as the primary font and the other fonts as
fpdf2 fallback fonts.

Measurements include:

- total PDF bytes;
- compressed page-content bytes;
- compressed embedded-font bytes;
- /ToUnicode bytes;
- BT, Tf, Tm, TJ, and Tj operator counts.

A second scaling test removes the EU-* label and repeats each script payload.
This separates fixed font/subset overhead from the cost that grows with text
volume.

## Environment note

The measured development runner used the same logical-unit implementation as
the enhanced-unicode-v3 branch, with system HarfBuzz called directly because
the container did not provide the Python uharfbuzz package.

The available local base package was fpdf2 2.8.5 while the Git branch is based
on fpdf2 2.8.8. The relevant legacy shaping and text-output paths were checked
against the current 2.8.8 source and are structurally the same. These results
should therefore be treated as development measurements. A release-grade
benchmark should be rerun from a clean checkout of the pinned branch commit.

## Exact Typsastra fixture

With the complete fixture rendered once:

| Variant | PDF bytes | Change |
| --- | ---: | ---: |
| Existing fpdf2 shaping | 55,325 | baseline |
| Enhanced logical units | 57,997 | +2,672 |
| Relative change | | **+4.83%** |

The uncompressed PDFs showed a similar result:

| Variant | PDF bytes |
| --- | ---: |
| Existing | 60,077 |
| Enhanced | 62,748 |
| Change | **+4.45%** |

So the current fpdf2 port does **not** reproduce Typsastra's mixed-document
size reduction on this small fixture.

## Where the additional bytes come from

For the compressed full fixture:

| Component | Existing | Enhanced | Delta |
| --- | ---: | ---: | ---: |
| Page content streams | 1,617 | 1,700 | +83 |
| /ToUnicode streams | 5,178 | 5,753 | +575 |
| Embedded font streams | 39,699 | 41,558 | +1,859 |
| Total PDF | 55,325 | 57,997 | +2,672 |

Most of the increase is not page-content syntax. It comes from the synthetic
logical glyphs added to the embedded TrueType subsets, followed by the larger
/ToUnicode maps.

The page content itself is almost neutral on the full fixture.

### Operator counts

| Operator | Existing | Enhanced |
| --- | ---: | ---: |
| BT | 16 | 16 |
| Tf | 69 | 69 |
| Tm | 98 | 104 |
| TJ | 0 | 8 |
| Tj | 178 | 98 |

The logical path removes 80 individual Tj operations, but it adds positioned
TJ arrays and a few extra Tm resets. After compression, this leaves the
content stream 83 bytes larger.

## Individual fixture lines

Every labeled fixture line was also rendered as a separate one-line PDF.

| Fixture | Existing bytes | Enhanced bytes | Change |
| --- | ---: | ---: | ---: |
| Latin | 29,721 | 29,955 | +0.79% |
| Combining Latin | 30,419 | 30,720 | +0.99% |
| Khmer 01 | 30,999 | 31,225 | +0.73% |
| Khmer 02 | 32,134 | 32,472 | +1.05% |
| Arabic | 31,475 | 31,937 | +1.47% |
| Devanagari | 31,519 | 31,875 | +1.13% |
| Thai | 30,520 | 30,812 | +0.96% |
| Lao | 30,186 | 30,401 | +0.71% |
| Mixed | 33,246 | 33,620 | +1.12% |
| Punctuation | 30,502 | 30,851 | +1.14% |

For tiny documents the fixed cost of synthetic glyph definitions dominates,
so all one-line samples are slightly larger.

This is why one-line measurements are not sufficient to evaluate the
serializer's asymptotic behavior.

## Repeated labeled lines

Repeating the exact labeled line 20 times begins to amortize the fixed font
cost:

| Fixture | Change at 20 repetitions |
| --- | ---: |
| Latin | +0.07% |
| Combining Latin | +0.95% |
| Khmer 01 | **-1.21%** |
| Khmer 02 | **-1.45%** |
| Arabic | +4.76% |
| Devanagari | +3.68% |
| Thai | **-0.15%** |
| Lao | +0.42% |
| Mixed | +2.38% |
| Punctuation | +0.94% |

Khmer is already smaller at this point. Thai is approximately at break-even.

## Script payload scaling

The next test removes the Latin EU-* label and uses one appropriate Noto font
per script. This better exposes the representation cost of the script itself.

### 100 repetitions

| Script | Existing bytes | Enhanced bytes | Change |
| --- | ---: | ---: | ---: |
| Latin | 10,189 | 9,702 | **-4.78%** |
| Combining Latin | 9,619 | 12,064 | **+25.42%** |
| Khmer 01 | 14,844 | 10,510 | **-29.20%** |
| Khmer 02 | 18,023 | 11,740 | **-34.86%** |
| Arabic | 10,694 | 11,646 | **+8.90%** |
| Devanagari | 10,582 | 10,685 | +0.97% |
| Thai | 13,182 | 10,429 | **-20.88%** |
| Lao | 12,025 | 9,829 | **-18.26%** |

### 500 repetitions

The deliberately large stress case makes the scaling trend clearer:

| Script | Existing bytes | Enhanced bytes | Change |
| --- | ---: | ---: | ---: |
| Latin | 19,411 | 16,234 | **-16.37%** |
| Combining Latin | 15,141 | 26,402 | **+74.37%** |
| Khmer 01 | 39,232 | 16,857 | **-57.03%** |
| Khmer 02 | 50,740 | 18,260 | **-64.01%** |
| Arabic | 17,296 | 20,872 | **+20.68%** |
| Devanagari | 17,237 | 17,013 | **-1.30%** |
| Thai | 31,498 | 16,930 | **-46.25%** |
| Lao | 27,894 | 16,366 | **-41.33%** |

The large repetition count is not intended as a realistic document. It shows
which costs are fixed and which grow with text volume.

## Khmer: clear size win after amortization

Khmer most closely reproduces the Typsastra behavior.

For the first labeled Khmer fixture line, the raw page-content stream changes
from:

~~~text
708 bytes -> 405 bytes
~~~

Operator counts change from:

| Operator | Existing | Enhanced |
| --- | ---: | ---: |
| Tf | 6 | 6 |
| Tm | 14 | 6 |
| Tj | 20 | 6 |
| TJ | 0 | 0 |

That is a substantial reduction in visual-positioning syntax.

The one-line PDF is still 0.73% larger because the enhanced font stream adds
323 bytes and /ToUnicode adds 14 bytes. Repetition amortizes that fixed cost,
after which the smaller content stream dominates.

This produces the 29% to 64% payload reductions seen in the larger Khmer
stress cases.

## Thai and Lao: same pattern at a smaller scale

Thai and Lao behave similarly to Khmer.

Their existing shaped-glyph output contains enough positioning operations that
one semantic CID per logical unit reduces the growing page-content cost.

The initial synthetic-font overhead makes one-line PDFs slightly larger, but
the logical path becomes smaller as the amount of text increases.

## Devanagari: content improves, font overhead delays the crossover

The pure Devanagari payload has a smaller enhanced content stream, but the
difference is modest compared with Khmer.

At 20 repetitions the raw content was:

~~~text
existing: 2770 bytes
enhanced: 2490 bytes
~~~

The enhanced font stream is about 198 bytes larger and /ToUnicode adds another
small fixed cost. The total PDF therefore remains slightly larger for moderate
text volumes and crosses below the existing path only in the larger stress
case.

This is qualitatively similar to Typsastra, but the magnitude is much smaller
because fpdf2's conventional Devanagari representation is already compact.

## Arabic: fpdf2 does not reproduce the Typsastra size win

Arabic is the most important difference.

For the one-line labeled Arabic sample:

| Metric | Existing | Enhanced |
| --- | ---: | ---: |
| Raw page content | 476 bytes | 1,164 bytes |
| Tf | 15 | 15 |
| Tm | 1 | 15 |
| TJ | 0 | 7 |
| Tj | 16 | 8 |

fpdf2's existing path emits the shaped Arabic glyphs in visual order and is
already extremely compact. It needs almost no explicit positioning.

The logical path deliberately emits semantic CIDs in source order. Reproducing
the RTL visual placement therefore requires numeric TJ adjustments and more
text-matrix positioning.

Unlike stock Krilla in the Typsastra benchmark, the fpdf2 baseline does not
carry thousands of /ActualText spans or a similarly expensive semantic repair
layer. There is therefore no large legacy overhead for the logical path to
remove.

The resulting size regression grows with text volume:

~~~text
1 payload:     +3.63%
100 payloads:  +8.90%
500 payloads: +20.68%
~~~

This is a real producer-specific tradeoff, not just fixed synthetic-font
overhead.

## Combining Latin exposes a fragment-boundary problem

The decomposed combining fixture is the largest negative scaling case.

fpdf2 splits this content into several shaping fragments. The current logical
serializer is invoked independently for each Fragment and establishes a new
text matrix for each logical fragment.

The existing path can emit compact sequences such as:

~~~text
(...) Tj (...) Tj (...) Tj
~~~

while the current enhanced integration produces repeated sequences resembling:

~~~text
Tm (...) Tj
Tm (...) Tj
Tm (...) Tj
~~~

The resulting content cost grows linearly with repeated text.

This is not evidence that a logical unit inherently requires larger combining
text. It exposes an integration boundary in the current fpdf2 port.

## Important integration discovery: the fpdf2 port is still fragment-scoped

Typsastra v0.3 retains the active logical font and batches compatible units
across the complete PDF logical run.

The current fpdf2 implementation retains that state only inside
Fragment.render_with_text_shaping().

fpdf2 can split a source line before this point because of:

- Unicode script segmentation;
- fallback-font selection;
- bidi reordering;
- line-layout fragments.

Each fragment then enters the logical PDF writer independently.

Conceptually, the current port is:

~~~text
source text
    -> fpdf2 paragraph/bidi/fallback fragmentation
    -> Fragment
        -> logical units
        -> source-order Tj/TJ
    -> next Fragment
        -> new logical serialization state
~~~

Typsastra's stronger model is:

~~~text
source text
    -> layout + shaping with source ownership preserved
    -> logical run spanning the relevant shaped fragments
    -> one retained PDF text state
    -> batched source-order Tj/TJ
~~~

This distinction explains part of the size difference.

It also reinforces the architectural requirement that logical units need an
end-to-end boundary. Adding them only at the final per-fragment writer recovers
many semantics but cannot recover information or state already split earlier.

## Extraction check during the size benchmark

Poppler pdftotext -raw was also checked against each exact labeled line.

The enhanced path extracted the following fixture cases exactly:

- Latin
- decomposed combining Latin
- Khmer 01
- Khmer 02
- Devanagari
- Thai
- Lao
- punctuation

The legacy path failed exact raw extraction for both Khmer lines and
Devanagari in this run.

Arabic and the mixed bidi line were not byte-identical to authored source for
either path. The current fpdf2 bidi layer has already divided/reordered the
paragraph into fragments before the logical-unit writer receives it.

This is important: the Arabic size result is currently a comparison of two
visually correct PDF representations, but the enhanced branch has not yet
achieved the full authored-source ordering invariant across fpdf2 bidi
fragment boundaries.

## What this benchmark establishes

The fpdf2 experiment supports four conclusions.

### 1. Logical units can reduce fpdf2 PDF size significantly

The effect is clear for sustained Khmer, Thai, and Lao text. Khmer reaches
roughly 30% to 35% reduction at 100 payload repetitions in this synthetic
benchmark and more than 50% in the 500-repeat stress case.

### 2. The benefit is not a universal property of complex scripts

Arabic is larger in fpdf2 because the existing visual-order glyph serializer is
already compact.

The logical-unit architecture should therefore not be sold as a general PDF
compression technique.

### 3. Fixed synthetic-font overhead matters for short documents

Every one-line fixture PDF is slightly larger. The size win appears only after
smaller page-content streams amortize the synthetic glyph and /ToUnicode cost.

### 4. Pipeline integration determines both semantics and size

The current Fragment-level integration leaves optimization opportunities on the
table and still loses authored ordering across some bidi boundaries.

The next fpdf2 architecture step should therefore be broader than another
micro-optimization inside _render_pdf_logical_units().

## Current recommendation and optional optimization path

The current fragment-local implementation is the recommended compromise for
fpdf2.

It preserves the core Enhanced Unicode representation at a small integration
surface, keeps the existing layout/bidi/fallback pipeline intact, falls back
safely to the existing renderer for unsupported cases, and already produces
substantial size reductions where fpdf2's conventional complex-script
representation is expensive.

The benchmark therefore does **not** imply that fpdf2 should redesign its text
pipeline now.

A broader fragment-spanning logical-run design should be treated as an
alternative implementation only when real product requirements justify the
additional architectural complexity.

Such requirements could include:

- PDF size becoming a material concern for workloads dominated by fragmented
  shaped text;
- cross-fragment semantic continuity becoming necessary for bidi or fallback
  cases that cannot be represented correctly at the current Fragment boundary;
- text-state efficiency becoming important enough that repeated Tf/Tm
  transitions across fragments are measurable in real documents.

If those requirements arise, fpdf2 could preserve source provenance through
its existing bidi, fallback, and layout stages and construct a higher-level
logical run spanning several rendering fragments.

Conceptually:

~~~text
LogicalRun {
    source-order units
    font ownership
    visual positions
}
~~~

The PDF serializer could then retain:

~~~text
active logical font
current text matrix
current logical/visual pen state
~~~

across compatible fragments.

That alternative could enable:

- fewer redundant Tf and Tm operations at fragment boundaries;
- larger TJ batches;
- better compactness for combining and fallback-heavy text;
- improved cross-fragment source-order preservation.

This would be a broader pipeline change, not a requirement of the current
Enhanced Unicode implementation.

The practical decision rule is therefore:

~~~text
use the current fragment-local logical-unit implementation
        ↓
measure real-world semantic and size behavior
        ↓
only if size or cross-fragment semantics become material requirements
        ↓
consider source-provenance + fragment-spanning LogicalRun
~~~

A small local experiment that removed only redundant initial Tm resets reduced
the full-fixture regression from about +4.8% to about +4.1%, which confirms that
some additional batching opportunity exists. That result alone is not enough
to justify redesigning the fpdf2 text pipeline.

## Reproducing the benchmark

The repository contains:

~~~text
scripts/benchmark-enhanced-unicode-size.py
~~~

Example:

~~~bash
python scripts/benchmark-enhanced-unicode-size.py \
    --font-dir /usr/share/fonts/truetype/noto \
    --payload-repetitions 1 20 100
~~~

The script writes the legacy and enhanced PDFs plus results.json under:

~~~text
build/enhanced-unicode-size/
~~~

The benchmark intentionally depends on the test-only pypdf package for stream
inspection.

## Conclusion

Typsastra demonstrated that the v3 logical-unit model can produce very large
size reductions when it replaces an expensive conventional complex-script PDF
representation.

fpdf2 confirms part of that result, especially for Khmer, Thai, and Lao, while
also showing that the size benefit depends on the producer's existing text
representation.

The more general conclusion is:

> PDF logical units change the scaling characteristics of text representation.
> They can be substantially smaller when they collapse expensive per-glyph
> positioning and semantic repair, but they can be larger when the producer's
> existing visual-glyph path is already compact or when fragmentation limits
> batching opportunities.

For fpdf2, the current fragment-local implementation remains a good engineering
compromise. It delivers the main Unicode-semantic benefit with a small,
isolated change surface and already provides meaningful size reductions for
several complex scripts.

A fragment-spanning LogicalRun architecture should therefore be viewed as an
optional future optimization, not as a prerequisite for Enhanced Unicode in
fpdf2. It should be pursued only if real-world PDF size, cross-fragment
semantics, or text-state efficiency creates sufficient demand to justify a
broader pipeline change.
