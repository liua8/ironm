"""Rebuild the demo files in `upload/` from the panels written here.

    python demo/generate.py

Run it after changing a panel, or to give a new demo account its own files.
The seeded side (`seed/*.md`) is hand-written and not touched: its values have
to agree with `_PROFILES` in `mirobody/server/demo.py`, which is what
`tests/server/test_member_seed.py` checks.

Four formats on purpose. A health record arrives as whatever the lab, the
clinic and the family actually produce, so the demo uploads a PDF, a phone
photo, a spreadsheet and a CSV rather than four of the same thing. Needs
Pillow and openpyxl, both in the `[app]` extra.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "upload"

BANNER = "SYNTHETIC SAMPLE - GENERATED DATA, NOT A REAL PATIENT RECORD"

#: The second panel each account gets, the one that does NOT come pre-seeded.
#: Every analyte here is spelled exactly as the seeded panel spells it, because
#: `collect.query` resolves the indicator NAME to a LOINC code at read time:
#: same name, same series, so an upload is a second point rather than a new
#: orphan indicator. Measured 2026-09-17: "Glycated Hemoglobin-HbA1c" resolves
#: to 4548-4 and "GlycatedHemoglobin-HbA1c" resolves to nothing.
PANELS = {
    "you_annual_checkup_2026-05": {
        "title": "Annual Checkup",
        "subject": "you@mirobody.ai / 41y",
        "collected": "2026-05-06",
        "exam": "annual physical (clinic)",
        "rows": [
            ("Glycated Hemoglobin-HbA1c", "5.2", "%", "4.0-5.6", ""),
            ("Fasting Blood Glucose-FBG", "4.9", "mmol/L", "3.9-6.1", ""),
            ("Total Cholesterol-TC", "4.45", "mmol/L", "3.0-5.18", ""),
            ("Low-Density Lipoprotein-LDL", "2.48", "mmol/L", "<3.4", ""),
            ("High-Density Lipoprotein-HDL", "1.50", "mmol/L", ">1.0", ""),
            ("Triglycerides-TG", "0.95", "mmol/L", "0.4-1.7", ""),
            ("Systolic Blood Pressure", "116", "mmHg", "<120", ""),
            ("Diastolic Blood Pressure", "75", "mmHg", "<80", ""),
            ("Resting Heart Rate", "57", "bpm", "60-100", "L"),
        ],
        "note": "No findings. Continue current activity level; recheck in 12 months.",
    },
    "mom_physical_2026-06": {
        "title": "Physical Examination",
        "subject": "mom@mirobody.ai / 63y",
        "collected": "2026-06-11",
        "exam": "follow-up (hospital)",
        "rows": [
            ("Glycated Hemoglobin-HbA1c", "6.0", "%", "4.0-5.6", "H"),
            ("Fasting Blood Glucose-FBG", "6.0", "mmol/L", "3.9-6.1", ""),
            ("Total Cholesterol-TC", "5.53", "mmol/L", "3.0-5.18", "H"),
            ("Low-Density Lipoprotein-LDL", "3.65", "mmol/L", "<3.4", "H"),
            ("High-Density Lipoprotein-HDL", "1.09", "mmol/L", ">1.0", ""),
            ("Triglycerides-TG", "1.90", "mmol/L", "0.4-1.7", "H"),
            ("Systolic Blood Pressure", "134", "mmHg", "<120", "H"),
            ("Diastolic Blood Pressure", "87", "mmHg", "<80", "H"),
            ("Resting Heart Rate", "73", "bpm", "60-100", ""),
        ],
        "note": "HbA1c and lipids above range; recheck in three months. Discussed activity and sleep.",
    },
}

#: A lipid panel a DIFFERENT lab exported as a csv, and it names the analytes
#: its own way. That is the point of this file: `Cholesterol, Total` and
#: `Total Cholesterol-TC` are the same test, and the record knows it because
#: both resolve to 14647-2. Measured 2026-09-17, six spellings and six matches.
#: The units match the other reports on purpose: LOINC puts the unit IN the
#: identity, so cholesterol is 14647-2 in mmol/L and 2093-3 in mg/dL, and
#: reconciling those two is the comparability key 1.5.0 brings.
#:
#: ONE collection date, like every file here. `resolve_report_date` gives a
#: whole file a single date, so a spreadsheet of seven mornings collapses to
#: one reading (measured: 7 rows in, 1 row out).
CSV_PANEL = {
    "collected": "2026-08-04",
    "rows": [
        ("Glucose, Fasting", "4.9", "mmol/L", "3.9-6.1"),
        ("Cholesterol, Total", "4.38", "mmol/L", "3.0-5.18"),
        ("LDL Cholesterol", "2.41", "mmol/L", "<3.4"),
        ("HDL Cholesterol", "1.52", "mmol/L", ">1.0"),
        ("Triglyceride", "0.91", "mmol/L", "0.4-1.7"),
    ],
}

#: What the clinic typed into a spreadsheet at mom's July visit.
#: Body weight and blood pressure are already in that account's device series
#: under the catalogue's names, so these land BESIDE them carrying the same
#: LOINC code: two sources, two rows, one code.
XLSX_PANEL = {
    "collected": "2026-07-07",
    "rows": [
        ("Body weight", 84.2, "kg"),
        ("Systolic Blood Pressure", 136, "mmHg"),
        ("Diastolic Blood Pressure", 88, "mmHg"),
        ("Fasting Blood Glucose-FBG", 6.2, "mmol/L"),
    ],
}


# ── PDF ──────────────────────────────────────────────────────────────────────
# Written out by hand rather than with a PDF library: a demo fixture is not
# worth a dependency, and the whole file is seven objects of Helvetica text.

def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _text(x: float, y: float, body: str, *, size: int = 10, bold: bool = False) -> str:
    font = "F2" if bold else "F1"
    return f"BT /{font} {size} Tf 1 0 0 1 {x} {y} Tm ({_escape(body)}) Tj ET\n"


def _pdf_stream(panel: dict) -> str:
    out = _text(48, 794, BANNER, size=9, bold=True)
    out += _text(48, 770, panel["title"], size=18, bold=True)
    out += _text(48, 747.5, f"Subject:   {panel['subject']}")
    out += _text(48, 732.5, f"Collected: {panel['collected']}")
    out += _text(48, 717.5, f"Exam:      {panel['exam']}")

    columns = ((48, "Analyte"), (298, "Result"), (368, "Unit"), (438, "Reference"), (528, "Flag"))
    for x, label in columns:
        out += _text(x, 690.5, label, bold=True)
    out += "0.5 w 48 684.5 m 547 684.5 l S\n"

    y = 669.5
    for analyte, result, unit, reference, flag in panel["rows"]:
        out += _text(48, y, analyte)
        out += _text(298, y, result, bold=True)
        out += _text(368, y, unit)
        out += _text(438, y, reference)
        if flag:
            out += _text(528, y, flag)
        y -= 15

    out += _text(48, y - 15, "Note: " + panel["note"])
    return out


def _pdf(panel: dict) -> bytes:
    stream = _pdf_stream(panel)
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources "
        "<< /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}endstream",
    ]

    body = "%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n{obj}\nendobj\n"

    xref_at = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    body += "".join(f"{offset:010d} 00000 n \n" for offset in offsets)
    body += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info "
        f"<< /Title ({_escape(panel['title'])}) /Producer (mirobody demo) >> >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    )
    return body.encode("latin-1")


# ── JPG ──────────────────────────────────────────────────────────────────────
# A phone photo of a printed slip, because that is how most people hand over a
# report. Slightly rotated and slightly uneven in brightness: a fixture that is
# a clean screenshot would not exercise the path the picture actually takes.

def _jpg(panel: dict) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    def font(size: int, bold: bool = False):
        name = "Arial Bold.ttf" if bold else "Arial.ttf"
        return ImageFont.truetype(f"/System/Library/Fonts/Supplemental/{name}", size)

    page = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(page)
    draw.text((70, 60), BANNER, font=font(22, bold=True), fill=(120, 120, 120))
    draw.text((70, 110), panel["title"], font=font(46, bold=True), fill="black")
    draw.text((70, 185), f"Subject:   {panel['subject']}", font=font(26), fill="black")
    draw.text((70, 225), f"Collected: {panel['collected']}", font=font(26), fill="black")
    draw.text((70, 265), f"Exam:      {panel['exam']}", font=font(26), fill="black")

    columns = ((70, "Analyte"), (640, "Result"), (800, "Unit"), (960, "Reference"), (1130, "Flag"))
    for x, label in columns:
        draw.text((x, 340), label, font=font(26, bold=True), fill="black")
    draw.line((70, 380, 1170, 380), fill="black", width=2)

    y = 405
    for analyte, result, unit, reference, flag in panel["rows"]:
        draw.text((70, y), analyte, font=font(26), fill="black")
        draw.text((640, y), result, font=font(26, bold=True), fill="black")
        draw.text((800, y), unit, font=font(26), fill="black")
        draw.text((960, y), reference, font=font(26), fill="black")
        draw.text((1130, y), flag, font=font(26), fill="black")
        y += 46

    draw.text((70, y + 40), "Note: " + panel["note"], font=font(24), fill="black")
    page = page.crop((0, 0, page.width, y + 140))

    # Photographed, not scanned: a slight rotation and one end that caught less
    # light. Enough to look like a picture, not enough to hurt legibility.
    page = page.rotate(-1.1, resample=Image.BICUBIC, expand=True, fillcolor=(238, 236, 232))
    shade = Image.linear_gradient("L").resize(page.size).point(lambda v: 150 + v // 3)
    page = Image.composite(page, Image.new("RGB", page.size, (0, 0, 0)), shade)

    buffer = io.BytesIO()
    page.resize((page.width // 2, page.height // 2)).save(buffer, "JPEG", quality=82)
    return buffer.getvalue()


# ── CSV and XLSX ─────────────────────────────────────────────────────────────

def _csv() -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["collected", "analyte", "result", "unit", "reference"])
    for analyte, result, unit, reference in CSV_PANEL["rows"]:
        writer.writerow([CSV_PANEL["collected"], analyte, result, unit, reference])
    return buffer.getvalue().encode("utf-8")


def _xlsx() -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Clinic visit"
    # Spelled out, not "Systolic"/"Diastolic". Measured 2026-09-17 against the
    # shipped resolver: the bare words send systolic to 24372-5 (peak pressure
    # during a rising phase) and leave diastolic unresolved, while the full
    # names land on 8480-6 and 8462-4.
    sheet.append(["Date", "Measurement", "Result", "Unit"])
    for measurement, result, unit in XLSX_PANEL["rows"]:
        sheet.append([XLSX_PANEL["collected"], measurement, result, unit])
    for column, width in zip("ABCD", (14, 30, 12, 12)):
        sheet.column_dimensions[column].width = width

    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    written = {
        "you_annual_checkup_2026-05.pdf": _pdf(PANELS["you_annual_checkup_2026-05"]),
        "you_lipid_panel_2026-08.csv": _csv(),
        "mom_physical_2026-06.jpg": _jpg(PANELS["mom_physical_2026-06"]),
        "mom_clinic_visit_2026-07.xlsx": _xlsx(),
    }
    for name, payload in written.items():
        (OUT / name).write_bytes(payload)
        print(f"{name:40} {len(payload):>8,} bytes")


if __name__ == "__main__":
    main()
