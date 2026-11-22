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
PART1 = ROOT / "Part1"
RUNS = PART1 / "nec_runs"
DATA = PART1 / "data"
NEC2_EXE = Path(os.environ.get("NEC2_EXE", "nec2dxs500.exe")).resolve()

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


def write_nec(
    path: Path,
    *,
    title: str,
    length_m: float,
    diameter_m: float,
    start_mhz: float = 250.0,
    count: int = 101,
    step_mhz: float = 1.0,
    rp_card: str | None = "RP 0 1 1 1000 90 0 0 0",
) -> None:
    radius = diameter_m / 2
    half = length_m / 2
    lines = [
        f"CM {title}",
        f"CM Total length: {length_m:.6f} m",
        f"CM Diameter: {diameter_m:.6f} m",
        "CM Vertical dipole along z-axis, centred at origin",
        "CE",
        f"GW 1 {SEGMENTS} 0 0 {-half:.6f} 0 0 {half:.6f} {radius:.6f}",
        "GE 0",
        f"EX 0 1 {SOURCE_SEGMENT} 0 1 0",
        f"FR 0 {count} 0 0 {start_mhz:g} {step_mhz:g}",
    ]
    if rp_card:
        lines.append(rp_card)
    lines.extend(["XQ", "EN", ""])
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
        raise RuntimeError(f"NEC2 did not create expected output file: {out}")


def parse_floats(line: str) -> list[float]:
    return [float(x) for x in FLOAT_RE.findall(line)]


def s11_db(resistance: float, reactance: float, z0: float = Z0) -> float:
    z = complex(resistance, reactance)
    gamma = (z - z0) / (z + z0)
    mag = max(abs(gamma), 1e-15)
    return 20.0 * math.log10(mag)


