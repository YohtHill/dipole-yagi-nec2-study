from __future__ import annotations

import math
import shutil
from dataclasses import dataclass
from pathlib import Path

import part2_yagi_2el as nec


ROOT = Path(__file__).resolve().parents[1]
PART3 = ROOT / "Part3"
RUNS = PART3 / "nec_runs"
DATA = PART3 / "data"

DRIVEN_LENGTH_M = 0.457
REFLECTOR_LENGTH_M = 0.460
REFLECTOR_SPACING_M = 0.200
DIAMETER_M = 0.008
RADIUS_M = DIAMETER_M / 2
SEGMENTS = 15
SOURCE_SEGMENT = (SEGMENTS + 1) // 2
MATCHING_LIMIT_DB = -10.0


@dataclass(frozen=True)
class Director:
    name: str
    length_m: float
    spacing_from_previous_m: float


def write_yagi_nec(
    path: Path,
    *,
    title: str,
    directors: list[Director],
    start_mhz: float = 250.0,
    count: int = 101,
    step_mhz: float = 1.0,
    rp_card: str | None = "RP 0 1 1 1000 90 0 0 0",
) -> None:
    driven_half = DRIVEN_LENGTH_M / 2
    reflector_half = REFLECTOR_LENGTH_M / 2
    director_comments = []
    x = 0.0
    for director in directors:
        x += director.spacing_from_previous_m
        director_comments.append(
            f"CM {director.name}: length={director.length_m:.6f} m, x={x:.6f} m, spacing_from_previous={director.spacing_from_previous_m:.6f} m"
        )

    lines = [
        f"CM {title}",
        "CM Yagi-Uda antenna for NIE2226 Part 3",
        f"CM Driven length: {DRIVEN_LENGTH_M:.6f} m",
        f"CM Reflector length: {REFLECTOR_LENGTH_M:.6f} m",
        f"CM Reflector spacing behind driven element: {REFLECTOR_SPACING_M:.6f} m",
        f"CM Element diameter: {DIAMETER_M:.6f} m",
        "CM Vertical elements along z-axis; forward direction is +x",
        *director_comments,
        "CE",
        f"GW 1 {SEGMENTS} 0 0 {-driven_half:.6f} 0 0 {driven_half:.6f} {RADIUS_M:.6f}",
        f"GW 2 {SEGMENTS} {-REFLECTOR_SPACING_M:.6f} 0 {-reflector_half:.6f} {-REFLECTOR_SPACING_M:.6f} 0 {reflector_half:.6f} {RADIUS_M:.6f}",
    ]
    x = 0.0
    for index, director in enumerate(directors, start=1):
        x += director.spacing_from_previous_m
        half = director.length_m / 2
        tag = index + 2
        lines.append(
            f"GW {tag} {SEGMENTS} {x:.6f} 0 {-half:.6f} {x:.6f} 0 {half:.6f} {RADIUS_M:.6f}"
        )
    lines.extend(
        [
            "GE 0",
            f"EX 0 1 {SOURCE_SEGMENT} 0 1 0",
            f"FR 0 {count} 0 0 {start_mhz:g} {step_mhz:g}",
        ]
    )
    if rp_card:
        lines.append(rp_card)
    lines.extend(["XQ", "EN", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="ascii")


def run_sweep(
    name: str,
    *,
    directors: list[Director],
    start_mhz: float = 250.0,
    count: int = 101,
    step_mhz: float = 1.0,
    rp_card: str | None = "RP 0 1 1 1000 90 0 0 0",
) -> tuple[list[nec.SweepPoint], list[nec.PatternPoint], Path, Path]:
    inp = RUNS / f"{name}.inp"
    out = RUNS / f"{name}.out"
    write_yagi_nec(
        inp,
        title=name,
        directors=directors,
        start_mhz=start_mhz,
        count=count,
        step_mhz=step_mhz,
        rp_card=rp_card,
    )
    nec.run_nec(inp, out)
    sweep, patterns = nec.parse_output(out)
    return sweep, patterns, inp, out


def directors_from_lengths_spacings(lengths: list[float], spacings: list[float]) -> list[Director]:
    return [
        Director(name=f"D{index}", length_m=length, spacing_from_previous_m=spacing)
        for index, (length, spacing) in enumerate(zip(lengths, spacings), start=1)
    ]


def one_director(length: float, spacing: float) -> list[Director]:
    return [Director(name="D1", length_m=length, spacing_from_previous_m=spacing)]


def summary_row(
    *,
    directors: list[Director],
    points: list[nec.SweepPoint],
    fb_patterns: list[nec.PatternPoint] | None = None,
) -> dict[str, object]:
    summary = nec.summarize_sweep(points)
    row: dict[str, object] = {
        "num_directors": len(directors),
        "director_1_length_m": directors[0].length_m if directors else None,
        "director_1_spacing_m": directors[0].spacing_from_previous_m if directors else None,
        **summary,
    }
    if fb_patterns is not None:
        fb_rows = nec.front_back_rows(fb_patterns)
        row["front_back_ratio_at_300_db"] = nec.value_at_300(fb_rows, "front_back_ratio_db")
    return row


def length_sequence(start: float, end: float, count: int = 9) -> list[float]:
    if count == 1:
        return [start]
    return [start + (end - start) * i / (count - 1) for i in range(count)]


def candidate_director_sets(best_len: float, best_spacing: float) -> list[tuple[str, list[Director]]]:
    length_sets: list[tuple[str, list[float]]] = [
        ("uniform_best_len", [best_len] * 9),
        ("mild_taper_best_to_minus_024", length_sequence(best_len, max(0.34, best_len - 0.024))),
        ("medium_taper_best_to_minus_040", length_sequence(best_len, max(0.34, best_len - 0.040))),
        ("standard_400_to_360", length_sequence(0.400, 0.360)),
        ("standard_410_to_370", length_sequence(0.410, 0.370)),
        ("standard_420_to_380", length_sequence(0.420, 0.380)),
    ]
    spacing_sets: list[tuple[str, list[float]]] = [
        ("uniform_best_spacing", [best_spacing] * 9),
        ("uniform_200", [0.200] * 9),
        ("uniform_180", [0.180] * 9),
        ("uniform_220", [0.220] * 9),
        ("first_best_then_200", [best_spacing] + [0.200] * 8),
        ("first_150_then_200", [0.150] + [0.200] * 8),
        ("gradual_180_to_220", length_sequence(0.180, 0.220)),
    ]
    candidates: list[tuple[str, list[Director]]] = []
    for length_name, lengths in length_sets:
        for spacing_name, spacings in spacing_sets:
            name = f"{length_name}__{spacing_name}"
            candidates.append((name, directors_from_lengths_spacings(lengths, spacings)))
    return candidates


def write_directors_table(path_prefix: Path, directors: list[Director]) -> list[dict[str, object]]:
    rows = []
    x = 0.0
    for director in directors:
        x += director.spacing_from_previous_m
        rows.append(
            {
                "director": director.name,
                "length_m": director.length_m,
                "spacing_from_previous_m": director.spacing_from_previous_m,
                "x_position_m": x,
            }
        )
    fields = ["director", "length_m", "spacing_from_previous_m", "x_position_m"]
    nec.write_csv(path_prefix.with_suffix(".csv"), rows, fields)
    nec.write_simple_xlsx(path_prefix.with_suffix(".xlsx"), "directors", rows, fields)
    return rows


def copy_data_file(filename: str) -> None:
    shutil.copyfile(DATA / filename, PART3 / filename)


def fmt(value: float | None, places: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{places}f}"


def passes_matching(row: dict[str, object], limit_db: float = MATCHING_LIMIT_DB) -> bool:
    value = row.get("s11_at_300_db")
    return value is not None and float(value) <= limit_db


def realized_gain_score(row: dict[str, object]) -> float:
    value = row.get("realized_gain_at_300_dbi")
    return -999.0 if value is None else float(value)


def best_gain_with_matching(rows: list[dict[str, object]]) -> dict[str, object]:
    matched = [row for row in rows if passes_matching(row)]
    candidates = matched if matched else rows
    return max(candidates, key=realized_gain_score)


def main() -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    (PART3 / "plots").mkdir(parents=True, exist_ok=True)

    # Initial 3-element Yagi from assignment starting point.
    initial_3el = one_director(0.400, 0.200)
    write_yagi_nec(
        PART3 / "yagi_3el_initial.nec",
        title="NIE2226 Part 3 initial 3-element Yagi",
        directors=initial_3el,
        rp_card="RP 0 1 1 1000 90 0 0 0",
    )
    initial_points, _, _, _ = run_sweep(
        "yagi_3el_initial_front_gain",
        directors=initial_3el,
        rp_card="RP 0 1 1 1000 90 0 0 0",
    )
    initial_summary = nec.summarize_sweep(initial_points)

    # Director length sweep.
    length_rows: list[dict[str, object]] = []
    for length in [0.36, 0.38, 0.40, 0.42, 0.44]:
        dirs = one_director(length, 0.200)
        points, _, _, _ = run_sweep(
            f"director_length_{length:.2f}m".replace(".", "p"),
            directors=dirs,
            rp_card="RP 0 1 1 1000 90 0 0 0",
        )
        row = summary_row(directors=dirs, points=points)
        row["director_length_m"] = length
        row["director_spacing_m"] = 0.200
        length_rows.append(row)

    best_length_row = best_gain_with_matching(length_rows)
    best_dir_len = float(best_length_row["director_length_m"])

    # Director spacing sweep.
    spacing_rows: list[dict[str, object]] = []
    for spacing in [0.10, 0.15, 0.20, 0.25, 0.30]:
        dirs = one_director(best_dir_len, spacing)
        points, fb_patterns, _, _ = run_sweep(
            f"director_spacing_{spacing:.2f}m".replace(".", "p"),
            directors=dirs,
            rp_card="RP 0 1 2 1000 90 0 0 180",
        )
        row = summary_row(directors=dirs, points=points, fb_patterns=fb_patterns)
        row["director_length_m"] = best_dir_len
        row["director_spacing_m"] = spacing
        spacing_rows.append(row)

    best_spacing_row = best_gain_with_matching(spacing_rows)
    best_dir_spacing = float(best_spacing_row["director_spacing_m"])

    # Final optimized 3-element data.
    final_3el = one_director(best_dir_len, best_dir_spacing)
    write_yagi_nec(
        PART3 / "yagi_3el_final.nec",
        title="NIE2226 Part 3 final 3-element Yagi",
        directors=final_3el,
        rp_card="RP 0 1 1 1000 90 0 0 0",
    )
    final_3el_points, _, _, _ = run_sweep(
        "yagi_3el_final_front_gain",
        directors=final_3el,
        rp_card="RP 0 1 1 1000 90 0 0 0",
    )
    final_3el_summary = nec.summarize_sweep(final_3el_points)
    _, final_3el_fb_patterns, _, _ = run_sweep(
        "yagi_3el_final_fb",
        directors=final_3el,
        rp_card="RP 0 1 2 1000 90 0 0 180",
    )
    final_3el_fb_rows = nec.front_back_rows(final_3el_fb_patterns)
    _, final_3el_az_patterns, _, _ = run_sweep(
        "yagi_3el_pattern_300mhz_azimuth",
        directors=final_3el,
        start_mhz=300.0,
        count=1,
        step_mhz=0.0,
        rp_card="RP 0 1 361 1000 90 0 0 1",
    )
    _, final_3el_el_patterns, _, _ = run_sweep(
        "yagi_3el_pattern_300mhz_elevation",
        directors=final_3el,
        start_mhz=300.0,
        count=1,
        step_mhz=0.0,
        rp_card="RP 0 181 1 1000 0 0 1 0",
    )

    # Candidate 9-director search.
    candidate_rows: list[dict[str, object]] = []
    best_any_candidate_name = ""
    best_any_directors: list[Director] = []
    best_any_candidate_points: list[nec.SweepPoint] = []
    best_any_gain = -999.0
    best_matched_candidate_name = ""
    best_matched_directors: list[Director] = []
    best_matched_candidate_points: list[nec.SweepPoint] = []
    best_matched_gain = -999.0
    for name, dirs in candidate_director_sets(best_dir_len, best_dir_spacing):
        points, _, _, _ = run_sweep(
            f"yagi_9dir_candidate_{len(candidate_rows):02d}",
            directors=dirs,
            rp_card="RP 0 1 1 1000 90 0 0 0",
        )
        summary = nec.summarize_sweep(points)
        gain_300 = summary["realized_gain_at_300_dbi"]
        candidate_row = {
            "candidate": name,
            "first_director_length_m": dirs[0].length_m,
            "last_director_length_m": dirs[-1].length_m,
            "first_spacing_m": dirs[0].spacing_from_previous_m,
            "last_spacing_m": dirs[-1].spacing_from_previous_m,
            **summary,
        }
        candidate_rows.append(candidate_row)
        score = -999.0 if gain_300 is None else float(gain_300)
        if score > best_any_gain:
            best_any_gain = score
            best_any_candidate_name = name
            best_any_directors = dirs
            best_any_candidate_points = points
        if passes_matching(candidate_row) and score > best_matched_gain:
            best_matched_gain = score
            best_matched_candidate_name = name
            best_matched_directors = dirs
            best_matched_candidate_points = points

    if best_matched_directors:
        best_candidate_name = best_matched_candidate_name
        best_directors = best_matched_directors
        best_candidate_points = best_matched_candidate_points
    else:
        best_candidate_name = best_any_candidate_name
        best_directors = best_any_directors
        best_candidate_points = best_any_candidate_points

    write_yagi_nec(
        PART3 / "yagi_9dir_best.nec",
        title=f"NIE2226 Part 3 best 9-director Yagi - {best_candidate_name}",
        directors=best_directors,
        rp_card="RP 0 1 1 1000 90 0 0 0",
    )

    # Final 9-director full outputs.
    best_9_summary = nec.summarize_sweep(best_candidate_points)
    _, best_9_fb_patterns, _, _ = run_sweep(
        "yagi_9dir_best_fb",
        directors=best_directors,
        rp_card="RP 0 1 2 1000 90 0 0 180",
    )
    best_9_fb_rows = nec.front_back_rows(best_9_fb_patterns)
    _, best_9_az_patterns, _, _ = run_sweep(
        "yagi_9dir_pattern_300mhz_azimuth",
        directors=best_directors,
        start_mhz=300.0,
        count=1,
        step_mhz=0.0,
        rp_card="RP 0 1 361 1000 90 0 0 1",
    )
    _, best_9_el_patterns, _, _ = run_sweep(
        "yagi_9dir_pattern_300mhz_elevation",
        directors=best_directors,
        start_mhz=300.0,
        count=1,
        step_mhz=0.0,
        rp_card="RP 0 181 1 1000 0 0 1 0",
    )

    # CSV and xlsx outputs.
    sweep_fields = [
        "num_directors",
        "director_1_length_m",
        "director_1_spacing_m",
        "director_length_m",
        "director_spacing_m",
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
    # Add missing F/B column to length rows.
    for row in length_rows:
        row.setdefault("front_back_ratio_at_300_db", None)
    nec.write_csv(DATA / "director_length_sweep.csv", length_rows, sweep_fields)
    nec.write_csv(DATA / "director_spacing_sweep.csv", spacing_rows, sweep_fields)
    nec.write_simple_xlsx(PART3 / "director_length_sweep.xlsx", "director_length", length_rows, sweep_fields)
    nec.write_simple_xlsx(PART3 / "director_spacing_sweep.xlsx", "director_spacing", spacing_rows, sweep_fields)
    copy_data_file("director_length_sweep.csv")
    copy_data_file("director_spacing_sweep.csv")

    candidate_fields = [
        "candidate",
        "first_director_length_m",
        "last_director_length_m",
        "first_spacing_m",
        "last_spacing_m",
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
    nec.write_csv(DATA / "yagi_9dir_candidate_sweep.csv", candidate_rows, candidate_fields)
    copy_data_file("yagi_9dir_candidate_sweep.csv")

    s11_rows = [
        {
            "frequency_mhz": p.frequency_mhz,
            "resistance_ohm": p.resistance_ohm,
            "reactance_ohm": p.reactance_ohm,
            "s11_db_50ohm": p.s11_db,
        }
        for p in best_candidate_points
    ]
    gain_rows = [
        {
            "frequency_mhz": p.frequency_mhz,
            "forward_gain_dbi": p.gain_db,
            "forward_realized_gain_dbi_50ohm": p.realized_gain_db,
        }
        for p in best_candidate_points
    ]
    nec.write_csv(DATA / "yagi_9dir_s11.csv", s11_rows, list(s11_rows[0].keys()))
    nec.write_csv(DATA / "yagi_9dir_gain.csv", gain_rows, list(gain_rows[0].keys()))
    nec.write_csv(DATA / "yagi_9dir_fb.csv", best_9_fb_rows, list(best_9_fb_rows[0].keys()))
    nec.write_csv(
        DATA / "yagi_9dir_pattern_azimuth_300MHz.csv",
        nec.pattern_rows(best_9_az_patterns),
        ["frequency_mhz", "theta_deg", "phi_deg", "gain_dbi", "realized_gain_dbi_50ohm"],
    )
    nec.write_csv(
        DATA / "yagi_9dir_pattern_elevation_300MHz.csv",
        nec.pattern_rows(best_9_el_patterns),
        ["frequency_mhz", "theta_deg", "phi_deg", "gain_dbi", "realized_gain_dbi_50ohm"],
    )
    for filename in [
        "yagi_9dir_s11.csv",
        "yagi_9dir_gain.csv",
        "yagi_9dir_fb.csv",
        "yagi_9dir_pattern_azimuth_300MHz.csv",
        "yagi_9dir_pattern_elevation_300MHz.csv",
    ]:
        copy_data_file(filename)

    director_rows = write_directors_table(PART3 / "directors_table", best_directors)
    shutil.copyfile(PART3 / "directors_table.csv", DATA / "directors_table.csv")

    # Also produce 3-element final data for comparison.
    final_3el_s11_rows = [
        {
            "frequency_mhz": p.frequency_mhz,
            "resistance_ohm": p.resistance_ohm,
            "reactance_ohm": p.reactance_ohm,
            "s11_db_50ohm": p.s11_db,
        }
        for p in final_3el_points
    ]
    final_3el_gain_rows = [
        {
            "frequency_mhz": p.frequency_mhz,
            "forward_gain_dbi": p.gain_db,
            "forward_realized_gain_dbi_50ohm": p.realized_gain_db,
        }
        for p in final_3el_points
    ]
    final_3el_combined_rows = [
        {
            "frequency_mhz": p.frequency_mhz,
            "resistance_ohm": p.resistance_ohm,
            "reactance_ohm": p.reactance_ohm,
            "s11_db_50ohm": p.s11_db,
            "forward_realized_gain_dbi_50ohm": p.realized_gain_db,
        }
        for p in final_3el_points
    ]
    nec.write_csv(DATA / "yagi_3el_s11.csv", final_3el_s11_rows, list(final_3el_s11_rows[0].keys()))
    nec.write_csv(DATA / "yagi_3el_gain.csv", final_3el_gain_rows, list(final_3el_gain_rows[0].keys()))
    nec.write_csv(DATA / "yagi_3el_fb.csv", final_3el_fb_rows, list(final_3el_fb_rows[0].keys()))
    nec.write_csv(
        DATA / "yagi_3el_pattern_azimuth_300MHz.csv",
        nec.pattern_rows(final_3el_az_patterns),
        ["frequency_mhz", "theta_deg", "phi_deg", "gain_dbi", "realized_gain_dbi_50ohm"],
    )
    nec.write_csv(
        DATA / "yagi_3el_pattern_elevation_300MHz.csv",
        nec.pattern_rows(final_3el_el_patterns),
        ["frequency_mhz", "theta_deg", "phi_deg", "gain_dbi", "realized_gain_dbi_50ohm"],
    )
    nec.write_csv(DATA / "yagi_3el_sweep.csv", final_3el_combined_rows, list(final_3el_combined_rows[0].keys()))
    for filename in [
        "yagi_3el_s11.csv",
        "yagi_3el_gain.csv",
        "yagi_3el_fb.csv",
        "yagi_3el_pattern_azimuth_300MHz.csv",
        "yagi_3el_pattern_elevation_300MHz.csv",
        "yagi_3el_sweep.csv",
    ]:
        copy_data_file(filename)

    fb_9_300 = nec.value_at_300(best_9_fb_rows, "front_back_ratio_db")
    fb_3el_300 = nec.value_at_300(final_3el_fb_rows, "front_back_ratio_db")
    dipole_gain = 1.989
    yagi2_gain = 6.372
    gain_3el = final_3el_summary["realized_gain_at_300_dbi"]
    gain_9dir = best_9_summary["realized_gain_at_300_dbi"]

    summary_lines = [
        "NIE2226 Part 3 director Yagi-Uda NEC2 summary",
        "===============================================",
        f"Driven length: {DRIVEN_LENGTH_M:.3f} m",
        f"Reflector length: {REFLECTOR_LENGTH_M:.3f} m",
        f"Reflector spacing: {REFLECTOR_SPACING_M:.3f} m",
        f"Element diameter: {DIAMETER_M:.3f} m",
        "",
        "Initial 3-element Yagi:",
        "  Director length: 0.400 m",
        "  Director spacing: 0.200 m",
        f"  Realized gain at 300 MHz: {fmt(initial_summary['realized_gain_at_300_dbi'])} dBi",
        f"  S11 at 300 MHz: {fmt(initial_summary['s11_at_300_db'])} dB",
        "",
        "Final 3-element Yagi from sweeps:",
        f"  Selection rule: highest 300 MHz realized gain with S11 <= {MATCHING_LIMIT_DB:.0f} dB",
        f"  Director length: {best_dir_len:.3f} m",
        f"  Director spacing: {best_dir_spacing:.3f} m",
        f"  Realized gain at 300 MHz: {fmt(gain_3el)} dBi",
        f"  Peak realized gain: {fmt(final_3el_summary['peak_realized_gain_dbi'])} dBi at {fmt(final_3el_summary['peak_realized_gain_frequency_mhz'])} MHz",
        f"  S11 at 300 MHz: {fmt(final_3el_summary['s11_at_300_db'])} dB",
        f"  Front-to-back ratio at 300 MHz: {fmt(fb_3el_300)} dB",
        "",
        "Best 9-director candidate:",
        f"  Selection rule: highest 300 MHz realized gain with S11 <= {MATCHING_LIMIT_DB:.0f} dB",
        f"  Candidate name: {best_candidate_name}",
        f"  Realized gain at 300 MHz: {fmt(gain_9dir)} dBi",
        f"  Peak realized gain: {fmt(best_9_summary['peak_realized_gain_dbi'])} dBi at {fmt(best_9_summary['peak_realized_gain_frequency_mhz'])} MHz",
        f"  S11 at 300 MHz: {fmt(best_9_summary['s11_at_300_db'])} dB",
        f"  Minimum S11: {fmt(best_9_summary['minimum_s11_db'])} dB at {fmt(best_9_summary['resonant_frequency_mhz'])} MHz",
        f"  Front-to-back ratio at 300 MHz: {fmt(fb_9_300)} dB",
        f"  -10 dB bandwidth: {fmt(best_9_summary['bandwidth_10db_mhz'])} MHz",
        f"  Fractional bandwidth: {fmt(best_9_summary['fractional_bandwidth_percent'])} %",
        "",
        "Gain comparisons at 300 MHz:",
        f"  3-element vs dipole: {fmt(None if gain_3el is None else gain_3el - dipole_gain)} dB",
        f"  3-element vs 2-element Yagi: {fmt(None if gain_3el is None else gain_3el - yagi2_gain)} dB",
        f"  9-director vs dipole: {fmt(None if gain_9dir is None else gain_9dir - dipole_gain)} dB",
        f"  9-director vs 2-element Yagi: {fmt(None if gain_9dir is None else gain_9dir - yagi2_gain)} dB",
        f"  9-director vs 3-element Yagi: {fmt(None if gain_9dir is None or gain_3el is None else gain_9dir - gain_3el)} dB",
        "",
        "Generated files:",
        "  Part3/yagi_3el_initial.nec",
        "  Part3/yagi_3el_final.nec",
        "  Part3/yagi_9dir_best.nec",
        "  Part3/director_length_sweep.xlsx",
        "  Part3/director_spacing_sweep.xlsx",
        "  Part3/directors_table.xlsx",
        "  Part3/yagi_9dir_s11.csv",
        "  Part3/yagi_9dir_gain.csv",
        "  Part3/yagi_9dir_fb.csv",
    ]
    (DATA / "part3_summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    (PART3 / "part3_summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print("\n".join(summary_lines))


if __name__ == "__main__":
    main()
