"""
plot_appendix.py — Generate 3 appendix figures for the NL2SPICE report.

  fig_a1_cumulative_convergence.png  — Cumulative spec-met % vs. iteration
  fig_a2_failure_modes.png           — Which metric fails for never-passing entries
  fig_a3_bode_before_after.png       — Bode plot: BPF iter-1 failure vs. final pass

Usage:
    python plot_appendix.py
"""

import json
import sys
import tempfile
import subprocess
import re
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE    = Path(__file__).parent
OUT_DIR = HERE / "rag_final_output"
FIG_DIR = HERE / "figures"
FIG_DIR.mkdir(exist_ok=True)

FILES = {
    "LPF":   OUT_DIR / "results_lpf_20260429_224747.json",
    "HPF":   OUT_DIR / "results_hpf_20260429_224747.json",
    "BPF":   OUT_DIR / "results_bpf_20260502_174846.json",
    "Notch": OUT_DIR / "results_notch_20260502_174846.json",
}
FILTER_ORDER  = ["LPF", "HPF", "BPF", "Notch"]
FILTER_COLORS = {"LPF": "#4C72B0", "HPF": "#DD8452", "BPF": "#55A868", "Notch": "#C44E52"}
NGSPICE_PATH  = "ngspice"

# ---------------------------------------------------------------------------
# Shared style
# ---------------------------------------------------------------------------
plt.rcParams.update({
    "font.family":        "DejaVu Sans",
    "font.size":          11,
    "axes.spines.top":    False,
    "axes.spines.right":  False,
    "axes.grid":          True,
    "axes.grid.axis":     "y",
    "grid.alpha":         0.4,
    "grid.linestyle":     "--",
    "figure.dpi":         150,
})

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
data: dict[str, list] = {}
for label, path in FILES.items():
    with open(path) as f:
        data[label] = json.load(f)

# ===========================================================================
# Fig A1 — Cumulative spec-met rate vs. iteration number
# ===========================================================================
MAX_ITERS = 5
fig, ax = plt.subplots(figsize=(7, 4.5))

for f in FILTER_ORDER:
    results    = data[f]
    n_total    = len(results)
    cumulative = []
    passed_so_far = 0
    for i in range(1, MAX_ITERS + 1):
        # entries that passed AT iteration i (or earlier)
        passed_so_far = sum(
            1 for r in results
            if r["final_spec_met"] and r["iterations_used"] <= i
        )
        cumulative.append(passed_so_far / n_total * 100)

    ax.plot(range(1, MAX_ITERS + 1), cumulative,
            marker="o", linewidth=2, markersize=6,
            color=FILTER_COLORS[f], label=f)
    # Annotate final value
    ax.annotate(f"{cumulative[-1]:.0f}%",
                xy=(MAX_ITERS, cumulative[-1]),
                xytext=(8, 0), textcoords="offset points",
                va="center", fontsize=9, color=FILTER_COLORS[f], fontweight="bold")

ax.set_xlim(0.7, MAX_ITERS + 0.6)
ax.set_ylim(0, 108)
ax.set_xticks(range(1, MAX_ITERS + 1))
ax.set_xlabel("Iteration number")
ax.set_ylabel("Cumulative spec-met rate (%)")
ax.set_title("Cumulative Specification Pass Rate vs. Agentic Iteration\n(RAG Final Pipeline, n=252 per filter type)", fontsize=12)
ax.axhline(100, color="gray", linewidth=0.7, linestyle=":")
ax.legend(fontsize=10, framealpha=0.9)

plt.tight_layout()
plt.savefig(FIG_DIR / "fig_a1_cumulative_convergence.png", bbox_inches="tight")
plt.close()
print("Saved fig_a1_cumulative_convergence.png")

# ===========================================================================
# Fig A2 — Failure mode breakdown for never-passing entries
# ===========================================================================

