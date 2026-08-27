#!/usr/bin/env python3
"""Benchmark legacy shaped-glyph output against Enhanced Unicode logical units."""

import argparse
import json
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from fpdf import FPDF


FIXTURE_HEADER = [
    "Enhanced Unicode Engine validation",
    "Each labeled line is extracted verbatim and checked independently. The generous",
    "spacing also makes selection geometry failures easy to inspect in PDF viewers.",
]

CASES = [
    ("LATIN", "EU-LATIN-01: Café naïve coöperate — precomposed Latin text."),
    (
        "COMBINING",
        "EU-COMBINING-01: Café naïve Å — decomposed combining sequences.",
    ),
    (
        "KHMER-01",
        "EU-KHMER-01: ភាសាខ្មែរគាំទ្រការសរសេរ ការជ្រើសរើស និងការចម្លងអត្ថបទ។",
    ),
    (
        "KHMER-02",
        "EU-KHMER-02: កម្ពុជា សិល្បៈ អក្សរសាស្ត្រ ព័ត៌មានវិទ្យា និងចំណេះដឹង។",
    ),
    (
        "ARABIC",
        "EU-ARABIC-01: العربية تدعم ترتيب النص المنطقي والنسخ والبحث.",
    ),
    (
        "DEVANAGARI",
        "EU-DEVANAGARI-01: हिन्दी पाठ चयन, प्रतिलिपि और खोज का परीक्षण।",
    ),
    (
        "THAI",
        "EU-THAI-01: ภาษาไทยทดสอบการเลือก การคัดลอก และการค้นหาข้อความ",
    ),
    (
        "LAO",
        "EU-LAO-01: ພາສາລາວທົດສອບການເລືອກ ການສຳເນົາ ແລະ ການຄົ້ນຫາ",
    ),
    (
        "MIXED",
        "EU-MIXED-01: Typsastra — ភាសាខ្មែរ — العربية — हिन्दी — ภาษาไทย — ພາສາລາວ.",
    ),
    (
        "PUNCT",
        "EU-PUNCT-01: “Logical text” — (selection) [copy] {search} … ១០០٪.",
    ),
]

PAYLOADS = {
    "LATIN": "Café naïve coöperate — precomposed Latin text.",
    "COMBINING": "Café naïve Å — decomposed combining sequences.",
    "KHMER-01": "ភាសាខ្មែរគាំទ្រការសរសេរ ការជ្រើសរើស និងការចម្លងអត្ថបទ។",
    "KHMER-02": "កម្ពុជា សិល្បៈ អក្សរសាស្ត្រ ព័ត៌មានវិទ្យា និងចំណេះដឹង។",
    "ARABIC": "العربية تدعم ترتيب النص المنطقي والنسخ والبحث.",
    "DEVANAGARI": "हिन्दी पाठ चयन, प्रतिलिपि और खोज का परीक्षण।",
    "THAI": "ภาษาไทยทดสอบการเลือก การคัดลอก และการค้นหาข้อความ",
    "LAO": "ພາສາລາວທົດສອບການເລືອກ ການສຳເນົາ ແລະ ການຄົ້ນຫາ",
}

FONT_FILES = {
    "Latin": "NotoSans-Regular.ttf",
    "Khmer": "NotoSansKhmer-Regular.ttf",
    "Arabic": "NotoSansArabic-Regular.ttf",
    "Devanagari": "NotoSansDevanagari-Regular.ttf",
    "Thai": "NotoSansThai-Regular.ttf",
    "Lao": "NotoSansLao-Regular.ttf",
}

PAYLOAD_FONT = {
    "LATIN": ("Latin", None),
    "COMBINING": ("Latin", None),
    "KHMER-01": ("Khmer", None),
    "KHMER-02": ("Khmer", None),
    "ARABIC": ("Arabic", "rtl"),
    "DEVANAGARI": ("Devanagari", None),
    "THAI": ("Thai", None),
    "LAO": ("Lao", None),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--font-dir",
        type=Path,
        default=Path("/usr/share/fonts/truetype/noto"),
        help="directory containing the required NotoSans*.ttf files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/enhanced-unicode-size"),
    )
    parser.add_argument(
        "--payload-repetitions",
        type=int,
        nargs="+",
        default=[1, 20, 100],
    )
    return parser.parse_args()


