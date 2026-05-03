"""
plot_results.py — Generate report figures from rag_final_pipeline results.

Produces 5 figures saved to figures/:
  fig1_overall_spec_met.png      — Spec-met % per filter type
  fig2_topology_heatmap.png      — Spec-met % heatmap (filter × topology)
  fig3_iteration_distribution.png — How many iters entries needed (stacked bar)
  fig4_per_topology_bars.png     — Per-topology grouped bars for each filter
  fig5_baseline_comparison.png   — Baseline vs RAG Final side-by-side

Usage:
    python plot_results.py
"""

import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ---------------------------------------------------------------------------
# Paths & data files (latest run per dataset)
# ---------------------------------------------------------------------------
OUT_DIR  = Path(__file__).parent.parent / "rag_final_output"
FIG_DIR  = Path(__file__).parent / "figures"
FIG_DIR.mkdir(exist_ok=True)

FILES = {
    "LPF":   OUT_DIR / "results_lpf_20260429_224747.json",
    "HPF":   OUT_DIR / "results_hpf_20260429_224747.json",
    "BPF":   OUT_DIR / "results_bpf_20260502_174846.json",
    "Notch": OUT_DIR / "results_notch_20260502_174846.json",
}

TOPO_LABELS = {
    "rc_single":          "RC\nSingle",
    "buffered_rc_single": "RC Single\n(Buffered)",
    "rc_multi":           "RC\nMulti",
    "buffered_rc_multi":  "RC Multi\n(Buffered)",
}
TOPO_ORDER = ["rc_single", "buffered_rc_single", "rc_multi", "buffered_rc_multi"]

FILTER_COLORS = {
    "LPF":   "#4C72B0",
    "HPF":   "#DD8452",
    "BPF":   "#55A868",
    "Notch": "#C44E52",
}

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
data: dict[str, list] = {}
for label, path in FILES.items():
    with open(path) as f:
        data[label] = json.load(f)

FILTER_ORDER = list(FILES.keys())


def spec_met_pct(results: list) -> float:
    return sum(r["final_spec_met"] for r in results) / len(results) * 100


def by_topology(results: list) -> dict[str, list]:
    out: dict[str, list] = {}
    for r in results:
        out.setdefault(r["topology"], []).append(r)
    return out


# ---------------------------------------------------------------------------
# Shared style
# ---------------------------------------------------------------------------
plt.rcParams.update({
    "font.family":     "DejaVu Sans",
    "font.size":       11,
    "axes.spines.top":    False,
    "axes.spines.right":  False,
    "axes.grid":          True,
    "axes.grid.axis":     "y",
    "grid.alpha":         0.4,
    "grid.linestyle":     "--",
    "figure.dpi":         150,
})


def annotate_bars(ax, bars, fmt="{:.0f}%", offset=0.8):
    for bar in bars:
        h = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            h + offset,
            fmt.format(h),
            ha="center", va="bottom", fontsize=9, fontweight="bold",
        )


# ---------------------------------------------------------------------------
# Fig 1 — Overall spec-met % per filter type
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(7, 4.5))

pcts   = [spec_met_pct(data[f]) for f in FILTER_ORDER]
colors = [FILTER_COLORS[f] for f in FILTER_ORDER]
bars   = ax.bar(FILTER_ORDER, pcts, color=colors, width=0.5, zorder=3, edgecolor="white", linewidth=0.8)

annotate_bars(ax, bars)
ax.set_ylim(0, 110)
ax.set_ylabel("Spec-met rate (%)")
ax.set_title("Specification Pass Rate by Filter Type\n(RAG Final Pipeline, n=252 per type)", fontsize=12)
ax.axhline(100, color="gray", linewidth=0.8, linestyle=":")

# Sample count annotation
for i, f in enumerate(FILTER_ORDER):
    n    = len(data[f])
    met  = sum(r["final_spec_met"] for r in data[f])
    ax.text(i, 2, f"{met}/{n}", ha="center", va="bottom", fontsize=8.5, color="white", fontweight="bold")

plt.tight_layout()
plt.savefig(FIG_DIR / "fig1_overall_spec_met.png", bbox_inches="tight")
plt.close()
print("Saved fig1_overall_spec_met.png")


# ---------------------------------------------------------------------------
# Fig 2 — Spec-met heatmap (filter × topology)
# ---------------------------------------------------------------------------
grid = np.zeros((len(FILTER_ORDER), len(TOPO_ORDER)))
for fi, f in enumerate(FILTER_ORDER):
    bt = by_topology(data[f])
    for ti, topo in enumerate(TOPO_ORDER):
        rs = bt.get(topo, [])
        grid[fi, ti] = spec_met_pct(rs) if rs else 0

fig, ax = plt.subplots(figsize=(8, 3.8))
im = ax.imshow(grid, cmap="RdYlGn", vmin=0, vmax=100, aspect="auto")