def get_failure_modes(results: list, label: str) -> dict[str, int]:
    """Count how many times each metric is the failing metric for entries that never pass."""
    counts = {
        "Cutoff freq":   0,
        "Attenuation":   0,
        "Passband ripple": 0,
        "Notch depth":   0,
        "Parse / sim":   0,
    }
    for r in results:
        if r["final_spec_met"]:
            continue
        m = r.get("metrics", {})
        if not r.get("parse_success") or not r.get("simulation_converged"):
            counts["Parse / sim"] += 1
            continue
        # Check each metric — mark all that fail
        failed_any = False
        if label in ("LPF", "HPF"):
            atten = m.get("attenuation_at_fs", {})
            if not atten.get("met", True):
                counts["Attenuation"] += 1; failed_any = True
            if m.get("cutoff_freq_error_pct", 0) > 20:
                counts["Cutoff freq"] += 1; failed_any = True
            if m.get("passband_ripple_db", 0) > 3:
                counts["Passband ripple"] += 1; failed_any = True
        elif label == "BPF":
            atten_lo = m.get("attenuation_at_fs_low", {})
            atten_hi = m.get("attenuation_at_fs_high", {})
            if not atten_lo.get("met", True) or not atten_hi.get("met", True):
                counts["Attenuation"] += 1; failed_any = True
            if m.get("cutoff_freq_low_error_pct", 0) > 20 or m.get("cutoff_freq_high_error_pct", 0) > 20:
                counts["Cutoff freq"] += 1; failed_any = True
            if m.get("passband_ripple_db", 0) > 3:
                counts["Passband ripple"] += 1; failed_any = True
        elif label == "Notch":
            if not m.get("notch_depth_met", True):
                counts["Notch depth"] += 1; failed_any = True
            if m.get("passband_ripple_high_db", 0) > 3 or m.get("passband_ripple_low_db", 0) > 3:
                counts["Passband ripple"] += 1; failed_any = True
        if not failed_any:
            counts["Parse / sim"] += 1
    return counts

METRIC_COLORS = {
    "Cutoff freq":     "#4C72B0",
    "Attenuation":     "#DD8452",
    "Passband ripple": "#55A868",
    "Notch depth":     "#C44E52",
    "Parse / sim":     "#9467bd",
}
METRIC_ORDER = ["Cutoff freq", "Attenuation", "Passband ripple", "Notch depth", "Parse / sim"]

fig, ax = plt.subplots(figsize=(9, 4.5))
x     = np.arange(len(FILTER_ORDER))
width = 0.15

for mi, metric in enumerate(METRIC_ORDER):
    vals = []
    for f in FILTER_ORDER:
        n_fail = sum(1 for r in data[f] if not r["final_spec_met"])
        counts = get_failure_modes(data[f], f)
        vals.append(counts[metric])
    offset = (mi - len(METRIC_ORDER) / 2 + 0.5) * width
    bars = ax.bar(x + offset, vals, width=width,
                  label=metric, color=METRIC_COLORS[metric],
                  zorder=3, edgecolor="white", linewidth=0.5)
    for bar, v in zip(bars, vals):
        if v > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, v + 0.15,
                    str(v), ha="center", va="bottom", fontsize=8, fontweight="bold")

ax.set_xticks(x)
ax.set_xticklabels(FILTER_ORDER, fontsize=11)
ax.set_ylabel("Number of failing entries")
ax.set_title("Failure Mode Breakdown for Never-Passing Entries\n(RAG Final Pipeline — entries may fail multiple metrics simultaneously)", fontsize=12)
ax.legend(fontsize=9, framealpha=0.9, ncol=2)
ax.set_ylim(0, ax.get_ylim()[1] * 1.15)
ax.grid(axis="y", alpha=0.4, linestyle="--")

# Annotate total failures per filter
for i, f in enumerate(FILTER_ORDER):
    n_fail = sum(1 for r in data[f] if not r["final_spec_met"])
    ax.text(i, ax.get_ylim()[1] * 0.97, f"({n_fail} total\nfailures)",
            ha="center", va="top", fontsize=8, color="gray")

plt.tight_layout()
plt.savefig(FIG_DIR / "fig_a2_failure_modes.png", bbox_inches="tight")
plt.close()
print("Saved fig_a2_failure_modes.png")

# ===========================================================================
# Fig A3 — Bode plot: BPF before (iter 1) vs. after (final passing iteration)
# ===========================================================================

def build_spice_file(netlist: str, params: dict, task_type: str) -> str:
    """Wrap a netlist with AC analysis command for NGSpice."""
    lines = netlist.strip().splitlines()
    # Remove any existing .end / .ac lines
    cleaned = [l for l in lines if not re.match(r'^\.(end|ac)\b', l, re.IGNORECASE)]

    fc_low  = params.get("fc_low_hz")  or params.get("fc_hz", 1000)
    fc_high = params.get("fc_high_hz") or params.get("fc_hz", 1000)
    fstart  = min(fc_low, fc_high) / 100
    fstop   = max(fc_low, fc_high) * 100

    cleaned += [
        f".AC DEC 200 {fstart:.6g} {fstop:.6g}",
        ".PRINT AC V(VOUT)",
        ".end",
    ]
    return "\n".join(cleaned)