def mismatch_efficiency_db(resistance: float, reactance: float, z0: float = Z0) -> float:
    z = complex(resistance, reactance)
    gamma = (z - z0) / (z + z0)
    eff = max(1.0 - abs(gamma) ** 2, 1e-15)
    return 10.0 * math.log10(eff)


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
        freq = round(pattern.frequency_mhz, 9)
        gain_by_freq[freq] = max(gain_by_freq.get(freq, -999.0), pattern.total_gain_db)
        if pattern.realized_gain_db is not None:
            realized_by_freq[freq] = max(
                realized_by_freq.get(freq, -999.0), pattern.realized_gain_db
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
                text = escape(str(value))
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheetData>{''.join(sheet_rows)}</sheetData>"
        "</worksheet>"
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
    if not points:
        return None, None, None
    min_i = min(range(len(points)), key=lambda i: points[i].s11_db)
    if points[min_i].s11_db > -10:
        return None, None, None

    left = None
    for i in range(min_i, 0, -1):
        y_hi = points[i].s11_db
        y_lo = points[i - 1].s11_db
        if y_hi <= -10 <= y_lo:
            left = interpolate_crossing(
                points[i - 1].frequency_mhz, y_lo, points[i].frequency_mhz, y_hi, -10
            )
            break
    if left is None and points[0].s11_db <= -10:
        left = points[0].frequency_mhz

    right = None
    for i in range(min_i, len(points) - 1):
        y_lo = points[i].s11_db
        y_hi = points[i + 1].s11_db
        if y_lo <= -10 <= y_hi:
            right = interpolate_crossing(
                points[i].frequency_mhz, y_lo, points[i + 1].frequency_mhz, y_hi, -10
            )
            break
    if right is None and points[-1].s11_db <= -10:
        right = points[-1].frequency_mhz

    if left is None or right is None:
        return left, right, None
    return left, right, right - left


def hpbw(patterns: list[PatternPoint]) -> tuple[float, float, float]:
    at_300 = [p for p in patterns if abs(p.frequency_mhz - 300.0) < 1e-6]
    if not at_300:
        raise RuntimeError("No 300 MHz pattern points found")
    at_300.sort(key=lambda p: p.theta_deg)
    max_i = max(range(len(at_300)), key=lambda i: at_300[i].total_gain_db)
    peak = at_300[max_i].total_gain_db
    target = peak - 3.0

    left = None
    for i in range(max_i, 0, -1):
        if at_300[i - 1].total_gain_db <= target <= at_300[i].total_gain_db:
            left = interpolate_crossing(
                at_300[i - 1].theta_deg,
                at_300[i - 1].total_gain_db,
                at_300[i].theta_deg,
                at_300[i].total_gain_db,
                target,
            )
            break

    right = None
    for i in range(max_i, len(at_300) - 1):
        if at_300[i].total_gain_db >= target >= at_300[i + 1].total_gain_db:
            right = interpolate_crossing(
                at_300[i].theta_deg,
                at_300[i].total_gain_db,
                at_300[i + 1].theta_deg,
                at_300[i + 1].total_gain_db,
                target,
            )
            break

    if left is None or right is None:
        raise RuntimeError("Could not find both -3 dB HPBW crossings")
    return left, right, right - left


def run_sweep(
    name: str,
    *,
    length_m: float,
    diameter_m: float,
    start_mhz: float = 250.0,
    count: int = 101,
    step_mhz: float = 1.0,
    rp_card: str | None = "RP 0 1 1 1000 90 0 0 0",
) -> tuple[list[SweepPoint], list[PatternPoint], Path, Path]:
    inp = RUNS / f"{name}.inp"
    out = RUNS / f"{name}.out"
    write_nec(
        inp,
        title=name,
        length_m=length_m,
        diameter_m=diameter_m,
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
    return {
        "resonant_frequency_mhz": resonant.frequency_mhz,
        "minimum_s11_db": resonant.s11_db,
        "resonant_resistance_ohm": resonant.resistance_ohm,
        "resonant_reactance_ohm": resonant.reactance_ohm,
        "f_l_10db_mhz": f_l,
        "f_h_10db_mhz": f_h,
        "bandwidth_10db_mhz": bw,
        "fractional_bandwidth_percent": fractional,
        "peak_realized_gain_dbi": None if peak_gain is None else peak_gain.realized_gain_db,
        "peak_realized_gain_frequency_mhz": None if peak_gain is None else peak_gain.frequency_mhz,
    }


def fmt(value: float | None, places: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{places}f}"


def main() -> None:
    if not NEC2_EXE.exists():
        raise FileNotFoundError(f"NEC2 executable not found: {NEC2_EXE}")
    RUNS.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    length_candidates = [0.46, 0.47, 0.48, 0.49, 0.50]
    tuning_rows: list[dict[str, object]] = []
    coarse_results: list[tuple[float, dict[str, float | None]]] = []
    for length in length_candidates:
        points, _, _, _ = run_sweep(
            f"dipole_len_{length:.3f}m".replace(".", "p"),
            length_m=length,
            diameter_m=DIAMETER_M,
            rp_card=None,
        )
        summary = summarize_sweep(points)
        coarse_results.append((length, summary))
        tuning_rows.append({"length_m": length, **summary})

    best_coarse_length = min(
        coarse_results, key=lambda item: abs((item[1]["resonant_frequency_mhz"] or 0) - 300.0)
    )[0]
    fine_start = max(0.43, best_coarse_length - 0.010)
    fine_lengths = [round(fine_start + i * 0.001, 3) for i in range(21)]
    fine_results: list[tuple[float, dict[str, float | None]]] = []
    for length in fine_lengths:
        points, _, _, _ = run_sweep(
            f"dipole_fine_len_{length:.3f}m".replace(".", "p"),
            length_m=length,
            diameter_m=DIAMETER_M,
            rp_card=None,
        )
        summary = summarize_sweep(points)
        fine_results.append((length, summary))
        tuning_rows.append({"length_m": length, **summary})

    final_length = min(
        fine_results, key=lambda item: abs((item[1]["resonant_frequency_mhz"] or 0) - 300.0)
    )[0]

    final_points, final_gain_patterns, _, _ = run_sweep(
        "dipole_final_sweep",
        length_m=final_length,
        diameter_m=DIAMETER_M,
        rp_card="RP 0 1 1 1000 90 0 0 0",
    )
    final_summary = summarize_sweep(final_points)

    _, elevation_patterns, _, _ = run_sweep(
        "dipole_pattern_300mhz_elevation",
        length_m=final_length,
        diameter_m=DIAMETER_M,
        start_mhz=300.0,
        count=1,
        step_mhz=0.0,
        rp_card="RP 0 181 1 1000 0 0 1 0",
    )
    hp_left, hp_right, hp_width = hpbw(elevation_patterns)
    final_summary["hpbw_left_deg"] = hp_left
    final_summary["hpbw_right_deg"] = hp_right
    final_summary["hpbw_deg"] = hp_width

    thickness_rows: list[dict[str, object]] = []
    for diameter_mm in [4, 6, 8, 10, 12]:
        diameter = diameter_mm / 1000.0
        points, _, _, _ = run_sweep(
            f"dipole_thickness_{diameter_mm:02d}mm",
            length_m=final_length,
            diameter_m=diameter,
            rp_card="RP 0 1 1 1000 90 0 0 0",
        )
        thickness_rows.append(
            {
                "diameter_mm": diameter_mm,
                "length_m": final_length,
                **summarize_sweep(points),
            }
        )

    write_nec(
        PART1 / "dipole_final.nec",
        title="NIE2226 Part 1 final tuned dipole",
        length_m=final_length,
        diameter_m=DIAMETER_M,
        rp_card="RP 0 1 1 1000 90 0 0 0",
    )

    tuning_fields = [
        "length_m",
        "resonant_frequency_mhz",
        "minimum_s11_db",
        "resonant_resistance_ohm",
        "resonant_reactance_ohm",
        "f_l_10db_mhz",
        "f_h_10db_mhz",
        "bandwidth_10db_mhz",
        "fractional_bandwidth_percent",
        "peak_realized_gain_dbi",
        "peak_realized_gain_frequency_mhz",
    ]
    write_csv(
        DATA / "dipole_length_tuning.csv",
        tuning_rows,
        tuning_fields,
    )

    s11_fields = ["frequency_mhz", "resistance_ohm", "reactance_ohm", "s11_db_50ohm"]
    write_csv(
        DATA / "dipole_s11.csv",
        [
            {
                "frequency_mhz": p.frequency_mhz,
                "resistance_ohm": p.resistance_ohm,
                "reactance_ohm": p.reactance_ohm,
                "s11_db_50ohm": p.s11_db,
            }
            for p in final_points
        ],
        s11_fields,
    )

    gain_fields = ["frequency_mhz", "gain_dbi", "realized_gain_dbi_50ohm"]
    write_csv(
        DATA / "dipole_gain.csv",
        [
            {
                "frequency_mhz": p.frequency_mhz,
                "gain_dbi": p.gain_db,
                "realized_gain_dbi_50ohm": p.realized_gain_db,
            }
            for p in final_points
        ],
        gain_fields,
    )

    pattern_fields = ["theta_deg", "phi_deg", "gain_dbi", "realized_gain_dbi_50ohm"]
    write_csv(
        DATA / "dipole_pattern_300MHz.csv",
        [
            {
                "theta_deg": p.theta_deg,
                "phi_deg": p.phi_deg,
                "gain_dbi": p.total_gain_db,
                "realized_gain_dbi_50ohm": p.realized_gain_db,
            }
            for p in elevation_patterns
        ],
        pattern_fields,
    )

    thickness_fields = [
        "diameter_mm",
        "length_m",
        "resonant_frequency_mhz",
        "minimum_s11_db",
        "resonant_resistance_ohm",
        "resonant_reactance_ohm",
        "f_l_10db_mhz",
        "f_h_10db_mhz",
        "bandwidth_10db_mhz",
        "fractional_bandwidth_percent",
        "peak_realized_gain_dbi",
        "peak_realized_gain_frequency_mhz",
    ]
    write_csv(
        DATA / "dipole_thickness_sweep.csv",
        thickness_rows,
        thickness_fields,
    )
    write_simple_xlsx(
        PART1 / "dipole_thickness_sweep.xlsx",
        "thickness_sweep",
        thickness_rows,
        thickness_fields,
    )

    for filename in [
        "dipole_s11.csv",
        "dipole_gain.csv",
        "dipole_pattern_300MHz.csv",
        "dipole_length_tuning.csv",
        "dipole_thickness_sweep.csv",
    ]:
        shutil.copyfile(DATA / filename, PART1 / filename)

    summary_lines = [
        "NIE2226 Part 1 dipole NEC2 summary",
        "====================================",
        f"Final tuned total length: {final_length:.3f} m",
        f"Diameter: {DIAMETER_M:.3f} m",
        f"Segments: {SEGMENTS}",
        f"Reference impedance for S11/realized gain: {Z0:.1f} ohm",
        "",
        f"Resonant frequency by minimum S11: {fmt(final_summary['resonant_frequency_mhz'])} MHz",
        f"Minimum S11: {fmt(final_summary['minimum_s11_db'])} dB",
        f"Input impedance at S11 minimum: {fmt(final_summary['resonant_resistance_ohm'])} + j{fmt(final_summary['resonant_reactance_ohm'])} ohm",
        f"-10 dB lower frequency: {fmt(final_summary['f_l_10db_mhz'])} MHz",
        f"-10 dB upper frequency: {fmt(final_summary['f_h_10db_mhz'])} MHz",
        f"-10 dB bandwidth: {fmt(final_summary['bandwidth_10db_mhz'])} MHz",
        f"Fractional bandwidth: {fmt(final_summary['fractional_bandwidth_percent'])} %",
        f"Peak realized gain: {fmt(final_summary['peak_realized_gain_dbi'])} dBi at {fmt(final_summary['peak_realized_gain_frequency_mhz'])} MHz",
        f"HPBW at 300 MHz: {fmt(final_summary['hpbw_deg'])} deg ({fmt(final_summary['hpbw_left_deg'])} deg to {fmt(final_summary['hpbw_right_deg'])} deg)",
        "",
        "Generated files:",
        "  Part1/dipole_final.nec",
        "  Part1/data/dipole_s11.csv",
        "  Part1/data/dipole_gain.csv",
        "  Part1/data/dipole_pattern_300MHz.csv",
        "  Part1/data/dipole_length_tuning.csv",
        "  Part1/data/dipole_thickness_sweep.csv",
    ]
    (DATA / "dipole_summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    print("\n".join(summary_lines))


if __name__ == "__main__":
    main()