ax.set_xticks(range(len(TOPO_ORDER)))
ax.set_xticklabels([TOPO_LABELS[t] for t in TOPO_ORDER], fontsize=10)
ax.set_yticks(range(len(FILTER_ORDER)))
ax.set_yticklabels(FILTER_ORDER, fontsize=11)
ax.set_title("Spec-met Rate (%) by Filter Type and Topology", fontsize=12, pad=10)

for fi in range(len(FILTER_ORDER)):
    for ti in range(len(TOPO_ORDER)):
        v = grid[fi, ti]
        color = "white" if v < 45 or v > 82 else "black"
        ax.text(ti, fi, f"{v:.0f}%", ha="center", va="center",
                fontsize=11, fontweight="bold", color=color)

cbar = plt.colorbar(im, ax=ax, shrink=0.85, pad=0.02)
cbar.set_label("Spec-met (%)", fontsize=10)
ax.spines[:].set_visible(False)
ax.grid(False)

plt.tight_layout()
plt.savefig(FIG_DIR / "fig2_topology_heatmap.png", bbox_inches="tight")
plt.close()
print("Saved fig2_topology_heatmap.png")


# ---------------------------------------------------------------------------
# Fig 3 — Iteration distribution (stacked bar: pass@1, pass@2, pass@3+, fail)
# ---------------------------------------------------------------------------
ITER_COLORS = ["#2ca02c", "#98df8a", "#ffbb78", "#d62728"]
ITER_LABELS = ["Pass @ iter 1", "Pass @ iter 2", "Pass @ iter 3+", "Failed"]

iter_data = {f: [0, 0, 0, 0] for f in FILTER_ORDER}
for f in FILTER_ORDER:
    for r in data[f]:
        met      = r["final_spec_met"]
        n_iters  = r["iterations_used"]
        if met:
            idx = min(n_iters - 1, 2)   # 0=iter1, 1=iter2, 2=iter3+
            iter_data[f][idx] += 1
        else:
            iter_data[f][3] += 1

fig, ax = plt.subplots(figsize=(8, 4.5))
x     = np.arange(len(FILTER_ORDER))
bottoms = np.zeros(len(FILTER_ORDER))

for i, (label, color) in enumerate(zip(ITER_LABELS, ITER_COLORS)):
    vals = np.array([iter_data[f][i] / len(data[f]) * 100 for f in FILTER_ORDER])
    bars = ax.bar(x, vals, bottom=bottoms, color=color, label=label,
                  width=0.55, edgecolor="white", linewidth=0.6, zorder=3)
    for j, (bar, v) in enumerate(zip(bars, vals)):
        if v >= 5:
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bottoms[j] + v / 2,
                    f"{v:.0f}%",
                    ha="center", va="center", fontsize=9, fontweight="bold",
                    color="white" if color in ("#2ca02c", "#d62728") else "black")
    bottoms += vals

ax.set_xticks(x)
ax.set_xticklabels(FILTER_ORDER, fontsize=11)
ax.set_ylabel("Entries (%)")
ax.set_ylim(0, 108)
ax.set_title("Iteration Distribution to Reach Specification\n(RAG Final Pipeline, n=252 per type)", fontsize=12)
ax.legend(loc="upper right", framealpha=0.9, fontsize=9)

plt.tight_layout()
plt.savefig(FIG_DIR / "fig3_iteration_distribution.png", bbox_inches="tight")
plt.close()
print("Saved fig3_iteration_distribution.png")


# ---------------------------------------------------------------------------
# Fig 4 — Per-topology grouped bars (all filter types side by side)
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 5))

n_topos   = len(TOPO_ORDER)
n_filters = len(FILTER_ORDER)
width     = 0.18
x         = np.arange(n_topos)

for fi, f in enumerate(FILTER_ORDER):
    bt   = by_topology(data[f])
    vals = [spec_met_pct(bt.get(t, [])) if bt.get(t) else 0 for t in TOPO_ORDER]
    offset = (fi - n_filters / 2 + 0.5) * width
    bars = ax.bar(x + offset, vals, width=width, label=f,
                  color=FILTER_COLORS[f], zorder=3, edgecolor="white", linewidth=0.5)
    for bar, v in zip(bars, vals):
        if v > 5:
            ax.text(bar.get_x() + bar.get_width() / 2, v + 0.8,
                    f"{v:.0f}", ha="center", va="bottom", fontsize=7.5, fontweight="bold")

ax.set_xticks(x)
ax.set_xticklabels([TOPO_LABELS[t] for t in TOPO_ORDER], fontsize=10.5)
ax.set_ylabel("Spec-met rate (%)")
ax.set_ylim(0, 115)
ax.set_title("Spec-met Rate by Topology and Filter Type\n(RAG Final Pipeline, n=63 per cell)", fontsize=12)
ax.legend(title="Filter", fontsize=9.5, title_fontsize=10, framealpha=0.9)
ax.axhline(100, color="gray", linewidth=0.7, linestyle=":")

