"""
analyse_results.py — Analysis and plotting for LLM netlist evaluation results.

Usage:
    python analyse_results.py                        # uses latest full-run results
    python analyse_results.py --run 20260414_020619  # specific timestamp

Outputs:
    Project_Baseline/output/analysis/figures_*.png
    Project_Baseline/output/analysis/summary_report.txt
"""

import argparse
import json
import math
import os
from pathlib import Path
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR  = _SCRIPT_DIR / "Project_Baseline" / "output"
ANALYSIS_DIR = OUTPUT_DIR / "analysis"

DATASETS = ["lpf", "hpf", "bpf", "notch"]
COLORS   = {"lpf": "#4C72B0", "hpf": "#DD8452", "bpf": "#55A868", "notch": "#C44E52"}
LABELS   = {"lpf": "Low-Pass", "hpf": "High-Pass", "bpf": "Band-Pass", "notch": "Notch"}

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def find_latest_run():
    """Return the timestamp string of the most recent full run (all 4 datasets present)."""
    timestamps = {}
    for f in OUTPUT_DIR.glob("results_*_*.json"):
        parts = f.stem.split("_", 2)  # results, <ds>, <timestamp>
        if len(parts) == 3:
            ds, ts = parts[1], parts[2]
            if ds in DATASETS:
                timestamps.setdefault(ts, set()).add(ds)
    # Find timestamps that have all 4 datasets and largest file sizes
    full = {ts: v for ts, v in timestamps.items() if v == set(DATASETS)}
    if not full:
        raise FileNotFoundError("No complete run found (need all 4 datasets).")
    return sorted(full.keys())[-1]


def load_run(timestamp):
    data = {}
    for ds in DATASETS:
        path = OUTPUT_DIR / f"results_{ds}_{timestamp}.json"
        if not path.exists():
            raise FileNotFoundError(f"Missing: {path}")
        with open(path) as f:
            data[ds] = json.load(f)
        print(f"  Loaded {ds}: {len(data[ds])} entries")
    return data


# ---------------------------------------------------------------------------
# Metric extraction helpers
# ---------------------------------------------------------------------------

def get_field(entry, *keys, default=None):
    obj = entry
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k, default)
        if obj is None:
            return default
    return obj


def extract_metrics(data):
    """Flatten all results into per-filter-type lists of metric values."""
    metrics = {ds: {} for ds in DATASETS}

    for ds, entries in data.items():
        m = metrics[ds]
        m["total"]      = len(entries)
        m["parsed"]     = sum(1 for e in entries if e.get("parse_success"))
        m["converged"]  = sum(1 for e in entries if e.get("simulation_converged"))
        matched = [e for e in entries if e.get("metrics", {}).get("filter_response_match")]
        m["matched"]    = len(matched)

        conv = [e for e in entries if e.get("simulation_converged") and e.get("metrics")]

        m["passband_ripple"]      = [get_field(e, "metrics", "passband_ripple_db")      for e in conv]
        m["passband_ripple"]      = [v for v in m["passband_ripple"] if v is not None]

        # LPF / HPF: single cutoff error
        m["cutoff_error"]     = [get_field(e, "metrics", "cutoff_freq_error_pct")   for e in conv]
        m["cutoff_error"]     = [v for v in m["cutoff_error"] if v is not None]
        m["cutoff_hz_spec"]   = [get_field(e, "params", "fc_hz")                    for e in conv if get_field(e, "metrics", "cutoff_freq_hz_measured") is not None]
        m["cutoff_hz_meas"]   = [get_field(e, "metrics", "cutoff_freq_hz_measured") for e in conv if get_field(e, "metrics", "cutoff_freq_hz_measured") is not None]

        # BPF: low and high cutoff errors
        m["cutoff_error_low"]  = [get_field(e, "metrics", "cutoff_freq_low_error_pct")  for e in conv]
        m["cutoff_error_low"]  = [v for v in m["cutoff_error_low"]  if v is not None]
        m["cutoff_error_high"] = [get_field(e, "metrics", "cutoff_freq_high_error_pct") for e in conv]
        m["cutoff_error_high"] = [v for v in m["cutoff_error_high"] if v is not None]

        # Attenuation achieved vs required
        atten_pairs = []
        for e in conv:
            for key in ["attenuation_at_fs", "attenuation_at_fs_low", "attenuation_at_fs_high"]:
                a = get_field(e, "metrics", key)
                if isinstance(a, dict) and a.get("required_db") is not None:
                    atten_pairs.append((a["required_db"], a["achieved_db"]))
        m["atten_required"] = [p[0] for p in atten_pairs]
        m["atten_achieved"] = [p[1] for p in atten_pairs]

        # Notch depth
        m["notch_depth_achieved"] = [get_field(e, "metrics", "notch_depth_db")        for e in conv]
        m["notch_depth_achieved"] = [v for v in m["notch_depth_achieved"] if v is not None]
        m["notch_depth_required"] = [get_field(e, "params",  "notch_depth_db")        for e in conv if get_field(e, "metrics", "notch_depth_db") is not None]

        # Generation stats
        m["gen_time"]   = [e["generation_time_s"] for e in entries if e.get("generation_time_s")]
        m["tokens"]     = [e["tokens_generated"]  for e in entries if e.get("parse_success") and e.get("tokens_generated")]

        # Topology breakdown
        topo_match  = {}
        topo_total  = {}
        for e in entries:
            t = e.get("topology", "unknown")
            topo_total[t] = topo_total.get(t, 0) + 1
            if e.get("simulation_converged"):
                topo_match[t] = topo_match.get(t, 0) + (1 if e.get("metrics", {}).get("filter_response_match") else 0)
        m["topo_total"] = topo_total
        m["topo_match"] = topo_match

    return metrics


