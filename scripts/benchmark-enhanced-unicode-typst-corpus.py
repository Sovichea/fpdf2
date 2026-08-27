#!/usr/bin/env python3
"""Benchmark fpdf2 Enhanced Unicode on the canonical Typsastra corpus.

The corpus is the unchanged set of generated Typst sources mirrored in:
Sovichea/OpenPDF@pdf-logical-unit
pdf-toolbox/src/test/resources/benchmark/typst
"""

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from fpdf import FPDF


CORPORA = ("english", "khmer", "arabic", "hindi", "mixed")

FONT_FILES = {
    "Latin": "NotoSans-VF.ttf",
    "Khmer": "NotoSansKhmer-VF.ttf",
    "Arabic": "NotoNaskhArabic-VF.ttf",
    "Devanagari": "NotoSansDevanagari-VF.ttf",
}

CORPUS_FONT = {
    "english": "Latin",
    "khmer": "Khmer",
    "arabic": "Arabic",
    "hindi": "Devanagari",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--font-dir", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/enhanced-unicode-typst-corpus"),
    )
    return parser.parse_args()


def load_typst_paragraphs(path: Path) -> tuple[str, list[str]]:
    """Extract the generated benchmark heading and prose paragraphs."""
    lines = path.read_text(encoding="utf-8").splitlines()
    heading = ""
    body_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("=") and not heading:
            heading = stripped.lstrip("=").strip()
            continue
        body_lines.append(line)

    paragraphs: list[str] = []
    current: list[str] = []
    for line in body_lines:
        if line.strip():
            current.append(line.strip())
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return heading, paragraphs


def font_paths(font_dir: Path) -> dict[str, Path]:
    paths = {name: font_dir / filename for name, filename in FONT_FILES.items()}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise SystemExit("Missing benchmark fonts:\n  " + "\n  ".join(missing))
    return paths


def configure_fonts(
    pdf: FPDF,
    corpus: str,
    fonts: dict[str, Path],
    enhanced: bool,
) -> None:
    if corpus == "mixed":
        for family, path in fonts.items():
            pdf.add_font(family, fname=path)
        pdf.set_font("Latin", size=10.5)
        pdf.set_fallback_fonts(
            ["Khmer", "Arabic", "Devanagari"],
            exact_match=False,
        )
    else:
        family = CORPUS_FONT[corpus]
        pdf.add_font(family, fname=fonts[family])
        pdf.set_font(family, size=10.5)

    pdf.set_text_shaping(True, enhanced_unicode=enhanced)


