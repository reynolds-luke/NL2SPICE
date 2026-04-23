from dataclasses import dataclass, field
import json
import math
import random
from pathlib import Path
from tqdm import tqdm

from typing import Dict
from utils.find_cutoffs import find_lowpass_cutoff_frequency
from utils.measure_atten import simulate_attenuation
from utils.requirements import lpf_requirements

from prompt_templates.low_pass_templates import TEMPLATES


def _rc_stages(n: int, R: str, C: str, first_node: str = "VIN") -> str:
    lines = []
    for i in range(1, n + 1):
        in_node  = first_node if i == 1 else f"N{i-1}"
        out_node = "VOUT" if i == n else f"N{i}"
        lines.append(f"R{i}   {in_node:<6} {out_node:<6} {R}")
        lines.append(f"C{i}   {out_node:<6} 0      {C}")
    return "\n".join(lines)


@dataclass
class NetlistTemplate:
    name: str
    buffered: bool = False
    static_R: str = ""
    static_C: str = ""

    def render(self, R: str = "", C: str = "", stages: int = 0) -> str:
        R = R or self.static_R
        C = C or self.static_C
        n = stages or 1

        first_node = "VBUF" if self.buffered else "VIN"
        buf = "\n* Input buffer (ideal unity-gain voltage follower)\nEBUF VBUF  0     VIN 0  1\n" if self.buffered else ""
        kind = "buffered " if self.buffered else ""
        header = f"* {n}-stage passive RC low-pass filter {kind}(input op-amp buffer)" if stages else f"* Single-stage passive RC low-pass filter{' with input op-amp buffer' if self.buffered else ''}"

        return f"{header}\nV1   VIN   0     AC 1\n{buf}\n{_rc_stages(n, R, C, first_node)}\n"


class NetlistLibrary:
    def __init__(self):
        self._t: Dict[str, NetlistTemplate] = {}

    def register(self, key: str, **kwargs):
        self._t[key] = NetlistTemplate(name=key, **kwargs)

    def render(self, key: str, **params) -> str:
        if key not in self._t:
            raise KeyError(f"Unknown template: {key}")
        return self._t[key].render(**params)


def build_library() -> NetlistLibrary:
    lib = NetlistLibrary()
    lib.register("rc_single",          static_R="1k", static_C="1n")
    lib.register("buffered_rc_single", static_R="1k", static_C="1n", buffered=True)
    lib.register("rc_multi")
    lib.register("buffered_rc_multi",  buffered=True)
    return lib


lib = build_library()

# -----------------------------
# Configuration
# -----------------------------
R_MIN, R_MAX = 1e3,  100e3   # 1 kΩ – 100 kΩ
C_MIN, C_MAX = 1e-9, 100e-9  # 1 nF – 100 nF

SPICE_SUFFIXES = [
    (1e-12, "p"),
    (1e-9,  "n"),
    (1e-6,  "u"),
    (1e-3,  "m"),
    (1e3,   "k"),
    (1e6,   "meg"),
]

def _to_spice(value: float) -> str:
    """Convert a float to a compact SPICE string, e.g. 4700.0 -> '4.7k'."""
    for threshold, suffix in reversed(SPICE_SUFFIXES):
        if value >= threshold:
            scaled = value / threshold
            # Trim unnecessary decimals
            s = f"{scaled:.3g}"
            return f"{s}{suffix}"
    return f"{value:.3g}"

def _sample_rc() -> tuple[str, str]:
    """Sample R and C log-uniformly within the configured ranges."""
    R = 10 ** random.uniform(math.log10(R_MIN), math.log10(R_MAX))
    C = 10 ** random.uniform(math.log10(C_MIN), math.log10(C_MAX))
    return _to_spice(R), _to_spice(C)

def _add_leeway(fc_db: float, fs_db: float, leeway_db: float = 1) -> tuple[float, float]:
    """
    fc_db is attenuation at the passband edge  (negative, close to 0)
    fs_db is attenuation at the stopband point (negative, large magnitude)
    Returns (pb, atten) as positive dB figures with a bit of slack.
    """
    pb    = abs(fc_db) + leeway_db   # allow a little more loss in passband
    atten = abs(fs_db) - leeway_db   # require a little less in stopband
    return round(pb, 1), round(atten, 1)

def _hz_label(f: float) -> str:
    """Human-readable frequency label, e.g. 1590.0 -> '1.59 kHz'."""
    if f >= 1e6:
        return f"{f/1e6:.3g} MHz"
    if f >= 1e3:
        return f"{f/1e3:.3g} kHz"
    return f"{f:.3g} Hz"

def create_prompts(
    n_per_type: int,
    output_path: str = "./prompts/lpf_dataset.json",
) -> list[dict]:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    records = []

    total = n_per_type * len(TEMPLATES)
    pbar = tqdm(total=total, desc="Generating prompts")

    SINGLE_STAGE_TOPOLOGIES = ("rc_single", "buffered_rc_single")
    MULTI_STAGE_TOPOLOGIES  = ("rc_multi",  "buffered_rc_multi")

    for topology, prompt_templates in TEMPLATES.items():
        for _ in range(n_per_type):
            pbar.set_postfix(topology=topology, records=len(records))

            R_str, C_str = _sample_rc()

            if topology in SINGLE_STAGE_TOPOLOGIES:
                stages = 1
            else:
                stages = 2 # Max 2 stage for simplicity

            if topology in MULTI_STAGE_TOPOLOGIES:
                netlist = lib.render(topology, R=R_str, C=C_str, stages=stages)
            else:
                netlist = lib.render(topology, R=R_str, C=C_str)

            fc_hz, *_ = find_lowpass_cutoff_frequency(netlist)
            if fc_hz is None:
                pbar.update(1)
                continue

            decades_below = random.uniform(0, 1)
            decades_above = random.uniform(1, 3)
            f_pass = fc_hz / (10 ** decades_below)
            f_stop = fc_hz * (10 ** decades_above)

            db_pass = simulate_attenuation(netlist, f_pass)
            db_stop = simulate_attenuation(netlist, f_stop)
            if db_pass is None or db_stop is None:
                pbar.update(1)
                continue

            pb, atten = _add_leeway(db_pass, db_stop)

            template_str = random.choice(prompt_templates)
            prompt = template_str.format(
                fc    = _hz_label(f_pass),
                fs    = _hz_label(f_stop),
                pb    = pb,
                atten = atten,
            )
            prompt = lpf_requirements(prompt, f_pass, f_stop, pb, atten)

            records.append({
                "prompt":        prompt,
                "netlist":       netlist,
                "topology":      topology,
                "stages":        stages,
                "R":             R_str,
                "C":             C_str,
                "fc_hz":         fc_hz,
                "f_pass_hz":     f_pass,
                "f_stop_hz":     f_stop,
                "db_pass":       db_pass,
                "db_stop":       db_stop,
                "pb_spec_db":    pb,
                "atten_spec_db": atten,
                "task":          "low_pass",
            })
            pbar.update(1)

    pbar.close()

    with open(output_path, "w") as f:
        json.dump(records, f, indent=2)

    print(f"Wrote {len(records)} records to {output_path}")
    return records


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--n-per-type", type=int, default=10)
    parser.add_argument("-o", "--output", default="./prompts/lpf_dataset.json")
    args = parser.parse_args()
    create_prompts(args.n_per_type, args.output)