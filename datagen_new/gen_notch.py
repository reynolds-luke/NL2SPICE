from dataclasses import dataclass
import json
import math
import random
from pathlib import Path
from tqdm import tqdm
import multiprocessing as mp
from multiprocessing import Pool

from typing import Dict
from utils.find_cutoffs import find_notch_cutoff_frequencies
from utils.measure_atten import simulate_attenuation

from prompt_templates.notch_templates import TEMPLATES


# ---------------------------------------------------------------------------
# Netlist builders
# ---------------------------------------------------------------------------

def _twin_t_stages(n: int, R: str, C: str, first_node: str = "VIN", stage_prefix: str = "A") -> tuple[str, str]:
    """
    Build n cascaded Twin-T notch sections.

    Each Twin-T uses:
      - Two series resistors R and a shunt capacitor 2C  (low-freq path)
      - Two series capacitors C and a shunt resistor R/2 (high-freq path)

    The two 'R' shunt components are approximated as R/2 via two R in parallel,
    and '2C' as two C in parallel — both expressed as literal SPICE values so
    the caller can pass standard E-series strings.

    Nodes are named  NT{prefix}{stage}A/B/MID/OUT so multiple stages don't clash.
    """
    lines = []
    prev_out = first_node

    for i in range(1, n + 1):
        p   = f"{stage_prefix}{i}"
        na  = f"NT{p}A"
        nb  = f"NT{p}B"
        out = f"NT{p}OUT"

        # --- Resistive (low-pass) arm: R → R → out, shunt 2C to ground ---
        lines.append(f"* Twin-T stage {i} — resistive arm")
        lines.append(f"RT{p}1  {prev_out:<8} {na:<8} {R}")
        lines.append(f"RT{p}2  {na:<8} {out:<8} {R}")
        # 2C shunt: two capacitors in parallel between na-midpoint and ground.
        lines.append(f"CT{p}S1 {na:<8} 0        {C}")
        lines.append(f"CT{p}S2 {na:<8} 0        {C}")

        # --- Capacitive (high-pass) arm: C → C → out, shunt R/2 to ground ---
        lines.append(f"* Twin-T stage {i} — capacitive arm")
        lines.append(f"CT{p}1  {prev_out:<8} {nb:<8} {C}")
        lines.append(f"CT{p}2  {nb:<8} {out:<8} {C}")
        # R/2 shunt: two resistors in parallel between nb-midpoint and ground.
        lines.append(f"RT{p}S1 {nb:<8} 0        {R}")
        lines.append(f"RT{p}S2 {nb:<8} 0        {R}")

        prev_out = out

    return "\n".join(lines), prev_out


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

@dataclass
class NotchNetlistTemplate:
    name: str
    buffered: bool = False

    def render(self, R: str, C: str, stages: int = 1) -> str:
        if stages > 1:
            kind   = "buffered " if self.buffered else ""
            header = f"* {stages}-stage passive RC notch filter {kind}(Twin-T)"
        else:
            suffix = " with input op-amp buffer" if self.buffered else ""
            header = f"* Single-stage passive RC notch filter (Twin-T){suffix}"

        input_buf = (
            "\n* Input buffer (ideal unity-gain voltage follower)\n"
            "EBUF VBUF  0     VIN 0  1\n"
        ) if self.buffered else ""

        first_node = "VBUF" if self.buffered else "VIN"

        if stages > 1 and self.buffered:
            stage1_lines, stage1_out = _twin_t_stages(1, R, C, first_node=first_node, stage_prefix="A")
            mid_buf = (
                f"\n* Mid buffer to isolate stage 1 from stage 2\n"
                f"EMID NMID  0     {stage1_out} 0  1\n"
            )
            stage2_lines, stage2_out = _twin_t_stages(1, R, C, first_node="NMID", stage_prefix="B")
            twin_t_section = (
                f"{stage1_lines}\n"
                f"{mid_buf}\n"
                f"* Stage 2\n"
                f"{stage2_lines}\n"
                f"EOUT VOUT  0     {stage2_out} 0  1\n"
            )
        else:
            twin_t_lines, last_node = _twin_t_stages(stages, R, C, first_node=first_node)
            twin_t_section = (
                f"{twin_t_lines}\n"
                f"EOUT VOUT  0     {last_node} 0  1\n"
            )

        return (
            f"{header}\n"
            f"V1   VIN   0     AC 1\n"
            f"{input_buf}\n"
            f"* Twin-T notch section(s)\n"
            f"{twin_t_section}"
        )


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------