def run_ngspice(spice_content: str) -> dict[float, float]:
    """Run NGSpice and return {freq_hz: magnitude_db} dict."""
    with tempfile.TemporaryDirectory() as tmp:
        cir  = Path(tmp) / "circuit.cir"
        out  = Path(tmp) / "output.txt"
        cir.write_text(spice_content)
        result = subprocess.run(
            [NGSPICE_PATH, "-b", "-o", str(out), str(cir)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return {}
        txt = out.read_text() if out.exists() else result.stdout

    ac_data = {}
    for line in txt.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                freq = float(parts[0])
                mag  = float(parts[1])
                if freq > 0:
                    mag_db = 20 * np.log10(abs(mag)) if mag > 0 else -100
                    ac_data[freq] = mag_db
            except ValueError:
                pass
    return ac_data


# Load LPF entry index 21:
#   Iter 1: C=15.2p → cutoff at ~1 MHz (7904% error, target 13 kHz)
#   Iter 2: C=1.132n → cutoff at ~14 kHz (7.5% error, passes)
with open(FILES["LPF"]) as f:
    lpf_data = json.load(f)

entry     = next(r for r in lpf_data if r["index"] == 21)
params    = entry["params"]
iter1_net = entry["iterations"][0]["generated_netlist"]
final_net = entry["iterations"][entry["iterations_used"] - 1]["generated_netlist"]

fc  = params["fc_hz"]
fs  = params["fs_hz"]
atten = params["atten_db"]

# Sweep from fc/1000 to fs*3 so both cutoffs are visible
fstart = fc / 1000
fstop  = fs * 3

print("Running NGSpice for LPF iter-1 netlist...")
spice1   = build_spice_file(iter1_net, params, "low_pass_filter")
ac_data1 = run_ngspice(spice1)

print("Running NGSpice for LPF final netlist...")
spice2   = build_spice_file(final_net, params, "low_pass_filter")
ac_data2 = run_ngspice(spice2)

if not ac_data1 or not ac_data2:
    print("WARNING: NGSpice simulation failed — skipping fig_a3")
else:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True,
                              constrained_layout=True)

    titles = ["Iteration 1  (FAIL)", f"Iteration {entry['iterations_used']}  (PASS)"]
    colors = ["#C44E52", "#55A868"]

    for ax, ac_data, title, color in zip(axes, [ac_data1, ac_data2], titles, colors):
        freqs = sorted(ac_data)
        mags  = [ac_data[f] for f in freqs]

        ax.semilogx(freqs, mags, color=color, linewidth=2.2, label="Simulated response")

        # Spec limit lines
        ax.axhline(-3,     color="navy", linewidth=1.2, linestyle="--",
                   label=f"−3 dB target (fc = {fc/1e3:.1f} kHz)")
        ax.axhline(-atten, color="gray", linewidth=1,   linestyle=":",
                   label=f"−{atten:.0f} dB attenuation req")

        # Target cutoff and stopband markers
        ax.axvline(fc, color="navy", linewidth=0.8, linestyle="--", alpha=0.5)
        ax.axvline(fs, color="gray", linewidth=0.8, linestyle=":",  alpha=0.5)

        # Shaded stopband
        ax.axvspan(fs, max(freqs), alpha=0.08, color="red", label="Stopband")

        ax.set_xlabel("Frequency (Hz)")
        ax.set_title(title, fontsize=12, color=color, fontweight="bold")
        ax.set_ylim(-80, 5)
        ax.grid(True, which="both", alpha=0.3, linestyle="--")
        ax.legend(fontsize=8.5, framealpha=0.9, loc="lower left")

    axes[0].set_ylabel("Magnitude (dB)")
    fig.suptitle(
        f"LPF Frequency Response: Before vs. After Agentic Refinement\n"
        f"(target fc = {fc/1e3:.1f} kHz,  attenuation ≥ {atten:.0f} dB at {fs/1e3:.0f} kHz)",
        fontsize=12
    )

    plt.savefig(FIG_DIR / "fig_a3_bode_before_after.png", bbox_inches="tight")
    plt.close()
    print("Saved fig_a3_bode_before_after.png")

print(f"\nAll appendix figures saved to {FIG_DIR}/")