def render(
    corpus: str,
    heading: str,
    paragraphs: list[str],
    fonts: dict[str, Path],
    enhanced: bool,
    output: Path,
) -> float:
    pdf = FPDF(format="A4")
    pdf.set_margins(22, 22, 22)
    pdf.set_auto_page_break(True, margin=22)
    pdf.add_page()
    configure_fonts(pdf, corpus, fonts, enhanced)

    # Typst fixture: 10.5 pt text with par leading 0.65 em.
    line_height = pdf.font_size * 1.65

    if heading:
        pdf.set_font_size(15)
        pdf.multi_cell(
            w=0,
            h=pdf.font_size * 1.35,
            text=heading,
            align="L",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(pdf.font_size * 0.5)
        pdf.set_font_size(10.5)

    started = time.perf_counter()
    for paragraph in paragraphs:
        pdf.multi_cell(
            w=0,
            h=line_height,
            text=paragraph,
            align="J",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(line_height * 0.35)
    pdf.output(output)
    return time.perf_counter() - started


def stream_length(obj: Any, decompressed: bool) -> int:
    stream = obj.get_object()
    if decompressed:
        return len(stream.get_data())
    raw = getattr(stream, "_data", None)
    return len(raw) if raw is not None else len(stream.get_data())


def inspect_pdf(path: Path) -> dict[str, Any]:
    reader = PdfReader(path)
    result: dict[str, Any] = {
        "bytes": path.stat().st_size,
        "pages": len(reader.pages),
        "content_compressed": 0,
        "content_raw": 0,
        "tounicode_compressed": 0,
        "font_compressed": 0,
        "operators": {"BT": 0, "Tf": 0, "Tm": 0, "TJ": 0, "Tj": 0},
    }
    seen_fonts: set[int] = set()
    seen_tounicode: set[int] = set()
    seen_font_files: set[int] = set()

    for page in reader.pages:
        contents = page.get("/Contents")
        content_refs = contents if isinstance(contents, list) else [contents]
        raw_content = bytearray()
        for content_ref in content_refs:
            if content_ref is None:
                continue
            result["content_compressed"] += stream_length(content_ref, False)
            data = content_ref.get_object().get_data()
            result["content_raw"] += len(data)
            raw_content.extend(data)

        for operator in result["operators"]:
            pattern = rb"(?<![A-Za-z])" + operator.encode() + rb"(?![A-Za-z])"
            result["operators"][operator] += len(re.findall(pattern, raw_content))

        resources = page.get("/Resources", {})
        for font_ref in resources.get("/Font", {}).values():
            font_id = getattr(font_ref, "idnum", id(font_ref))
            if font_id in seen_fonts:
                continue
            seen_fonts.add(font_id)
            font = font_ref.get_object()

            to_unicode = font.get("/ToUnicode")
            if to_unicode is not None:
                stream_id = getattr(to_unicode, "idnum", id(to_unicode))
                if stream_id not in seen_tounicode:
                    seen_tounicode.add(stream_id)
                    result["tounicode_compressed"] += stream_length(
                        to_unicode, False
                    )

            for descendant_ref in font.get("/DescendantFonts") or []:
                descriptor_ref = descendant_ref.get_object().get("/FontDescriptor")
                if descriptor_ref is None:
                    continue
                descriptor = descriptor_ref.get_object()
                font_file = (
                    descriptor.get("/FontFile2")
                    or descriptor.get("/FontFile3")
                    or descriptor.get("/FontFile")
                )
                if font_file is None:
                    continue
                stream_id = getattr(font_file, "idnum", id(font_file))
                if stream_id in seen_font_files:
                    continue
                seen_font_files.add(stream_id)
                result["font_compressed"] += stream_length(font_file, False)

    return result


def main() -> None:
    args = parse_args()
    fonts = font_paths(args.font_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}

    print(
        "corpus,variant,pages,bytes,content,font,tounicode,"
        "BT,Tf,Tm,TJ,Tj,seconds"
    )
    for corpus in CORPORA:
        source = args.corpus_dir / f"{corpus}.typ"
        heading, paragraphs = load_typst_paragraphs(source)
        results[corpus] = {"paragraphs": len(paragraphs)}

        for enhanced in (False, True):
            variant = "enhanced" if enhanced else "legacy"
            output = args.output_dir / f"{corpus}-{variant}.pdf"
            seconds = render(
                corpus,
                heading,
                paragraphs,
                fonts,
                enhanced,
                output,
            )
            metrics = inspect_pdf(output)
            metrics["seconds"] = seconds
            results[corpus][variant] = metrics
            operators = metrics["operators"]
            print(
                f"{corpus},{variant},{metrics['pages']},{metrics['bytes']},"
                f"{metrics['content_compressed']},{metrics['font_compressed']},"
                f"{metrics['tounicode_compressed']},{operators['BT']},"
                f"{operators['Tf']},{operators['Tm']},{operators['TJ']},"
                f"{operators['Tj']},{seconds:.6f}"
            )

        legacy = results[corpus]["legacy"]["bytes"]
        enhanced = results[corpus]["enhanced"]["bytes"]
        results[corpus]["delta_bytes"] = enhanced - legacy
        results[corpus]["delta_percent"] = (enhanced - legacy) * 100 / legacy
        print(
            f"CHANGE {corpus}: {legacy} -> {enhanced} "
            f"({results[corpus]['delta_percent']:+.2f}%)"
        )

    result_path = args.output_dir / "results.json"
    result_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"RESULTS_JSON={result_path}")


if __name__ == "__main__":
    main()