# ---------------------------------------------------------------------------
# Plotting helpers
# ---------------------------------------------------------------------------

def savefig(fig, name):
    path = ANALYSIS_DIR / f"{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {path.name}")


def style():
    plt.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor":   "white",
        "axes.grid":        True,
        "grid.alpha":       0.3,
        "axes.spines.top":  False,
        "axes.spines.right":False,
        "font.size":        11,
    })


# ---------------------------------------------------------------------------
# Figure 1: Pipeline quality overview
# ---------------------------------------------------------------------------

def fig_pipeline_quality(metrics):
    fig, ax = plt.subplots(figsize=(10, 5))
    ds_list = DATASETS
    x = np.arange(len(ds_list))
    w = 0.25

    parse_pct = [metrics[ds]["parsed"]    / metrics[ds]["total"] * 100 for ds in ds_list]
    conv_pct  = [metrics[ds]["converged"] / metrics[ds]["total"] * 100 for ds in ds_list]
    match_pct = [metrics[ds]["matched"]   / max(metrics[ds]["converged"], 1) * 100 for ds in ds_list]

    bars1 = ax.bar(x - w, parse_pct, w, label="Parse success",        color="#4C72B0", alpha=0.9)
    bars2 = ax.bar(x,     conv_pct,  w, label="Simulation converged", color="#55A868", alpha=0.9)
    bars3 = ax.bar(x + w, match_pct, w, label="Spec match",           color="#C44E52", alpha=0.9)

    for bars in [bars1, bars2, bars3]:
        for bar in bars:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h + 0.5, f"{h:.1f}%",
                    ha="center", va="bottom", fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels([LABELS[ds] for ds in ds_list])
    ax.set_ylabel("Percentage (%)")
    ax.set_title("Pipeline Quality by Filter Type", fontweight="bold", pad=12)
    ax.set_ylim(0, 115)
    ax.legend(loc="upper right")
    ax.axhline(100, color="gray", linestyle="--", linewidth=0.8, alpha=0.5)

    total_entries = sum(metrics[ds]["total"] for ds in ds_list)
    total_conv    = sum(metrics[ds]["converged"] for ds in ds_list)
    total_match   = sum(metrics[ds]["matched"] for ds in ds_list)
    fig.text(0.5, -0.02,
             f"Total: {total_entries} entries  |  Converged: {total_conv} ({total_conv/total_entries*100:.1f}%)  |  "
             f"Spec match: {total_match} ({total_match/total_conv*100:.1f}% of converged)",
             ha="center", fontsize=10, color="gray")
    return fig


# ---------------------------------------------------------------------------
# Figure 2: Cutoff frequency — spec vs measured (LPF scatter)
# ---------------------------------------------------------------------------

