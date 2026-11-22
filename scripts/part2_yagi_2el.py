from __future__ import annotations

import csv
import math
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
PART2 = ROOT / "Part2"
RUNS = PART2 / "nec_runs"
DATA = PART2 / "data"
NEC2_EXE = Path(os.environ.get("NEC2_EXE", "nec2dxs500.exe")).resolve()

DRIVEN_LENGTH_M = 0.457
INITIAL_REFLECTOR_LENGTH_M = 0.480
INITIAL_SPACING_M = 0.200
DIAMETER_M = 0.008
RADIUS_M = DIAMETER_M / 2
SEGMENTS = 15
SOURCE_SEGMENT = (SEGMENTS + 1) // 2
Z0 = 50.0

FLOAT_RE = re.compile(r"[-+]?\d+(?:\.\d*)?(?:E[-+]?\d+)?", re.IGNORECASE)


@dataclass
class SweepPoint:
    frequency_mhz: float
    resistance_ohm: float
    reactance_ohm: float
    s11_db: float
    gain_db: float | None = None
    realized_gain_db: float | None = None


@dataclass
class PatternPoint:
    frequency_mhz: float
    theta_deg: float
    phi_deg: float
    total_gain_db: float
    realized_gain_db: float | None = None


def parse_floats(line: str) -> list[float]:
    return [float(x) for x in FLOAT_RE.findall(line)]


def s11_db(resistance: float, reactance: float, z0: float = Z0) -> float:
    z = complex(resistance, reactance)
    gamma = (z - z0) / (z + z0)
    return 20.0 * math.log10(max(abs(gamma), 1e-15))


def mismatch_efficiency_db(resistance: float, reactance: float, z0: float = Z0) -> float:
    z = complex(resistance, reactance)
    gamma = (z - z0) / (z + z0)
    return 10.0 * math.log10(max(1.0 - abs(gamma) ** 2, 1e-15))


