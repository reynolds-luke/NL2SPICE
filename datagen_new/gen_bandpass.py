from dataclasses import dataclass
import json
import math
import random
from pathlib import Path
from tqdm import tqdm
import multiprocessing as mp
from multiprocessing import Pool

from typing import Dict
from utils.find_cutoffs import find_bandpass_cutoff_frequencies
from utils.measure_atten import simulate_attenuation

from prompt_templates.band_pass_templates import TEMPLATES


# ---------------------------------------------------------------------------
# Netlist builders
# ---------------------------------------------------------------------------

def _hp_rc_stages(n: int, R: str, C: str, first_node: str = "VIN") -> tuple[str, str]:
    lines = []
    for i in range(1, n + 1):
        in_node  = first_node if i == 1 else f"NH{i-1}"
        out_node = f"NH{i}"
        lines.append(f"CH{i}  {in_node:<6} {out_node:<6} {C}")
        lines.append(f"RH{i}  {out_node:<6} 0      {R}")
    return "\n".join(lines), f"NH{n}"


def _lp_rc_stages(n: int, R: str, C: str, first_node: str, last_node: str = "VOUT") -> str:
    lines = []
    for i in range(1, n + 1):
        in_node  = first_node if i == 1 else f"NL{i-1}"
        out_node = last_node  if i == n else f"NL{i}"
        lines.append(f"RL{i}  {in_node:<6} {out_node:<6} {R}")
        lines.append(f"CL{i}  {out_node:<6} 0      {C}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

@dataclass
class BandpassNetlistTemplate:
    name: str
    buffered: bool = False

    def render(self, R_hp: str, C_hp: str, R_lp: str, C_lp: str, stages: int = 1) -> str:
        if stages > 1:
            kind   = "buffered " if self.buffered else ""
            header = f"* {stages}-stage passive RC band-pass filter {kind}(input op-amp buffer)"
        else:
            suffix = " with input op-amp buffer" if self.buffered else ""
            header = f"* Single-stage passive RC band-pass filter{suffix}"

        input_buf = (
            "\n* Input buffer (ideal unity-gain voltage follower)\n"
            "EBUF VBUF  0     VIN 0  1\n"
        ) if self.buffered else ""

        first_hp_node = "VBUF" if self.buffered else "VIN"

        hp_lines, last_hp_node = _hp_rc_stages(stages, R_hp, C_hp, first_node=first_hp_node)

        if self.buffered:
            mid_buf       = (
                f"\n* Mid buffer to isolate HP from LP\n"
                f"EMID NMID  0     {last_hp_node} 0  1\n"
            )
            first_lp_node = "NMID"
        else:
            mid_buf       = ""
            first_lp_node = last_hp_node

        lp_lines = _lp_rc_stages(stages, R_lp, C_lp, first_node=first_lp_node)

        return (
            f"{header}\n"
            f"V1   VIN   0     AC 1\n"
            f"{input_buf}\n"
            f"* High-pass section (sets lower cutoff)\n"
            f"{hp_lines}\n"
            f"{mid_buf}\n"
            f"* Low-pass section (sets upper cutoff)\n"
            f"{lp_lines}\n"
        )


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------

class BandpassNetlistLibrary:
    def __init__(self):
        self._t: Dict[str, BandpassNetlistTemplate] = {}

    def register(self, key: str, **kwargs):
        self._t[key] = BandpassNetlistTemplate(name=key, **kwargs)

    def render(self, key: str, **params) -> str:
        if key not in self._t:
            raise KeyError(f"Unknown template: {key!r}")
        return self._t[key].render(**params)


def build_library() -> BandpassNetlistLibrary:
    lib = BandpassNetlistLibrary()
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

MIN_PASSBAND_DECADES = 0.5

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


def _sample_rc_pair() -> tuple[str, str, str, str]:
    for _ in range(100):
        R_hp, C_hp = _sample_rc()
        R_lp, C_lp = _sample_rc()

        f_hp = 1 / (2 * math.pi * _parse_spice(R_hp) * _parse_spice(C_hp))
        f_lp = 1 / (2 * math.pi * _parse_spice(R_lp) * _parse_spice(C_lp))

        if f_lp / f_hp >= 10 ** MIN_PASSBAND_DECADES:
            return R_hp, C_hp, R_lp, C_lp

    raise RuntimeError("Could not sample a valid HP/LP RC pair after 100 attempts")


def _add_leeway(fc_db: float, fs_db: float, leeway_db: float = 1.0) -> tuple[float, float]:
    pb    = abs(fc_db) + leeway_db
    atten = abs(fs_db) - leeway_db
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
# Worker initializer — each subprocess builds its own lib instance so there
# is no shared mutable state and no pickling of the library object itself.
# ---------------------------------------------------------------------------

_worker_lib: BandpassNetlistLibrary = None   # set per-process by initializer

def _worker_init():
    """Called once per worker process; seeds RNG independently and builds lib."""
    global _worker_lib
    # Each worker gets a unique seed so samples don't repeat across processes.
    random.seed()
    _worker_lib = build_library()


# ---------------------------------------------------------------------------
# Single-sample worker — receives (topology, prompt_templates) and returns
# one record dict, or None if the sample should be skipped.
# ---------------------------------------------------------------------------

def _generate_one(args: tuple) -> dict | None:
    topology, prompt_templates = args

    stages = 1 if topology in SINGLE_STAGE_TOPOLOGIES else 2

    try:
        R_hp, C_hp, R_lp, C_lp = _sample_rc_pair()
    except RuntimeError:
        return None

    netlist = _worker_lib.render(
        topology,
        R_hp=R_hp, C_hp=C_hp,
        R_lp=R_lp, C_lp=C_lp,
        stages=stages,
    )

    result = find_bandpass_cutoff_frequencies(netlist)
    if result is None or result[0] is None:
        return None

    (f_low_hz, f_high_hz), _ = result

    log_f_low  = math.log10(f_low_hz)
    log_f_high = math.log10(f_high_hz)
    f_pass_hz  = 10 ** random.uniform(log_f_low, log_f_high)

    f_stop_low_hz  = f_low_hz  / (10 ** random.uniform(1, 3))
    f_stop_high_hz = f_high_hz * (10 ** random.uniform(1, 3))

    db_pass      = simulate_attenuation(netlist, f_pass_hz)
    db_stop_low  = simulate_attenuation(netlist, f_stop_low_hz)
    db_stop_high = simulate_attenuation(netlist, f_stop_high_hz)

    if any(v is None for v in (db_pass, db_stop_low, db_stop_high)):
        return None

    db_stop_worst = max(db_stop_low, db_stop_high)
    pb, atten     = _add_leeway(db_pass, db_stop_worst)

    f_pass_low_prompt  = f_low_hz  * (10 ** random.uniform(0, 0.5))
    f_pass_high_prompt = f_high_hz / (10 ** random.uniform(0, 0.5))

    template_str = random.choice(prompt_templates)
    prompt = template_str.format(
        fc_low  = _hz_label(f_pass_low_prompt),
        fc_high = _hz_label(f_pass_high_prompt),
        fs_low  = _hz_label(f_stop_low_hz),
        fs_high = _hz_label(f_stop_high_hz),
        pb      = pb,
        atten   = atten,
    )

    return {
        "prompt":          prompt,
        "netlist":         netlist,
        "topology":        topology,
        "stages":          stages,
        "R_hp":            R_hp,
        "C_hp":            C_hp,
        "R_lp":            R_lp,
        "C_lp":            C_lp,
        "f_low_hz":        f_low_hz,
        "f_high_hz":       f_high_hz,
        "f_pass_hz":       f_pass_hz,
        "f_stop_low_hz":   f_stop_low_hz,
        "f_stop_high_hz":  f_stop_high_hz,
        "db_pass":         db_pass,
        "db_stop_low":     db_stop_low,
        "db_stop_high":    db_stop_high,
        "pb_spec_db":      pb,
        "atten_spec_db":   atten,
        "task":            "band_pass",
    }


def create_prompts(
    n_per_type: int,
    output_path: str = "./prompts/bpf_dataset.json",
    num_workers: int | None = None,
) -> list[dict]:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Build the full job list: n_per_type jobs per topology.
    # We over-sample by ~20 % to absorb expected None returns without a
    # second pass, then truncate to exactly n_per_type per topology at the end.
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
    parser.add_argument("-o", "--output",      default="./prompts/bpf_dataset.json")
    parser.add_argument("-w", "--num-workers", type=int,  default=None,
                        help="Worker processes (default: all CPU cores)")
    args = parser.parse_args()
    create_prompts(args.n_per_type, args.output, args.num_workers)