def fig_fc_scatter(metrics):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    # LPF + HPF: spec vs measured (both have a single fc_hz cutoff)
    ax = axes[0]
    all_spec, all_meas = [], []
    for ds in ["lpf", "hpf"]:
        spec = metrics[ds]["cutoff_hz_spec"]
        meas = metrics[ds]["cutoff_hz_meas"]
        if spec and meas:
            ax.scatter(spec, meas, alpha=0.3, s=12, color=COLORS[ds], label=LABELS[ds])
            all_spec.extend(spec); all_meas.extend(meas)
    if all_spec:
        lim_min = min(min(all_spec), min(all_meas)) * 0.5
        lim_max = max(max(all_spec), max(all_meas)) * 2
        ax.plot([lim_min, lim_max], [lim_min, lim_max], "k--", linewidth=1, label="Perfect match")
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlabel("Specified fc (Hz)"); ax.set_ylabel("Measured fc (Hz)")
        ax.set_title("LPF & HPF: Specified vs Measured Cutoff", fontweight="bold")
        ax.legend(fontsize=9)

    # Cutoff error histogram — LPF, HPF, and BPF edges
    ax = axes[1]
    for ds, key, label in [
        ("lpf",  "cutoff_error",      "LPF"),
        ("hpf",  "cutoff_error",      "HPF"),
        ("bpf",  "cutoff_error_low",  "BPF (low edge)"),
        ("bpf",  "cutoff_error_high", "BPF (high edge)"),
    ]:
        vals = [min(v, 500) for v in metrics[ds].get(key, [])]  # cap at 500% for readability
        if vals:
            ax.hist(vals, bins=40, alpha=0.5, label=f"{label} (n={len(vals)})", density=True)
    ax.set_xlabel("Cutoff Frequency Error (%, capped at 500%)")
    ax.set_ylabel("Density")
    ax.set_title("Cutoff Frequency Error Distribution", fontweight="bold")
    ax.legend(fontsize=9)
    ax.axvline(20, color="red", linestyle="--", linewidth=1, label="20% threshold")

    fig.suptitle("Cutoff Frequency Accuracy", fontsize=13, fontweight="bold", y=1.02)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Figure 3: Passband ripple
# ---------------------------------------------------------------------------

def fig_passband_ripple(metrics):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    # Box plot
    ax = axes[0]
    ripple_data  = [metrics[ds]["passband_ripple"] for ds in DATASETS]
    ripple_data  = [[min(v, 30) for v in d] for d in ripple_data]   # cap at 30dB
    bp = ax.boxplot(ripple_data, patch_artist=True, medianprops={"color": "black", "linewidth": 2})
    for patch, ds in zip(bp["boxes"], DATASETS):
        patch.set_facecolor(COLORS[ds])
        patch.set_alpha(0.7)
    ax.set_xticklabels([LABELS[ds] for ds in DATASETS])
    ax.set_ylabel("Passband Ripple (dB, capped at 30)")
    ax.set_title("Passband Ripple Distribution", fontweight="bold")

    # Histogram overlay
    ax = axes[1]
    for ds in DATASETS:
        vals = [min(v, 30) for v in metrics[ds]["passband_ripple"]]
        if vals:
            ax.hist(vals, bins=40, alpha=0.5, color=COLORS[ds],
                    label=f"{LABELS[ds]} (med={np.median(vals):.1f}dB)", density=True)
    ax.set_xlabel("Passband Ripple (dB, capped at 30)")
    ax.set_ylabel("Density")
    ax.set_title("Passband Ripple Histogram", fontweight="bold")
    ax.legend(fontsize=9)

    fig.suptitle("Passband Ripple", fontsize=13, fontweight="bold", y=1.02)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Figure 4: Attenuation — achieved vs required
# ---------------------------------------------------------------------------

def fig_attenuation(metrics):
    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    axes = axes.flatten()

    for i, ds in enumerate(DATASETS):
        ax = axes[i]
        req = metrics[ds]["atten_required"]
        ach = metrics[ds]["atten_achieved"]
        if not req:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(LABELS[ds])
            continue

        req = np.array(req); ach = np.array(ach)
        met   = ach >= req
        unmet = ~met

        ax.scatter(req[met],   ach[met],   alpha=0.3, s=10, color="green", label=f"Met ({met.sum()})")
        ax.scatter(req[unmet], ach[unmet], alpha=0.3, s=10, color="red",   label=f"Unmet ({unmet.sum()})")

        lim = max(req.max(), ach.max(), 10) * 1.05
        ax.plot([0, lim], [0, lim], "k--", linewidth=1, label="Required = Achieved")
        ax.set_xlim(0, lim); ax.set_ylim(0, lim)
        ax.set_xlabel("Required Attenuation (dB)")
        ax.set_ylabel("Achieved Attenuation (dB)")
        ax.set_title(f"{LABELS[ds]} Filter — Attenuation", fontweight="bold")
        ax.legend(fontsize=9)
        pct = met.sum() / len(met) * 100
        ax.text(0.05, 0.92, f"{pct:.1f}% met", transform=ax.transAxes,
                fontsize=10, color="darkgreen" if pct > 50 else "darkred")

    fig.suptitle("Stopband Attenuation: Achieved vs Required", fontsize=13, fontweight="bold")
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Figure 5: Notch depth
# ---------------------------------------------------------------------------