class NotchNetlistLibrary:
    def __init__(self):
        self._t: Dict[str, NotchNetlistTemplate] = {}

    def register(self, key: str, **kwargs):
        self._t[key] = NotchNetlistTemplate(name=key, **kwargs)

    def render(self, key: str, **params) -> str:
        if key not in self._t:
            raise KeyError(f"Unknown template: {key!r}")
        return self._t[key].render(**params)


def build_library() -> NotchNetlistLibrary:
    lib = NotchNetlistLibrary()
    lib.register("rc_single")
    lib.register("buffered_rc_single", buffered=True)
    lib.register("rc_multi")
    lib.register("buffered_rc_multi",  buffered=True)
    return lib


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

R_MIN, R_MAX = 1e3,  100e3
C_MIN, C_MAX = 1e-9, 100e-9

# Minimum separation (in decades) between passband sample points and notch centre.
MIN_PASSBAND_OFFSET_DECADES = 0.5

SPICE_SUFFIXES = [
    (1e-12, "p"),
    (1e-9,  "n"),
    (1e-6,  "u"),
    (1e-3,  "m"),
    (1e3,   "k"),
    (1e6,   "meg"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_spice(value: float) -> str:
    for threshold, suffix in reversed(SPICE_SUFFIXES):
        if value >= threshold:
            scaled = value / threshold
            return f"{float(f'{scaled:.3g}')}{suffix}"
    return f"{value:.3g}"


def _sample_rc() -> tuple[str, str]:
    R = 10 ** random.uniform(math.log10(R_MIN), math.log10(R_MAX))
    C = 10 ** random.uniform(math.log10(C_MIN), math.log10(C_MAX))
    return _to_spice(R), _to_spice(C)


def _parse_spice(s: str) -> float:
    s = s.lower()
    for suffix, exp in [("meg", 1e6), ("k", 1e3), ("m", 1e-3),
                        ("u", 1e-6), ("n", 1e-9), ("p", 1e-12)]:
        if s.endswith(suffix):
            return float(s[:-len(suffix)]) * exp
    return float(s)


def _add_leeway(pb_db: float, atten_db: float, leeway_db: float = 1.0) -> tuple[float, float]:
    pb    = abs(pb_db)    + leeway_db
    atten = abs(atten_db) - leeway_db
    return round(pb, 1), round(atten, 1)


def _hz_label(f: float) -> str:
    if f >= 1e6:
        return f"{f/1e6:.3g} MHz"
    if f >= 1e3:
        return f"{f/1e3:.3g} kHz"
    return f"{f:.3g} Hz"


# ---------------------------------------------------------------------------
# Dataset generation
# ---------------------------------------------------------------------------

SINGLE_STAGE_TOPOLOGIES = {"rc_single", "buffered_rc_single"}
MULTI_STAGE_TOPOLOGIES  = {"rc_multi",  "buffered_rc_multi"}


# ---------------------------------------------------------------------------
# Worker initializer
# ---------------------------------------------------------------------------

_worker_lib: NotchNetlistLibrary = None

def _worker_init():
    global _worker_lib
    random.seed()
    _worker_lib = build_library()


# ---------------------------------------------------------------------------
# Single-sample worker
# ---------------------------------------------------------------------------

def _generate_one(args: tuple) -> dict | None:
    topology, prompt_templates = args

    stages = 1 if topology in SINGLE_STAGE_TOPOLOGIES else 2

    R, C = _sample_rc()

    netlist = _worker_lib.render(topology, R=R, C=C, stages=stages)

    result = find_notch_cutoff_frequencies(netlist)
    if result is None or result[0] is None:
        return None

    (f_low_hz, f_high_hz), _ = result

    # Notch centre (geometric mean of the two -3 dB points)
    f_notch_hz = math.sqrt(f_low_hz * f_high_hz)

    # --- Passband sample points: well outside the notch on each side ---
    f_pass_low_hz  = f_low_hz  / (10 ** random.uniform(MIN_PASSBAND_OFFSET_DECADES,
                                                        MIN_PASSBAND_OFFSET_DECADES + 2))
    f_pass_high_hz = f_high_hz * (10 ** random.uniform(MIN_PASSBAND_OFFSET_DECADES,
                                                        MIN_PASSBAND_OFFSET_DECADES + 2))

    # --- Stopband sample point: inside the notch, near the centre ---
    log_low   = math.log10(f_low_hz)
    log_high  = math.log10(f_high_hz)
    f_stop_hz = 10 ** random.uniform(log_low, log_high)

    db_pass_low  = simulate_attenuation(netlist, f_pass_low_hz)
    db_pass_high = simulate_attenuation(netlist, f_pass_high_hz)
    db_stop      = simulate_attenuation(netlist, f_stop_hz)

    if any(v is None for v in (db_pass_low, db_pass_high, db_stop)):
        return None

    # Worst passband figure = lowest gain (most attenuation) across both sides
    db_pass_worst = min(db_pass_low, db_pass_high)
    pb, atten     = _add_leeway(db_pass_worst, db_stop)

    # Prompt passband/stopband edge labels — nudge slightly inward for realism
    f_pass_low_prompt  = f_low_hz  / (10 ** random.uniform(0, 0.5))
    f_pass_high_prompt = f_high_hz * (10 ** random.uniform(0, 0.5))

    # fc_low/fc_high are the notch (stopband) edges in the prompt
    # fs_low/fs_high are the passband reference frequencies in the prompt
    template_str = random.choice(prompt_templates)
    prompt = template_str.format(
        fc_low  = _hz_label(f_low_hz),
        fc_high = _hz_label(f_high_hz),
        fs_low  = _hz_label(f_pass_low_prompt),
        fs_high = _hz_label(f_pass_high_prompt),
        pb      = pb,
        atten   = atten,
    )

    return {
        "prompt":           prompt,
        "netlist":          netlist,
        "topology":         topology,
        "stages":           stages,
        "R":                R,
        "C":                C,
        "f_notch_hz":       f_notch_hz,
        "f_low_hz":         f_low_hz,
        "f_high_hz":        f_high_hz,
        "f_pass_low_hz":    f_pass_low_hz,
        "f_pass_high_hz":   f_pass_high_hz,
        "f_stop_hz":        f_stop_hz,
        "db_pass_low":      db_pass_low,
        "db_pass_high":     db_pass_high,
        "db_stop":          db_stop,
        "pb_spec_db":       pb,
        "atten_spec_db":    atten,
        "task":             "notch",
    }


def create_prompts(
    n_per_type: int,
    output_path: str = "./prompts/notch_dataset.json",
    num_workers: int | None = None,
) -> list[dict]:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    oversample = max(1, int(n_per_type * 1.2))
    jobs: list[tuple] = [
        (topology, prompt_templates)
        for topology, prompt_templates in TEMPLATES.items()
        for _ in range(oversample)
    ]

    n_workers = min(num_workers or mp.cpu_count(), 16)
    total     = len(jobs)

    records: dict[str, list[dict]] = {t: [] for t in TEMPLATES}

    with Pool(
        processes=n_workers,
        initializer=_worker_init,
    ) as pool:
        with tqdm(total=total, desc=f"Generating prompts ({n_workers} workers)") as pbar:
            for record in pool.imap_unordered(_generate_one, jobs, chunksize=1):
                pbar.update(1)
                if record is not None:
                    topology = record["topology"]
                    if len(records[topology]) < n_per_type:
                        records[topology].append(record)
                        pbar.set_postfix(
                            {t: len(v) for t, v in records.items()}
                        )

    flat_records = [r for recs in records.values() for r in recs]

    with open(output_path, "w") as f:
        json.dump(flat_records, f, indent=2)

    print(f"Wrote {len(flat_records)} records to {output_path}")
    return flat_records


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--n-per-type",  type=int,  default=10)
    parser.add_argument("-o", "--output",      default="./prompts/notch_dataset.json")
    parser.add_argument("-w", "--num-workers", type=int,  default=None,
                        help="Worker processes (default: all CPU cores)")
    args = parser.parse_args()
    create_prompts(args.n_per_type, args.output, args.num_workers)