plt.tight_layout()
plt.savefig(FIG_DIR / "fig4_per_topology_bars.png", bbox_inches="tight")
plt.close()
print("Saved fig4_per_topology_bars.png")

# ---------------------------------------------------------------------------
# Fig 5 — Baseline vs RAG Final comparison
# ---------------------------------------------------------------------------

# Baseline: pipeline_v2.py one-shot, n=1000 per filter (New_Datagen/output Apr 27)
BASELINE = {
    "LPF":   2.9,
    "HPF":   0.0,
    "BPF":  30.9,
    "Notch": 18.3,
}
OVERALL_BASELINE = 17.5
OVERALL_RAG      = sum(spec_met_pct(data[f]) for f in FILTER_ORDER) / len(FILTER_ORDER)

fig, axes = plt.subplots(1, 2, figsize=(13, 5),
                         gridspec_kw={"width_ratios": [3, 1]},
                         constrained_layout=True)

# --- Left panel: per-filter grouped bars ---
ax = axes[0]
x      = np.arange(len(FILTER_ORDER))
w      = 0.32
c_base = "#B0BEC5"
c_rag  = "#1565C0"

bars_b = ax.bar(x - w/2, [BASELINE[f] for f in FILTER_ORDER], width=w,
                color=c_base, label="Baseline (one-shot)", zorder=3,
                edgecolor="white", linewidth=0.7)
bars_r = ax.bar(x + w/2, [spec_met_pct(data[f]) for f in FILTER_ORDER], width=w,
                color=c_rag, label="RAG Final (agentic)", zorder=3,
                edgecolor="white", linewidth=0.7)

for bar in bars_b:
    h = bar.get_height()
    ax.text(bar.get_x() + bar.get_width() / 2, h + 1.2,
            f"{h:.0f}%", ha="center", va="bottom", fontsize=9, color="#546E7A")

for bar in bars_r:
    h = bar.get_height()
    ax.text(bar.get_x() + bar.get_width() / 2, h + 1.2,
            f"{h:.0f}%", ha="center", va="bottom", fontsize=9,
            fontweight="bold", color=c_rag)

# Delta annotations (↑ improvement arrows)
for i, f in enumerate(FILTER_ORDER):
    b = BASELINE[f]
    r = spec_met_pct(data[f])
    delta = r - b
    ax.annotate(f"+{delta:.0f}pp",
                xy=(i + w/2, r + 5), fontsize=8,
                ha="center", color="#2E7D32", fontweight="bold")

ax.set_xticks(x)
ax.set_xticklabels(FILTER_ORDER, fontsize=12)
ax.set_ylabel("Spec-met rate (%)", fontsize=11)
ax.set_ylim(0, 118)
ax.set_title("Per-filter Specification Pass Rate:\nBaseline vs RAG Final Pipeline", fontsize=12)
ax.legend(fontsize=10, framealpha=0.9)
ax.axhline(100, color="gray", linewidth=0.7, linestyle=":")

# --- Right panel: overall comparison ---
ax2 = axes[1]
overall_vals = [OVERALL_BASELINE, OVERALL_RAG]
overall_bars = ax2.bar(["Baseline", "RAG\nFinal"], overall_vals,
                       color=[c_base, c_rag], width=0.45, zorder=3,
                       edgecolor="white", linewidth=0.7)

for bar, v in zip(overall_bars, overall_vals):
    ax2.text(bar.get_x() + bar.get_width() / 2, v + 1.5,
             f"{v:.1f}%", ha="center", va="bottom", fontsize=11, fontweight="bold")

delta_overall = OVERALL_RAG - OVERALL_BASELINE
ax2.text(0.5, max(overall_vals) + 9, f"+{delta_overall:.0f}pp",
         ha="center", va="bottom", fontsize=11, color="#2E7D32", fontweight="bold")

ax2.set_ylim(0, 120)
ax2.set_ylabel("Spec-met rate (%)", fontsize=11)
ax2.set_title("Overall\n(avg across filters)", fontsize=12)
ax2.axhline(100, color="gray", linewidth=0.7, linestyle=":")

ax2.set_ylim(0, 118)
ax2.set_ylabel("Spec-met rate (%)", fontsize=11)
ax2.set_title("Overall\n(avg across filters)", fontsize=12)
ax2.axhline(100, color="gray", linewidth=0.7, linestyle=":")

plt.savefig(FIG_DIR / "fig5_baseline_comparison.png", bbox_inches="tight")
plt.close()
print("Saved fig5_baseline_comparison.png")

print(f"\nAll figures saved to {FIG_DIR}/")
