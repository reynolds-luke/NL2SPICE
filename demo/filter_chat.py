"""
filter_chat.py — Interactive filter design chat using the RAG Final Pipeline.

Guides the user through entering filter specs, runs the agentic design loop,
displays the generated netlist, and saves a frequency response plot.

Usage:
    python filter_chat.py
"""

import math, os, re, sys, tempfile, time
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent
_REPO_ROOT  = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from pipeline_v2 import (
    load_model, extract_netlist, build_spice_file,
    run_ngspice, parse_ac_results, calculate_metrics,
)
from rag_final_pipeline import agentic_loop, MAX_ITERS
from rag_pipeline import _fmt_hz

CHAT_OUT = _REPO_ROOT / "demo" / "chat_output"
CHAT_OUT.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Terminal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _hr(char="─", width=62):
    print(char * width)

def _banner():
    print()
    print("╔" + "═" * 60 + "╗")
    print("║{:^60}║".format("RAG Filter Design Assistant"))
    print("║{:^60}║".format("Qwen2.5-Coder-14B  ·  RAG Final Pipeline"))
    print("╚" + "═" * 60 + "╝")
    print()

def _ask(prompt, options=None, default=None):
    """Prompt user for input with optional validation."""
    while True:
        suffix = f" [{'/'.join(options)}]" if options else (f" [default: {default}]" if default else "")
        raw = input(f"  {prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        if options and raw.lower() not in [o.lower() for o in options]:
            print(f"    → Please enter one of: {', '.join(options)}")
            continue
        return raw

def _ask_float(prompt, default=None):
    while True:
        suffix = f" [default: {default}]" if default is not None else ""
        raw = input(f"  {prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return float(default)
        try:
            return float(raw)
        except ValueError:
            print("    → Please enter a number (e.g. 1000 or 1.5)")

def _ask_freq(prompt, default=None):
    """Accept '1 kHz', '1000', '1000 Hz', '1.5 MHz' etc → Hz float."""
    while True:
        suffix = f" [default: {default}]" if default else ""
        raw = input(f"  {prompt} (e.g. '1 kHz', '500 Hz'){suffix}: ").strip()
        if not raw and default:
            raw = default
        m = re.match(r"([\d.]+(?:e[+-]?\d+)?)\s*(MHz|kHz|Hz|k|M)?$", raw, re.I)
        if m:
            val = float(m.group(1))
            unit = (m.group(2) or "Hz").lower()
            return val * {"mhz": 1e6, "m": 1e6, "khz": 1e3, "k": 1e3, "hz": 1.0}.get(unit, 1.0)
        print("    → Could not parse frequency. Try '1 kHz' or '1000'.")


# ─────────────────────────────────────────────────────────────────────────────
# Prompt builder — mirrors the New_Datagen dataset format exactly
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_freq_str(hz):
    """Format Hz to the dataset style: '1.0 kHz', '500 Hz', '2.5 MHz'."""
    if hz >= 1e6:
        return f"{hz/1e6:.4g} MHz"
    if hz >= 1e3:
        return f"{hz/1e3:.4g} kHz"
    return f"{hz:.4g} Hz"

def build_prompt(task, topology, specs):
    """
    Build a dataset-compatible prompt string from user specs.
    specs keys depend on task type — see collect_specs().
    """
    topo_desc = {
        "rc_single":          "single-stage passive RC",
        "buffered_rc_single": "single-stage buffered RC",
        "rc_multi":           "two-stage passive RC",
        "buffered_rc_multi":  "two-stage buffered RC",
    }[topology]

    if task == "low_pass":
        fc  = _fmt_freq_str(specs["fc"])
        fs  = _fmt_freq_str(specs["fs"])
        pb  = specs["pb_loss"]
        att = specs["atten"]
        req = (f"  Type: low-pass filter\n"
               f"  Passband edge (fc): {fc}  [max loss: {pb} dB]\n"
               f"  Stopband edge (fs): {fs}  [min attenuation: {att} dB]")
        body = (f"Design a {topo_desc} low-pass filter meeting:\n"
                f"  • Pass frequencies below {fc} with ≤{pb} dB loss\n"
                f"  • Attenuate at {fs} by ≥{att} dB")

    elif task == "high_pass":
        fc  = _fmt_freq_str(specs["fc"])
        fs  = _fmt_freq_str(specs["fs"])
        pb  = specs["pb_loss"]
        att = specs["atten"]
        req = (f"  Type: high-pass filter\n"
               f"  Passband edge (fc): {fc}  [max loss: {pb} dB]\n"
               f"  Stopband edge (fs): {fs}  [min attenuation: {att} dB]")
        body = (f"Design a {topo_desc} high-pass filter meeting:\n"
                f"  • Pass frequencies above {fc} with ≤{pb} dB loss\n"
                f"  • Attenuate at {fs} by ≥{att} dB")

    elif task == "band_pass":
        fcl = _fmt_freq_str(specs["fc_low"])
        fch = _fmt_freq_str(specs["fc_high"])
        fsl = _fmt_freq_str(specs["fs_low"])
        fsh = _fmt_freq_str(specs["fs_high"])
        pb  = specs["pb_loss"]
        att = specs["atten"]
        req = (f"  Type: band-pass filter\n"
               f"  Lower passband edge (fc_low): {fcl}  [max loss: {pb} dB]\n"
               f"  Upper passband edge (fc_high): {fch}  [max loss: {pb} dB]\n"
               f"  Lower stopband edge (fs_low): {fsl}  [min attenuation: {att} dB]\n"
               f"  Upper stopband edge (fs_high): {fsh}  [min attenuation: {att} dB]")
        body = (f"Design a {topo_desc} band-pass filter meeting:\n"
                f"  • Pass {fcl}–{fch} with ≤{pb} dB loss\n"
                f"  • Attenuate below {fsl} and above {fsh} by ≥{att} dB")

    elif task == "notch":
        fn   = _fmt_freq_str(specs["f_notch"])
        bwl  = _fmt_freq_str(specs["bw_low"])
        bwh  = _fmt_freq_str(specs["bw_high"])
        fs   = _fmt_freq_str(specs["fs"])
        att  = specs["atten"]
        pb   = specs["pb_loss"]
        req = (f"  Type: notch filter\n"
               f"  Notch centre: {fn}\n"
               f"  Notch bandwidth (-3 dB): {bwl} – {bwh}\n"
               f"  Stopband sample (fs): {fs}  [min attenuation: {att} dB]\n"
               f"  Passband loss: ≤ {pb} dB")
        body = (f"Design a {topo_desc} notch filter meeting:\n"
                f"  • Notch at {fn} (−3 dB bandwidth: {bwl}–{bwh})\n"
                f"  • ≥{att} dB attenuation at {fs}\n"
                f"  • Passband loss ≤{pb} dB outside the notch")

    return f"{body}\n\nREQUIREMENTS:\n{req}\n  Topology: {topology}\n"


# ─────────────────────────────────────────────────────────────────────────────
# Spec collection (guided Q&A)
# ─────────────────────────────────────────────────────────────────────────────

FILTER_TASKS = {
    "1": "low_pass",  "lpf": "low_pass",  "low_pass": "low_pass",
    "2": "high_pass", "hpf": "high_pass", "high_pass": "high_pass",
    "3": "band_pass", "bpf": "band_pass", "band_pass": "band_pass",
    "4": "notch",     "notch": "notch",
}


def _single_stage_atten_db(ratio):
    """Attenuation of a single-pole RC at frequency ratio fs/fc (or fc/fs for HPF)."""
    return 10 * math.log10(1 + ratio ** 2)


def infer_topology(task, specs):
    """
    Select topology purely from the spec requirements:
      - If single-stage RC can meet the stopband → rc_single
      - If two stages are needed → buffered_rc_multi (buffered outperforms rc_multi
        across all filter types in empirical results)
      - Notch always uses buffered_rc_single (buffer prevents loading the Twin-T)
    Returns (topology, reason_str).
    """
    if task == "notch":
        return "buffered_rc_single", "Twin-T with output buffer (best notch depth)"

    att = specs.get("atten", 40.0)

    if task == "low_pass":
        ratio = specs["fs"] / specs["fc"]
        att1  = _single_stage_atten_db(ratio)
        if att1 >= att:
            return "rc_single", f"1-stage RC gives {att1:.0f} dB at fs — sufficient"
        return "buffered_rc_multi", f"1-stage only gives {att1:.0f} dB at fs, need 2-stage"

    if task == "high_pass":
        ratio = specs["fc"] / specs["fs"]
        att1  = _single_stage_atten_db(ratio)
        if att1 >= att:
            return "rc_single", f"1-stage RC gives {att1:.0f} dB at fs — sufficient"
        return "buffered_rc_multi", f"1-stage only gives {att1:.0f} dB at fs, need 2-stage"

    if task == "band_pass":
        # Check the tighter of the two transition edges
        ratio_low  = specs["fc_low"]  / specs["fs_low"]   # HPF side
        ratio_high = specs["fs_high"] / specs["fc_high"]  # LPF side
        att1 = min(_single_stage_atten_db(ratio_low),
                   _single_stage_atten_db(ratio_high))
        if att1 >= att:
            return "rc_single", f"1-stage RC gives ≥{att1:.0f} dB at both stopband edges"
        return "buffered_rc_multi", f"1-stage only gives {att1:.0f} dB at tighter edge, need 2-stage"

    return "rc_single", "default"


def collect_specs():
    """Interactively collect filter specs. Returns (task, specs) or None to quit."""
    print()
    _hr()
    print("  Filter type:")
    print("    1) Low-pass      2) High-pass")
    print("    3) Band-pass     4) Notch")
    raw = _ask("Choice", default="1")
    if raw.lower() in ("q", "quit", "exit"):
        return None
    task = FILTER_TASKS.get(raw.lower())
    if not task:
        print("  Invalid choice."); return None

    print()
    specs = {}
    if task == "low_pass":
        specs["fc"]      = _ask_freq("Passband edge (fc)")
        specs["pb_loss"] = _ask_float("Max passband loss (dB)", default=1.0)
        specs["fs"]      = _ask_freq("Stopband edge (fs)")
        specs["atten"]   = _ask_float("Min attenuation at fs (dB)", default=40.0)

    elif task == "high_pass":
        specs["fc"]      = _ask_freq("Passband edge (fc)")
        specs["pb_loss"] = _ask_float("Max passband loss (dB)", default=1.0)
        specs["fs"]      = _ask_freq("Stopband edge (fs) [must be < fc]")
        specs["atten"]   = _ask_float("Min attenuation at fs (dB)", default=40.0)

    elif task == "band_pass":
        specs["fc_low"]  = _ask_freq("Lower passband edge (fc_low)")
        specs["fc_high"] = _ask_freq("Upper passband edge (fc_high)")
        specs["pb_loss"] = _ask_float("Max passband loss (dB)", default=3.0)
        specs["fs_low"]  = _ask_freq("Lower stopband edge (fs_low) [< fc_low]")
        specs["fs_high"] = _ask_freq("Upper stopband edge (fs_high) [> fc_high]")
        specs["atten"]   = _ask_float("Min attenuation at stopband edges (dB)", default=40.0)

    elif task == "notch":
        specs["f_notch"] = _ask_freq("Notch centre frequency")
        specs["bw_low"]  = _ask_freq("Lower −3 dB edge")
        specs["bw_high"] = _ask_freq("Upper −3 dB edge")
        specs["fs"]      = _ask_freq("Stopband sample frequency [≈ notch centre]")
        specs["atten"]   = _ask_float("Min attenuation at fs (dB)", default=40.0)
        specs["pb_loss"] = _ask_float("Max passband loss (dB)", default=1.0)

    return task, specs


# ─────────────────────────────────────────────────────────────────────────────
# Frequency response plot
# ─────────────────────────────────────────────────────────────────────────────

def plot_frequency_response(ac_data, params, task_type, topology,
                            metrics, timestamp):
    if not ac_data:
        print("  (no AC data to plot)")
        return None

    freqs = sorted(ac_data.keys())
    mags  = [ac_data[f] for f in freqs]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.semilogx(freqs, mags, color="#1565C0", linewidth=2, zorder=4)

    ax.set_xlabel("Frequency (Hz)", fontsize=12)
    ax.set_ylabel("Magnitude (dB)", fontsize=12)
    ax.grid(True, which="both", alpha=0.3, linestyle="--")
    ax.grid(True, which="major", alpha=0.5)

    # ── Spec overlays ────────────────────────────────────────────────────────
    ymin, ymax = ax.get_ylim()
    ymin = min(ymin, min(mags) - 5)

    if task_type in ("low_pass_filter", "high_pass_filter"):
        fc   = params.get("fc_hz")
        fs   = params.get("fs_hz")
        pb   = params.get("pb_loss_db", 3)
        att  = params.get("atten_db", 40)
        is_lpf = task_type == "low_pass_filter"

        # Shaded passband region
        if is_lpf:
            ax.axvspan(freqs[0], fc, alpha=0.08, color="green", label="Passband")
            ax.axvspan(fs, freqs[-1], alpha=0.08, color="red", label="Stopband")
        else:
            ax.axvspan(fc, freqs[-1], alpha=0.08, color="green", label="Passband")
            ax.axvspan(freqs[0], fs, alpha=0.08, color="red", label="Stopband")

        ax.axhline(-pb,  color="green", linewidth=1.2, linestyle="--",
                   label=f"Max passband loss: −{pb} dB")
        ax.axhline(-att, color="red",   linewidth=1.2, linestyle="--",
                   label=f"Min attenuation: −{att} dB")
        if fc:
            ax.axvline(fc, color="green", linewidth=1, linestyle=":",
                       label=f"fc = {_fmt_hz(fc)}")
        if fs:
            ax.axvline(fs, color="red", linewidth=1, linestyle=":",
                       label=f"fs = {_fmt_hz(fs)}")

        # Measured cutoff marker
        fc_meas = metrics.get("cutoff_freq_hz_measured")
        if fc_meas:
            ax.axvline(fc_meas, color="#1565C0", linewidth=1.5, linestyle="-.",
                       label=f"Measured −3 dB: {_fmt_hz(fc_meas)}")

    elif task_type == "band_pass_filter":
        fcl  = params.get("fc_low_hz")
        fch  = params.get("fc_high_hz")
        fsl  = params.get("fs_low_hz")
        fsh  = params.get("fs_high_hz")
        pb   = params.get("pb_loss_db", 3)
        att  = params.get("atten_low_db", 40)

        if fcl and fch:
            ax.axvspan(fcl, fch, alpha=0.08, color="green", label="Passband")
        if fsl:
            ax.axvspan(freqs[0], fsl, alpha=0.08, color="red")
        if fsh:
            ax.axvspan(fsh, freqs[-1], alpha=0.08, color="red", label="Stopband")
        ax.axhline(-pb,  color="green", linewidth=1.2, linestyle="--",
                   label=f"Max passband loss: −{pb} dB")
        ax.axhline(-att, color="red",   linewidth=1.2, linestyle="--",
                   label=f"Min attenuation: −{att} dB")
        for f, lbl in [(fcl, "fc_low"), (fch, "fc_high"), (fsl, "fs_low"), (fsh, "fs_high")]:
            if f:
                ax.axvline(f, color="gray", linewidth=0.8, linestyle=":")

    elif task_type == "notch_filter":
        fn   = params.get("f_notch_hz")
        fs   = params.get("fs_low_hz") or params.get("fs_high_hz")
        att  = params.get("notch_depth_db", 40)
        pb   = params.get("pb_loss_db", 1)

        if fn:
            ax.axvline(fn, color="#C62828", linewidth=1.5, linestyle="--",
                       label=f"Notch centre: {_fmt_hz(fn)}")
        ax.axhline(-att, color="red",   linewidth=1.2, linestyle="--",
                   label=f"Required depth: −{att} dB")
        ax.axhline(-pb,  color="green", linewidth=1.2, linestyle="--",
                   label=f"Max passband loss: −{pb} dB")

    # ── Spec met annotation ───────────────────────────────────────────────────
    spec_met = metrics.get("filter_response_match", False)
    colour   = "#2E7D32" if spec_met else "#C62828"
    label    = "✓  Specification MET" if spec_met else "✗  Specification NOT met"
    ax.text(0.02, 0.04, label, transform=ax.transAxes,
            fontsize=11, color=colour, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=colour, alpha=0.9))

    topo_nice = topology.replace("_", " ").title()
    ftype_nice = task_type.replace("_filter", "").replace("_", "-").title()
    ax.set_title(f"Frequency Response — {ftype_nice} ({topo_nice})", fontsize=13)
    ax.legend(fontsize=8.5, loc="lower left", framealpha=0.9)
    ax.set_ylim(bottom=ymin)

    out_path = CHAT_OUT / f"response_{timestamp}.png"
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# Result display
# ─────────────────────────────────────────────────────────────────────────────

def print_result(result, plot_path):
    print()
    _hr("═")
    iters = result["iterations"]
    final = iters[-1]
    metrics  = final.get("metrics", {})
    spec_met = result["final_spec_met"]
    task_type = result["task_type"]
    params    = result["params"]

    status = "✓  ALL SPECIFICATIONS MET" if spec_met else "✗  Specifications NOT fully met"
    colour = "\033[92m" if spec_met else "\033[91m"
    print(f"  {colour}{status}\033[0m")
    print(f"  Iterations used: {result['iterations_used']} / {MAX_ITERS}")
    print(f"  Total time:      {result['generation_time_s']:.1f}s")
    print()

    # Per-type metric summary
    if task_type in ("low_pass_filter", "high_pass_filter"):
        fc_m  = metrics.get("cutoff_freq_hz_measured")
        fc_t  = params.get("fc_hz")
        loss  = metrics.get("loss_at_fc_db")
        pb_r  = params.get("pb_loss_db")
        atten = metrics.get("attenuation_at_fs", {})
        if fc_m and fc_t:
            err = abs(fc_m - fc_t) / fc_t * 100
            print(f"  Cutoff (measured): {_fmt_hz(fc_m)}  (target {_fmt_hz(fc_t)}, error {err:.1f}%)")
        if loss is not None:
            ok = "✓" if (pb_r is None or loss <= pb_r + 0.1) else "✗"
            print(f"  Passband loss:     {loss:.2f} dB  / {pb_r} dB  {ok}")
        if atten:
            ok = "✓" if atten.get("met") else "✗"
            print(f"  Stopband atten:    {atten.get('achieved_db', 0):.1f} dB"
                  f"  / {atten.get('required_db', 0):.1f} dB  {ok}")

    elif task_type == "band_pass_filter":
        for key, lbl in [("cutoff_freq_low_hz_measured","Lower −3dB"),
                          ("cutoff_freq_high_hz_measured","Upper −3dB")]:
            fc_m = metrics.get(key)
            fc_t = params.get("fc_low_hz" if "low" in key else "fc_high_hz")
            if fc_m and fc_t:
                err = abs(fc_m - fc_t) / fc_t * 100
                print(f"  {lbl}: {_fmt_hz(fc_m)}  (target {_fmt_hz(fc_t)}, error {err:.1f}%)")

    elif task_type == "notch_filter":
        depth = metrics.get("notch_depth_peak_db") or metrics.get("notch_depth_db")
        req   = params.get("notch_depth_db")
        if depth is not None:
            ok = "✓" if (req is None or depth >= req - 0.1) else "✗"
            print(f"  Notch depth:       {depth:.1f} dB  / {req:.1f} dB  {ok}")

    # Netlist
    netlist = result.get("generated_netlist", "")
    if netlist:
        print()
        _hr()
        print("  Generated Netlist:")
        _hr()
        for line in netlist.splitlines():
            print(f"    {line}")

    # Plot
    if plot_path:
        print()
        _hr()
        print(f"  Frequency response plot saved to:")
        print(f"    {plot_path}")
    _hr("═")


# ─────────────────────────────────────────────────────────────────────────────
# Main chat loop
# ─────────────────────────────────────────────────────────────────────────────

def main():
    _banner()

    print("  Loading model (this may take ~20 seconds)...")
    t0 = time.time()
    model, tokenizer = load_model()
    print(f"  Model ready in {time.time()-t0:.1f}s\n")

    while True:
        result_data = collect_specs()
        if result_data is None:
            print("\n  Goodbye!\n")
            break
        task, specs = result_data

        topology, reason = infer_topology(task, specs)
        topo_nice = topology.replace("_", " ").title()
        print()
        print(f"  Topology selected: {topo_nice}")
        print(f"  Reason: {reason}")

        prompt = build_prompt(task, topology, specs)

        print()
        _hr()
        print("  Designing filter ...")

        entry = {"task": task, "topology": topology, "prompt": prompt, "netlist": ""}
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        result = agentic_loop(model, tokenizer, entry, idx=0,
                              max_iters=MAX_ITERS, verbose=True)

        # Re-run NGSpice on the final netlist to get AC data for plotting
        plot_path = None
        final_netlist = result.get("generated_netlist")
        task_type     = result["task_type"]
        params        = result["params"]

        if final_netlist and result.get("simulation_converged"):
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    data_file = os.path.join(tmp, "ac_data.txt")
                    spice = build_spice_file(final_netlist, params, task_type, data_file)
                    _, _, rc = run_ngspice(spice, tmp)
                    if rc == 0:
                        ac_data = parse_ac_results(data_file)
                        metrics = calculate_metrics(ac_data, params, task_type) if ac_data else {}
                        plot_path = plot_frequency_response(
                            ac_data, params, task_type, topology, metrics, timestamp
                        )
            except Exception as e:
                print(f"\n  (plot failed: {e})")

        print_result(result, plot_path)

        print()
        again = input("  Design another filter? [y/n]: ").strip().lower()
        if again not in ("y", "yes"):
            print("\n  Goodbye!\n")
            break


if __name__ == "__main__":
    main()