def write_yagi_nec(
    path: Path,
    *,
    title: str,
    reflector_length_m: float,
    reflector_spacing_m: float,
    start_mhz: float = 250.0,
    count: int = 101,
    step_mhz: float = 1.0,
    rp_card: str | None = "RP 0 1 1 1000 90 0 0 0",
) -> None:
    driven_half = DRIVEN_LENGTH_M / 2
    reflector_half = reflector_length_m / 2
    reflector_x = -reflector_spacing_m
    lines = [
        f"CM {title}",
        "CM 2-element Yagi-Uda antenna for NIE2226 Part 2",
        f"CM Driven dipole length: {DRIVEN_LENGTH_M:.6f} m",
        f"CM Reflector length: {reflector_length_m:.6f} m",
        f"CM Reflector spacing behind driven element: {reflector_spacing_m:.6f} m",
        f"CM Diameter: {DIAMETER_M:.6f} m",
        "CM Geometry: vertical elements along z-axis; forward direction is +x",
        "CE",
        f"GW 1 {SEGMENTS} 0 0 {-driven_half:.6f} 0 0 {driven_half:.6f} {RADIUS_M:.6f}",
        f"GW 2 {SEGMENTS} {reflector_x:.6f} 0 {-reflector_half:.6f} {reflector_x:.6f} 0 {reflector_half:.6f} {RADIUS_M:.6f}",
        "GE 0",
        f"EX 0 1 {SOURCE_SEGMENT} 0 1 0",
        f"FR 0 {count} 0 0 {start_mhz:g} {step_mhz:g}",
    ]
    if rp_card:
        lines.append(rp_card)
    lines.extend(["XQ", "EN", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="ascii")


def run_nec(inp: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    # NEC-2 truncates long paths entered at its file prompts.
    proc = subprocess.run(
        [str(NEC2_EXE)],
        input=f"{inp.name}\n{out.name}\n",
        cwd=inp.parent,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"NEC2 failed for {inp.name}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    if not out.exists():
        raise RuntimeError(f"NEC2 did not create output file: {out}")


def parse_output(path: Path) -> tuple[list[SweepPoint], list[PatternPoint]]:
    sweep: list[SweepPoint] = []
    patterns: list[PatternPoint] = []
    current_freq: float | None = None
    want_source = False
    in_pattern = False
    pattern_ready = False

    for raw in path.read_text(errors="replace").splitlines():
        line = raw.rstrip()
        if "FREQUENCY=" in line:
            nums = parse_floats(line)
            if nums:
                current_freq = nums[0]
            want_source = False
            in_pattern = False
            pattern_ready = False
            continue

        if "ANTENNA INPUT PARAMETERS" in line:
            want_source = True
            continue

        if want_source and current_freq is not None:
            nums = parse_floats(line)
            if len(nums) >= 11 and int(nums[0]) == 1 and int(nums[1]) == SOURCE_SEGMENT:
                resistance = nums[6]
                reactance = nums[7]
                sweep.append(
                    SweepPoint(
                        frequency_mhz=current_freq,
                        resistance_ohm=resistance,
                        reactance_ohm=reactance,
                        s11_db=s11_db(resistance, reactance),
                    )
                )
                want_source = False
            continue

        if "RADIATION PATTERNS" in line:
            in_pattern = True
            pattern_ready = False
            continue

        if in_pattern and "DEGREES" in line:
            pattern_ready = True
            continue

        if in_pattern and pattern_ready and current_freq is not None:
            nums = parse_floats(line)
            if len(nums) >= 5:
                patterns.append(
                    PatternPoint(
                        frequency_mhz=current_freq,
                        theta_deg=nums[0],
                        phi_deg=nums[1],
                        total_gain_db=nums[4],
                    )
                )
            elif not line.strip():
                in_pattern = False
                pattern_ready = False

    by_freq = {round(p.frequency_mhz, 9): p for p in sweep}
    for pattern in patterns:
        sweep_point = by_freq.get(round(pattern.frequency_mhz, 9))
        if sweep_point is not None:
            pattern.realized_gain_db = (
                pattern.total_gain_db
                + mismatch_efficiency_db(
                    sweep_point.resistance_ohm, sweep_point.reactance_ohm
                )
            )

    gain_by_freq: dict[float, float] = {}
    realized_by_freq: dict[float, float] = {}
    for pattern in patterns:
        key = round(pattern.frequency_mhz, 9)
        gain_by_freq[key] = max(gain_by_freq.get(key, -999.0), pattern.total_gain_db)
        if pattern.realized_gain_db is not None:
            realized_by_freq[key] = max(
                realized_by_freq.get(key, -999.0), pattern.realized_gain_db
            )
    for point in sweep:
        key = round(point.frequency_mhz, 9)
        point.gain_db = gain_by_freq.get(key)
        point.realized_gain_db = realized_by_freq.get(key)

    return sweep, patterns


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def excel_column(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def write_simple_xlsx(
    path: Path, sheet_name: str, rows: list[dict[str, object]], fieldnames: list[str]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet_rows: list[str] = []
    all_rows: list[list[object]] = [fieldnames]
    all_rows.extend([[row.get(field, "") for field in fieldnames] for row in rows])
    for row_index, row in enumerate(all_rows, start=1):
        cells: list[str] = []
        for col_index, value in enumerate(row, start=1):
            ref = f"{excel_column(col_index)}{row_index}"
            if isinstance(value, int | float) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            elif value is None:
                cells.append(f'<c r="{ref}"/>')
            else:
                cells.append(
                    f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
                )
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheetData>{''.join(sheet_rows)}</sheetData></worksheet>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/worksheets/sheet1.xml", worksheet)


def interpolate_crossing(
    f1: float, y1: float, f2: float, y2: float, target: float
) -> float:
    if abs(y2 - y1) < 1e-12:
        return f1
    return f1 + (target - y1) * (f2 - f1) / (y2 - y1)


def bandwidth_10db(points: list[SweepPoint]) -> tuple[float | None, float | None, float | None]:
    min_i = min(range(len(points)), key=lambda i: points[i].s11_db)
    if points[min_i].s11_db > -10:
        return None, None, None
    left = None
    for i in range(min_i, 0, -1):
        if points[i].s11_db <= -10 <= points[i - 1].s11_db:
            left = interpolate_crossing(
                points[i - 1].frequency_mhz,
                points[i - 1].s11_db,
                points[i].frequency_mhz,
                points[i].s11_db,
                -10,
            )
            break
    if left is None and points[0].s11_db <= -10:
        left = points[0].frequency_mhz
    right = None
    for i in range(min_i, len(points) - 1):
        if points[i].s11_db <= -10 <= points[i + 1].s11_db:
            right = interpolate_crossing(
                points[i].frequency_mhz,
                points[i].s11_db,
                points[i + 1].frequency_mhz,
                points[i + 1].s11_db,
                -10,
            )
            break
    if right is None and points[-1].s11_db <= -10:
        right = points[-1].frequency_mhz
    if left is None or right is None:
        return left, right, None
    return left, right, right - left


def run_sweep(
    name: str,
    *,
    reflector_length_m: float,
    reflector_spacing_m: float,
    start_mhz: float = 250.0,
    count: int = 101,
    step_mhz: float = 1.0,
    rp_card: str | None = "RP 0 1 1 1000 90 0 0 0",
) -> tuple[list[SweepPoint], list[PatternPoint], Path, Path]:
    inp = RUNS / f"{name}.inp"
    out = RUNS / f"{name}.out"
    write_yagi_nec(
        inp,
        title=name,
        reflector_length_m=reflector_length_m,
        reflector_spacing_m=reflector_spacing_m,
        start_mhz=start_mhz,
        count=count,
        step_mhz=step_mhz,
        rp_card=rp_card,
    )
    run_nec(inp, out)
    sweep, patterns = parse_output(out)
    return sweep, patterns, inp, out


def summarize_sweep(points: list[SweepPoint]) -> dict[str, float | None]:
    resonant = min(points, key=lambda p: p.s11_db)
    gain_points = [p for p in points if p.realized_gain_db is not None]
    peak_gain = max(gain_points, key=lambda p: p.realized_gain_db) if gain_points else None
    f_l, f_h, bw = bandwidth_10db(points)
    fractional = (bw / resonant.frequency_mhz * 100.0) if bw is not None else None
    at_300 = min(points, key=lambda p: abs(p.frequency_mhz - 300.0))
    return {
        "resonant_frequency_mhz": resonant.frequency_mhz,
        "minimum_s11_db": resonant.s11_db,
        "resonant_resistance_ohm": resonant.resistance_ohm,
        "resonant_reactance_ohm": resonant.reactance_ohm,
        "s11_at_300_db": at_300.s11_db,
        "realized_gain_at_300_dbi": at_300.realized_gain_db,
        "f_l_10db_mhz": f_l,
        "f_h_10db_mhz": f_h,
        "bandwidth_10db_mhz": bw,
        "fractional_bandwidth_percent": fractional,
        "peak_realized_gain_dbi": None if peak_gain is None else peak_gain.realized_gain_db,
        "peak_realized_gain_frequency_mhz": None if peak_gain is None else peak_gain.frequency_mhz,
    }


def pattern_rows(patterns: list[PatternPoint]) -> list[dict[str, object]]:
    return [
        {
            "frequency_mhz": p.frequency_mhz,
            "theta_deg": p.theta_deg,
            "phi_deg": p.phi_deg,
            "gain_dbi": p.total_gain_db,
            "realized_gain_dbi_50ohm": p.realized_gain_db,
        }
        for p in patterns
    ]


def front_back_rows(patterns: list[PatternPoint]) -> list[dict[str, object]]:
    by_freq: dict[float, list[PatternPoint]] = {}
    for p in patterns:
        by_freq.setdefault(round(p.frequency_mhz, 9), []).append(p)
    rows: list[dict[str, object]] = []
    for freq, pts in sorted(by_freq.items()):
        front = min(pts, key=lambda p: abs(p.phi_deg - 0.0))
        back = min(pts, key=lambda p: abs(p.phi_deg - 180.0))
        rows.append(
            {
                "frequency_mhz": freq,
                "front_gain_dbi": front.total_gain_db,
                "back_gain_dbi": back.total_gain_db,
                "front_back_ratio_db": front.total_gain_db - back.total_gain_db,
                "front_realized_gain_dbi_50ohm": front.realized_gain_db,
                "back_realized_gain_dbi_50ohm": back.realized_gain_db,
            }
        )
    return rows


def value_at_300(rows: list[dict[str, object]], key: str) -> float | None:
    candidates = [row for row in rows if abs(float(row["frequency_mhz"]) - 300.0) < 1e-9]
    if not candidates:
        return None
    value = candidates[0].get(key)
    return None if value is None else float(value)


def fmt(value: float | None, places: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{places}f}"


def main() -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    # Initial assignment model.
    write_yagi_nec(
        PART2 / "yagi_2el_initial.nec",
        title="NIE2226 Part 2 initial 2-element Yagi",
        reflector_length_m=INITIAL_REFLECTOR_LENGTH_M,
        reflector_spacing_m=INITIAL_SPACING_M,
        rp_card="RP 0 1 1 1000 90 0 0 0",
    )
    initial_points, _, _, _ = run_sweep(
        "yagi_2el_initial_front_gain",
        reflector_length_m=INITIAL_REFLECTOR_LENGTH_M,
        reflector_spacing_m=INITIAL_SPACING_M,
        rp_card="RP 0 1 1 1000 90 0 0 0",
    )
    initial_summary = summarize_sweep(initial_points)

    # Reflector length sweep at fixed initial spacing.
    length_rows: list[dict[str, object]] = []
    for length in [0.44, 0.46, 0.48, 0.50, 0.52]:
        points, _, _, _ = run_sweep(
            f"reflector_length_{length:.2f}m".replace(".", "p"),
            reflector_length_m=length,
            reflector_spacing_m=INITIAL_SPACING_M,
            rp_card="RP 0 1 1 1000 90 0 0 0",
        )
        length_rows.append(
            {
                "reflector_length_m": length,
                "reflector_spacing_m": INITIAL_SPACING_M,
                **summarize_sweep(points),
            }
        )

    best_length_row = max(
        length_rows,
        key=lambda row: (
            -999.0
            if row["realized_gain_at_300_dbi"] is None
            else float(row["realized_gain_at_300_dbi"])
        ),
    )
    best_length = float(best_length_row["reflector_length_m"])

    # Reflector spacing sweep using best length from previous step.
    spacing_rows: list[dict[str, object]] = []
    for spacing in [0.10, 0.15, 0.20, 0.25, 0.30]:
        points, fb_patterns, _, _ = run_sweep(
            f"reflector_spacing_{spacing:.2f}m".replace(".", "p"),
            reflector_length_m=best_length,
            reflector_spacing_m=spacing,
            rp_card="RP 0 1 2 1000 90 0 0 180",
        )
        fb_rows = front_back_rows(fb_patterns)
        summary = summarize_sweep(points)
        spacing_rows.append(
            {
                "reflector_length_m": best_length,
                "reflector_spacing_m": spacing,
                "front_back_ratio_at_300_db": value_at_300(fb_rows, "front_back_ratio_db"),
                **summary,
            }
        )

    best_spacing_row = max(
        spacing_rows,
        key=lambda row: (
            -999.0
            if row["realized_gain_at_300_dbi"] is None
            else float(row["realized_gain_at_300_dbi"])
        ),
    )
    best_spacing = float(best_spacing_row["reflector_spacing_m"])

    # Final optimized 2-element Yagi data.
    final_points, _, _, _ = run_sweep(
        "yagi_2el_final_front_gain",
        reflector_length_m=best_length,
        reflector_spacing_m=best_spacing,
        rp_card="RP 0 1 1 1000 90 0 0 0",
    )
    final_summary = summarize_sweep(final_points)
    _, final_fb_patterns, _, _ = run_sweep(
        "yagi_2el_final_fb",
        reflector_length_m=best_length,
        reflector_spacing_m=best_spacing,
        rp_card="RP 0 1 2 1000 90 0 0 180",
    )
    final_fb_rows = front_back_rows(final_fb_patterns)
    _, az_patterns, _, _ = run_sweep(
        "yagi_2el_pattern_300mhz_azimuth",
        reflector_length_m=best_length,
        reflector_spacing_m=best_spacing,
        start_mhz=300.0,
        count=1,
        step_mhz=0.0,
        rp_card="RP 0 1 361 1000 90 0 0 1",
    )
    _, el_patterns, _, _ = run_sweep(
        "yagi_2el_pattern_300mhz_elevation",
        reflector_length_m=best_length,
        reflector_spacing_m=best_spacing,
        start_mhz=300.0,
        count=1,
        step_mhz=0.0,
        rp_card="RP 0 181 1 1000 0 0 1 0",
    )

    write_yagi_nec(
        PART2 / "yagi_2el_final.nec",
        title="NIE2226 Part 2 final 2-element Yagi",
        reflector_length_m=best_length,
        reflector_spacing_m=best_spacing,
        rp_card="RP 0 1 1 1000 90 0 0 0",
    )

    s11_rows = [
        {
            "frequency_mhz": p.frequency_mhz,
            "resistance_ohm": p.resistance_ohm,
            "reactance_ohm": p.reactance_ohm,
            "s11_db_50ohm": p.s11_db,
        }
        for p in final_points
    ]
    gain_rows = [
        {
            "frequency_mhz": p.frequency_mhz,
            "forward_gain_dbi": p.gain_db,
            "forward_realized_gain_dbi_50ohm": p.realized_gain_db,
        }
        for p in final_points
    ]
    write_csv(DATA / "yagi_2el_s11.csv", s11_rows, list(s11_rows[0].keys()))
    write_csv(DATA / "yagi_2el_gain.csv", gain_rows, list(gain_rows[0].keys()))
    write_csv(DATA / "yagi_2el_fb.csv", final_fb_rows, list(final_fb_rows[0].keys()))
    write_csv(
        DATA / "yagi_2el_pattern_azimuth_300MHz.csv",
        pattern_rows(az_patterns),
        ["frequency_mhz", "theta_deg", "phi_deg", "gain_dbi", "realized_gain_dbi_50ohm"],
    )
    write_csv(
        DATA / "yagi_2el_pattern_elevation_300MHz.csv",
        pattern_rows(el_patterns),
        ["frequency_mhz", "theta_deg", "phi_deg", "gain_dbi", "realized_gain_dbi_50ohm"],
    )

    length_fields = [
        "reflector_length_m",
        "reflector_spacing_m",
        "resonant_frequency_mhz",
        "minimum_s11_db",
        "resonant_resistance_ohm",
        "resonant_reactance_ohm",
        "s11_at_300_db",
        "realized_gain_at_300_dbi",
        "peak_realized_gain_dbi",
        "peak_realized_gain_frequency_mhz",
        "f_l_10db_mhz",
        "f_h_10db_mhz",
        "bandwidth_10db_mhz",
        "fractional_bandwidth_percent",
    ]
    spacing_fields = [
        "reflector_length_m",
        "reflector_spacing_m",
        "front_back_ratio_at_300_db",
        "resonant_frequency_mhz",
        "minimum_s11_db",
        "resonant_resistance_ohm",
        "resonant_reactance_ohm",
        "s11_at_300_db",
        "realized_gain_at_300_dbi",
        "peak_realized_gain_dbi",
        "peak_realized_gain_frequency_mhz",
        "f_l_10db_mhz",
        "f_h_10db_mhz",
        "bandwidth_10db_mhz",
        "fractional_bandwidth_percent",
    ]
    write_csv(DATA / "reflector_length_sweep.csv", length_rows, length_fields)
    write_csv(DATA / "reflector_spacing_sweep.csv", spacing_rows, spacing_fields)
    write_simple_xlsx(PART2 / "reflector_length_sweep.xlsx", "reflector_length", length_rows, length_fields)
    write_simple_xlsx(PART2 / "reflector_spacing_sweep.xlsx", "reflector_spacing", spacing_rows, spacing_fields)

    for filename in [
        "yagi_2el_s11.csv",
        "yagi_2el_gain.csv",
        "yagi_2el_fb.csv",
        "yagi_2el_pattern_azimuth_300MHz.csv",
        "yagi_2el_pattern_elevation_300MHz.csv",
        "reflector_length_sweep.csv",
        "reflector_spacing_sweep.csv",
    ]:
        shutil.copyfile(DATA / filename, PART2 / filename)

    final_fb_300 = value_at_300(final_fb_rows, "front_back_ratio_db")
    initial_gain_300 = initial_summary["realized_gain_at_300_dbi"]
    final_gain_300 = final_summary["realized_gain_at_300_dbi"]
    gain_improvement = (
        None
        if initial_gain_300 is None or final_gain_300 is None
        else final_gain_300 - initial_gain_300
    )

    summary_lines = [
        "NIE2226 Part 2 2-element Yagi-Uda NEC2 summary",
        "================================================",
        f"Driven dipole length: {DRIVEN_LENGTH_M:.3f} m",
        f"Element diameter: {DIAMETER_M:.3f} m",
        "",
        "Initial assignment reflector:",
        f"  Reflector length: {INITIAL_REFLECTOR_LENGTH_M:.3f} m",
        f"  Reflector spacing: {INITIAL_SPACING_M:.3f} m",
        f"  Realized gain at 300 MHz: {fmt(initial_summary['realized_gain_at_300_dbi'])} dBi",
        f"  S11 at 300 MHz: {fmt(initial_summary['s11_at_300_db'])} dB",
        "",
        "Selected final 2-element design from sweeps:",
        f"  Reflector length: {best_length:.3f} m",
        f"  Reflector spacing: {best_spacing:.3f} m",
        f"  Resonant frequency by minimum S11: {fmt(final_summary['resonant_frequency_mhz'])} MHz",
        f"  Minimum S11: {fmt(final_summary['minimum_s11_db'])} dB",
        f"  S11 at 300 MHz: {fmt(final_summary['s11_at_300_db'])} dB",
        f"  Realized gain at 300 MHz: {fmt(final_summary['realized_gain_at_300_dbi'])} dBi",
        f"  Peak realized gain: {fmt(final_summary['peak_realized_gain_dbi'])} dBi at {fmt(final_summary['peak_realized_gain_frequency_mhz'])} MHz",
        f"  Gain improvement vs initial reflector case at 300 MHz: {fmt(gain_improvement)} dB",
        f"  Front-to-back ratio at 300 MHz: {fmt(final_fb_300)} dB",
        f"  -10 dB lower frequency: {fmt(final_summary['f_l_10db_mhz'])} MHz",
        f"  -10 dB upper frequency: {fmt(final_summary['f_h_10db_mhz'])} MHz",
        f"  -10 dB bandwidth: {fmt(final_summary['bandwidth_10db_mhz'])} MHz",
        f"  Fractional bandwidth: {fmt(final_summary['fractional_bandwidth_percent'])} %",
        "",
        "Generated files:",
        "  Part2/yagi_2el_initial.nec",
        "  Part2/yagi_2el_final.nec",
        "  Part2/yagi_2el_s11.csv",
        "  Part2/yagi_2el_gain.csv",
        "  Part2/yagi_2el_fb.csv",
        "  Part2/reflector_length_sweep.xlsx",
        "  Part2/reflector_spacing_sweep.xlsx",
    ]
    (DATA / "yagi_2el_summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    (PART2 / "yagi_2el_summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print("\n".join(summary_lines))


if __name__ == "__main__":
    main()