def font_paths(font_dir: Path) -> dict[str, Path]:
    paths = {name: font_dir / filename for name, filename in FONT_FILES.items()}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise SystemExit(
            "Missing benchmark fonts:\n  " + "\n  ".join(missing)
        )
    return paths


def configure_fixture(pdf: FPDF, fonts: dict[str, Path], enhanced: bool) -> None:
    for family, path in fonts.items():
        pdf.add_font(family, fname=path)
    pdf.set_font("Latin", size=14)
    pdf.set_fallback_fonts(
        ["Khmer", "Arabic", "Devanagari", "Thai", "Lao"],
        exact_match=False,
    )
    pdf.set_text_shaping(True, enhanced_unicode=enhanced)


def render_fixture(
    path: Path,
    fonts: dict[str, Path],
    enhanced: bool,
    lines: list[str],
    repetitions: int = 1,
) -> None:
    pdf = FPDF(format="A4")
    pdf.set_margins(18, 18, 18)
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    configure_fixture(pdf, fonts, enhanced)
    line_height = pdf.font_size * 1.1

    for repetition in range(repetitions):
        for line in lines:
            pdf.multi_cell(
                w=0,
                h=line_height,
                text=line,
                new_x="LMARGIN",
                new_y="NEXT",
            )
        if repetitions > 1 and repetition + 1 < repetitions:
            pdf.ln(line_height * 0.25)

    pdf.output(path)


def render_payload(
    path: Path,
    fonts: dict[str, Path],
    key: str,
    enhanced: bool,
    repetitions: int,
) -> None:
    family, direction = PAYLOAD_FONT[key]
    pdf = FPDF(format="A4")
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    pdf.add_font(family, fname=fonts[family])
    pdf.set_font(family, size=14)

    shaping: dict[str, Any] = {"enhanced_unicode": enhanced}
    if direction is not None:
        shaping["direction"] = direction
    pdf.set_text_shaping(True, **shaping)

    line_height = pdf.font_size * 1.25
    for _ in range(repetitions):
        pdf.cell(
            w=0,
            h=line_height,
            text=PAYLOADS[key],
            new_x="LMARGIN",
            new_y="NEXT",
        )
    pdf.output(path)


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

        for font_ref in page["/Resources"].get("/Font", {}).values():
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


def comparison(legacy: dict[str, Any], enhanced: dict[str, Any]) -> dict[str, Any]:
    delta = enhanced["bytes"] - legacy["bytes"]
    return {
        "legacy": legacy,
        "enhanced": enhanced,
        "delta_bytes": delta,
        "delta_percent": delta * 100 / legacy["bytes"],
    }


def main() -> None:
    args = parse_args()
    fonts = font_paths(args.font_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {"fixture": {}, "lines": {}, "payload_scaling": {}}

    fixture_lines = FIXTURE_HEADER + [""] + [text for _, text in CASES]
    for enhanced in (False, True):
        kind = "enhanced" if enhanced else "legacy"
        render_fixture(
            args.output_dir / f"fixture-{kind}.pdf",
            fonts,
            enhanced,
            fixture_lines,
        )
    results["fixture"] = comparison(
        inspect_pdf(args.output_dir / "fixture-legacy.pdf"),
        inspect_pdf(args.output_dir / "fixture-enhanced.pdf"),
    )

    for key, line in CASES:
        legacy_path = args.output_dir / f"{key.lower()}-legacy.pdf"
        enhanced_path = args.output_dir / f"{key.lower()}-enhanced.pdf"
        render_fixture(legacy_path, fonts, False, [line])
        render_fixture(enhanced_path, fonts, True, [line])
        results["lines"][key] = comparison(
            inspect_pdf(legacy_path),
            inspect_pdf(enhanced_path),
        )

    for key in PAYLOADS:
        results["payload_scaling"][key] = {}
        for repetitions in args.payload_repetitions:
            legacy_path = (
                args.output_dir / f"{key.lower()}-{repetitions}x-legacy.pdf"
            )
            enhanced_path = (
                args.output_dir / f"{key.lower()}-{repetitions}x-enhanced.pdf"
            )
            render_payload(
                legacy_path, fonts, key, False, repetitions
            )
            render_payload(
                enhanced_path, fonts, key, True, repetitions
            )
            results["payload_scaling"][key][str(repetitions)] = comparison(
                inspect_pdf(legacy_path),
                inspect_pdf(enhanced_path),
            )

    result_path = args.output_dir / "results.json"
    result_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(result_path)


if __name__ == "__main__":
    main()