def fig_notch(metrics):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    depths = metrics["notch"]["notch_depth_achieved"]
    req    = metrics["notch"]["notch_depth_required"]

    ax = axes[0]
    if depths:
        ax.hist(depths, bins=40, color=COLORS["notch"], alpha=0.8, edgecolor="white")
        ax.axvline(np.median(depths), color="black", linestyle="--",
                   label=f"Median: {np.median(depths):.1f} dB")
        ax.set_xlabel("Achieved Notch Depth (dB)")
        ax.set_ylabel("Count")
        ax.set_title("Notch Depth Distribution", fontweight="bold")
        ax.legend()

    ax = axes[1]
    if req and depths and len(req) == len(depths):
        req_arr = np.array(req); dep_arr = np.array(depths)
        met   = dep_arr >= req_arr
        unmet = ~met
        ax.scatter(req_arr[met],   dep_arr[met],   alpha=0.4, s=10, color="green", label=f"Met ({met.sum()})")
        ax.scatter(req_arr[unmet], dep_arr[unmet], alpha=0.4, s=10, color="red",   label=f"Unmet ({unmet.sum()})")
        lim = max(req_arr.max(), dep_arr.max()) * 1.05
        ax.plot([0, lim], [0, lim], "k--", linewidth=1)
        ax.set_xlabel("Required Notch Depth (dB)")
        ax.set_ylabel("Achieved Notch Depth (dB)")
        ax.set_title("Notch Depth: Achieved vs Required", fontweight="bold")
        ax.legend(fontsize=9)

    fig.suptitle("Notch Filter — Notch Depth Analysis", fontsize=13, fontweight="bold", y=1.02)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Figure 6: Spec match by topology
# ---------------------------------------------------------------------------

def fig_topology(metrics):
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    axes = axes.flatten()

    for i, ds in enumerate(DATASETS):
        ax = axes[i]
        topo_total = metrics[ds]["topo_total"]
        topo_match = metrics[ds]["topo_match"]
        topos = sorted(topo_total.keys())
        totals = [topo_total[t] for t in topos]
        matches = [topo_match.get(t, 0) for t in topos]
        match_pct = [m / t * 100 if t > 0 else 0 for m, t in zip(matches, totals)]

        x = np.arange(len(topos))
        bars = ax.bar(x, match_pct, color=COLORS[ds], alpha=0.8, edgecolor="white")
        for bar, tot, pct in zip(bars, totals, match_pct):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                    f"{pct:.0f}%\n(n={tot})", ha="center", va="bottom", fontsize=8)
        ax.set_xticks(x)
        ax.set_xticklabels(topos, rotation=15, ha="right")
        ax.set_ylabel("Spec Match Rate (%)")
        ax.set_ylim(0, max(max(match_pct) * 1.3, 10))
        ax.set_title(f"{LABELS[ds]} — Match Rate by Topology", fontweight="bold")

    fig.suptitle("Spec Match Rate by Circuit Topology", fontsize=13, fontweight="bold")
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Figure 7: Generation statistics
# ---------------------------------------------------------------------------

def fig_generation_stats(metrics):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    # Generation time
    ax = axes[0]
    for ds in DATASETS:
        times = metrics[ds]["gen_time"]
        if times:
            ax.hist(times, bins=30, alpha=0.6, color=COLORS[ds],
                    label=f"{LABELS[ds]} (μ={np.mean(times):.2f}s)", density=True)
    ax.set_xlabel("Generation Time per Sequence (s)")
    ax.set_ylabel("Density")
    ax.set_title("LLM Generation Time Distribution", fontweight="bold")
    ax.legend(fontsize=9)

    # Token count
    ax = axes[1]
    for ds in DATASETS:
        toks = metrics[ds]["tokens"]
        if toks:
            ax.hist(toks, bins=30, alpha=0.6, color=COLORS[ds],
                    label=f"{LABELS[ds]} (μ={np.mean(toks):.0f} tok)", density=True)
    ax.set_xlabel("Tokens Generated per Netlist")
    ax.set_ylabel("Density")
    ax.set_title("Token Count Distribution", fontweight="bold")
    ax.legend(fontsize=9)

    fig.suptitle("Generation Efficiency", fontsize=13, fontweight="bold", y=1.02)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Text summary
# ---------------------------------------------------------------------------

def write_text_summary(metrics, timestamp, out_path):
    lines = []
    lines += [
        "=" * 65,
        f"  LLM NETLIST EVALUATION — FULL RUN SUMMARY",
        f"  Timestamp: {timestamp}   Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 65,
        "",
    ]

    total   = sum(metrics[ds]["total"]     for ds in DATASETS)
    parsed  = sum(metrics[ds]["parsed"]    for ds in DATASETS)
    conv    = sum(metrics[ds]["converged"] for ds in DATASETS)
    matched = sum(metrics[ds]["matched"]   for ds in DATASETS)

    lines += [
        f"  Total entries:          {total}",
        f"  Parse success:          {parsed}/{total}  ({parsed/total*100:.1f}%)",
        f"  Simulation converged:   {conv}/{total}  ({conv/total*100:.1f}%)",
        f"  Spec match (of conv'd): {matched}/{conv}  ({matched/conv*100:.1f}%)",
        "",
        f"  {'Filter':<12} {'Total':>6}  {'Parse%':>7}  {'Conv%':>7}  {'Match%':>7}  {'Avg fc_err%':>11}",
        f"  {'-'*60}",
    ]
    for ds in DATASETS:
        m     = metrics[ds]
        n     = m["total"]
        parse = m["parsed"] / n * 100
        c     = m["converged"] / n * 100
        match = m["matched"] / max(m["converged"], 1) * 100
        fc_errs = m["cutoff_error"] + m["cutoff_error_low"] + m["cutoff_error_high"]
        fc_str  = f"{np.mean(fc_errs):.1f}%" if fc_errs else "n/a"
        lines.append(f"  {LABELS[ds]:<12} {n:>6}  {parse:>6.1f}%  {c:>6.1f}%  {match:>6.1f}%  {fc_str:>11}")

    lines += ["", "  KEY FINDINGS", "  " + "-" * 40]

    for ds in DATASETS:
        m = metrics[ds]
        ripples = m["passband_ripple"]
        req = np.array(m["atten_required"]); ach = np.array(m["atten_achieved"])
        atten_met_pct = (ach >= req).mean() * 100 if len(req) else float("nan")
        fc_errs = m["cutoff_error"] + m["cutoff_error_low"] + m["cutoff_error_high"]
        lines += [
            f"",
            f"  {LABELS[ds].upper()} FILTER:",
            f"    Passband ripple (median):   {np.median(ripples):.2f} dB"  if ripples else "    Passband ripple: n/a",
            f"    Attenuation spec met:        {atten_met_pct:.1f}%" if not math.isnan(atten_met_pct) else "    Attenuation spec met: n/a",
            f"    Avg cutoff freq error:       {np.mean(fc_errs):.1f}%" if fc_errs else "    Cutoff freq error: n/a",
        ]
        if ds == "notch":
            depths = m["notch_depth_achieved"]
            lines.append(f"    Median notch depth achieved: {np.median(depths):.1f} dB" if depths else "    Notch depth: n/a")

    lines += ["", "=" * 65, ""]

    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    print(f"  Saved: {out_path.name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=str, default=None,
                        help="Timestamp of the run to analyse (default: latest)")
    args = parser.parse_args()

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    style()

    timestamp = args.run or find_latest_run()
    print(f"Analysing run: {timestamp}")

    print("Loading data...")
    data = load_run(timestamp)

    print("Extracting metrics...")
    metrics = extract_metrics(data)

    print("Generating figures...")
    savefig(fig_pipeline_quality(metrics),    "fig1_pipeline_quality")
    savefig(fig_fc_scatter(metrics),          "fig2_cutoff_frequency")
    savefig(fig_passband_ripple(metrics),     "fig3_passband_ripple")
    savefig(fig_attenuation(metrics),         "fig4_attenuation")
    savefig(fig_notch(metrics),               "fig5_notch_depth")
    savefig(fig_topology(metrics),            "fig6_topology_breakdown")
    savefig(fig_generation_stats(metrics),    "fig7_generation_stats")

    print("Writing text summary...")
    write_text_summary(metrics, timestamp, ANALYSIS_DIR / "summary_report.txt")

    print(f"\nAll outputs written to: {ANALYSIS_DIR}")


if __name__ == "__main__":
    main()
