"""
agentic_pipeline.py — Agentic LLM Netlist Generation & NGSpice Evaluation Pipeline

For each circuit specification, runs a simulation-feedback loop:
  1. LLM generates initial netlist from the spec prompt
  2. Run NGSpice simulation and measure the actual frequency response
  3. If spec not met (or simulation failed / parse failed), feed structured
     feedback back to the LLM so it can revise its netlist
  4. Repeat up to --max-iters times (default 5)
  5. Record all iterations and the final result per entry

Imports shared code (model loading, SPICE building, simulation, metrics)
directly from pipeline.py — no duplication.

Usage:
    python agentic_pipeline.py --datasets lpf --limit 100
    python agentic_pipeline.py --datasets lpf,hpf --max-iters 5 --limit 50
    python agentic_pipeline.py --datasets lpf --limit 10 --max-iters 3 --verbose

Output:
    Project_Baseline/output/agentic_results_<ds>_<timestamp>.json   per dataset
    Project_Baseline/output/agentic_summary_<timestamp>.json
    Project_Baseline/output/agentic_progress.txt                    live progress
"""

import argparse
import json
import math
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

import torch

# Import all shared utilities from pipeline.py (importable because
# pipeline.py guards its main() with  if __name__ == "__main__":)
from pipeline import (
    load_model,
    extract_netlist,
    validate_netlist,
    build_spice_file,
    run_ngspice,
    parse_ac_results,
    calculate_metrics,
    SYSTEM_PROMPT,
    MODEL_ID,
    NGSPICE_PATH,
    DATA_DIR,
    OUTPUT_DIR,
    DATASET_FILES,
    TEMPERATURE,
)

# ---------------------------------------------------------------------------
# CHAIN-OF-THOUGHT SYSTEM PROMPT
# ---------------------------------------------------------------------------
# Replaces the one-shot SYSTEM_PROMPT from pipeline.py.
# Forces the model to show its component-value calculations before writing
# the netlist, so the computed values are in context when the SPICE lines
# are generated — the single biggest expected improvement over the baseline.
COT_SYSTEM_PROMPT = """\
You are a circuit design assistant specialized in SPICE netlist generation.

Before writing any SPICE, you MUST reason through the design step by step.

══ STEP 1 — DETERMINE FILTER ORDER ══
From the required rolloff or attenuation spec, decide how many poles you need:
  20 dB/decade  →  1st-order  (one RC stage)
  40 dB/decade  →  2nd-order  (Sallen-Key or two cascaded RC stages)
  60 dB/decade  →  3rd-order
  80 dB/decade  →  4th-order  (two cascaded 2nd-order stages)
Write: "I need a [N]th-order [low-pass / high-pass / band-pass / notch] filter."

══ STEP 2 — COMPUTE COMPONENT VALUES ══
Work out the required R and C numerically. Show every calculation.
For a single-pole RC stage: fc = 1 / (2π·R·C)  →  R·C = 1 / (2π·fc)
  • Choose a resistor value (e.g. R = 10 kΩ)
  • Compute C = 1 / (2π · fc · R) and write the result in nF or µF
  • If you need multiple stages, compute values for each stage separately.
Write: "R·C = 1/(2π·[fc Hz]) = [value] s. With R = [value], C = [value]."

══ STEP 3 — WRITE THE NETLIST ══
After your calculations, output the SPICE netlist in a ```spice ... ``` block.

MANDATORY NODE NAMES — use these exact strings:
  VIN  = the input node  (do NOT create a component named VIN)
  VOUT = the output node (the last node of your filter chain MUST be VOUT)
  GND  = ground / 0 V reference

VOLTAGE SOURCE — always write the AC stimulus exactly like this:
  V1 VIN GND AC 1

COMPONENT NAMING: resistors R1, R2, …; capacitors C1, C2, …; op-amp U1.

OP-AMP — if needed, use subcircuit OPAMP_IDEAL with five pins: INP INN VCC VEE OUT.
  Instance line: U1 node_inp node_inn VCC VEE node_out OPAMP_IDEAL
  Do NOT define .SUBCKT OPAMP_IDEAL — it is provided externally.
  Do NOT add VCC or VEE power supply sources — they are handled externally.

Do NOT write 'GND 0' or any standalone ground declaration.
End the netlist with .END. Do NOT include .AC, .TRAN, or any simulation commands.\
"""

# ---------------------------------------------------------------------------
# AGENTIC CONFIG
# ---------------------------------------------------------------------------
MAX_ITERS       = 5      # max simulation-feedback rounds per entry
# Extra tokens to accommodate CoT reasoning before the netlist
MAX_NEW_TOKENS  = 1024

_SCRIPT_DIR        = Path(__file__).parent
AGENTIC_OUTPUT_DIR = _SCRIPT_DIR / "agentic_output"

_agentic_start_time = None


# ---------------------------------------------------------------------------
# SINGLE-TURN GENERATION WITH FULL CONVERSATION HISTORY
# ---------------------------------------------------------------------------

def generate_with_history(model, tokenizer, messages: list):
    """
    Run inference on a full multi-turn conversation (system + alternating user/assistant).
    Unlike generate_batch, this is always a single sequence because each entry
    has its own evolving conversation state.

    Returns (response_text, tokens_generated, elapsed_s).
    """
    text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = tokenizer(text, return_tensors="pt").to(model.device)
    input_len = inputs.input_ids.shape[1]

    t0 = time.time()
    with torch.no_grad():
        output = model.generate(
            input_ids=inputs.input_ids,
            attention_mask=inputs.attention_mask,
            max_new_tokens=MAX_NEW_TOKENS,
            temperature=TEMPERATURE,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
        )
    elapsed = time.time() - t0

    generated_ids = output[0][input_len:]
    tokens_gen = int((generated_ids != tokenizer.eos_token_id).sum()) or generated_ids.shape[0]
    reply = tokenizer.decode(generated_ids, skip_special_tokens=True)
    return reply, tokens_gen, elapsed


# ---------------------------------------------------------------------------
# FEEDBACK MESSAGE BUILDERS
# ---------------------------------------------------------------------------

def _fmt_hz(hz):
    """Format a frequency value for display."""
    if hz is None:
        return "?"
    if hz >= 1e6:
        return f"{hz/1e6:.3g} MHz"
    if hz >= 1e3:
        return f"{hz/1e3:.4g} kHz"
    return f"{hz:.4g} Hz"


def _extract_rc_values(netlist: str) -> list:
    """
    Pull R and C component values from a SPICE netlist for display in feedback.
    Returns a list of strings like ["R1=10 kΩ", "C1=10 nF"].
    """
    results = []
    for line in (netlist or "").splitlines():
        line = line.strip()
        # Resistor: Rxxx  n1  n2  value
        m = re.match(r'^(R\S+)\s+\S+\s+\S+\s+(\S+)', line, re.IGNORECASE)
        if m:
            val = _fmt_component_val(m.group(2), "Ω")
            if val:
                results.append(f"{m.group(1).upper()}={val}")
        # Capacitor: Cxxx  n1  n2  value
        m = re.match(r'^(C\S+)\s+\S+\s+\S+\s+(\S+)', line, re.IGNORECASE)
        if m:
            val = _fmt_component_val(m.group(2), "F")
            if val:
                results.append(f"{m.group(1).upper()}={val}")
    return results


def _fmt_component_val(raw: str, unit: str) -> str:
    """Convert a SPICE component value string (e.g. '10k', '1e-9', '15n') to readable text."""
    raw = raw.strip().upper()
    # SPICE suffixes: T=1e12, G=1e9, MEG=1e6, K=1e3, M=1e-3, U=1e-6, N=1e-9, P=1e-12, F=1e-15
    suffix_map = {
        "T": 1e12, "G": 1e9, "MEG": 1e6, "K": 1e3,
        "M": 1e-3, "U": 1e-6, "N": 1e-9, "P": 1e-12, "F": 1e-15,
    }
    try:
        # Try plain float first (handles scientific notation)
        val = float(raw)
    except ValueError:
        # Try stripping suffix
        for suffix, multiplier in sorted(suffix_map.items(), key=lambda x: -len(x[0])):
            if raw.endswith(suffix):
                try:
                    val = float(raw[:-len(suffix)]) * multiplier
                    break
                except ValueError:
                    continue
        else:
            return ""  # unparseable

    if unit == "Ω":
        if val >= 1e6:
            return f"{val/1e6:.3g} MΩ"
        if val >= 1e3:
            return f"{val/1e3:.3g} kΩ"
        return f"{val:.3g} Ω"
    elif unit == "F":
        if val >= 1e-3:
            return f"{val*1e3:.3g} mF"
        if val >= 1e-6:
            return f"{val*1e6:.3g} µF"
        if val >= 1e-9:
            return f"{val*1e9:.3g} nF"
        if val >= 1e-12:
            return f"{val*1e12:.3g} pF"
        return f"{val:.3g} F"
    return f"{val:.3g}"


def _compute_rolloff_slope(metrics: dict, params: dict, task_type: str) -> tuple:
    """
    Estimate the measured roll-off slope in dB/decade between fc and fs,
    and compare against what the spec implies.
    Returns (achieved_db_per_dec, required_db_per_dec) or (None, None).
    """
    if task_type not in ("low_pass_filter", "high_pass_filter"):
        return None, None

    fc_meas = metrics.get("cutoff_freq_hz_measured")
    fc_spec = params.get("fc_hz")
    fs_spec = params.get("fs_hz")
    atten_req = params.get("atten_db")
    atten_at_fs = metrics.get("attenuation_at_fs", {})
    atten_meas = atten_at_fs.get("achieved_db")

    if not all([fc_meas, fs_spec, atten_meas]):
        return None, None

    try:
        decades = math.log10(fs_spec / fc_meas)
        if decades <= 0:
            return None, None
        achieved = atten_meas / decades
        required = (atten_req / math.log10(fs_spec / fc_spec)) if (atten_req and fc_spec) else None
        return round(achieved, 1), (round(required, 1) if required else None)
    except (ValueError, ZeroDivisionError):
        return None, None


def build_feedback_message(iteration: int, parse_success: bool,
                           sim_converged: bool, metrics: dict,
                           params: dict, task_type: str,
                           stderr: str = "",
                           prev_metrics: dict = None,
                           netlist: str = None,
                           formula_hints: bool = True) -> str:
    """
    Build the feedback message sent back to the LLM after one simulation attempt.

    prev_metrics:   metrics from the previous iteration — used to show progress.
    netlist:        the LLM's netlist this iteration — used to display component values.
    formula_hints:  if True, include equation-backed correction hints with computed
                    target values (full RAG-style guidance).
                    if False, direction-only hints (ablation baseline).
    """
    lines = [
        f"SIMULATION FEEDBACK — Iteration {iteration}",
        "=" * 50,
    ]

    # Show what component values the LLM used (helps it understand what it produced)
    if netlist:
        rc_vals = _extract_rc_values(netlist)
        if rc_vals:
            lines.append(f"Components in your iteration {iteration} netlist: {', '.join(rc_vals)}")
            lines.append("")

    # ------------------------------------------------------------------ #
    # Case 1: parse failure — LLM didn't produce a valid netlist block    #
    # ------------------------------------------------------------------ #
    if not parse_success:
        lines += [
            "Status: PARSE FAILED",
            "I could not extract a valid SPICE netlist from your response.",
            "",
            "Requirements:",
            "  • Wrap the entire netlist in a ```spice ... ``` code block",
            "  • The netlist MUST end with .END",
            "  • Include V1 VIN GND AC 1 as the AC stimulus source",
            "  • The output node MUST be named VOUT",
            "",
            "Please try again. Output ONLY the netlist in a ```spice ... ``` block.",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Case 2: simulation failed — NGSpice crashed or returned error       #
    # ------------------------------------------------------------------ #
    if not sim_converged:
        # Extract the most informative lines from NGSpice stderr
        error_lines = [
            l.strip() for l in stderr.splitlines()
            if any(kw in l.lower() for kw in ("error", "fatal", "singular", "convergence",
                                               "can't", "cannot", "mismatch", "syntax"))
        ][:6]
        error_block = "\n  ".join(error_lines) if error_lines else "(no specific error message)"

        lines += [
            "Status: SIMULATION FAILED",
            "NGSpice could not simulate your circuit.",
            "",
            f"NGSpice errors:\n  {error_block}",
            "",
            "Common causes and fixes:",
            "  • Floating node: every internal node needs a DC path to GND.",
            "    Add a large resistor (e.g. R_bleed node GND 1G) if needed.",
            "  • VOUT missing: your filter output must connect to a node named VOUT.",
            "  • Syntax error: check component lines; no spaces inside node names.",
            "  • V1 source must be: V1 VIN GND AC 1",
            "  • Do NOT define .SUBCKT OPAMP_IDEAL — it is provided externally.",
            "",
            "Please output a corrected netlist in a ```spice ... ``` block.",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Case 3: simulation succeeded — report measured vs required          #
    # ------------------------------------------------------------------ #
    spec_met = metrics.get("filter_response_match", False)

    if spec_met:
        lines += [
            "Status: ALL SPECIFICATIONS MET ✓",
            "",
            _format_measured_metrics(metrics, params, task_type),
            "",
            "No further revision needed.",
        ]
        return "\n".join(lines)

    # Spec not met — give detailed, actionable feedback
    lines += [
        "Status: SIMULATED SUCCESSFULLY — but specifications NOT met.",
        "",
        "=== Measured vs Required ===",
        _format_measured_metrics(metrics, params, task_type),
    ]

    # Roll-off slope diagnosis
    achieved_slope, required_slope = _compute_rolloff_slope(metrics, params, task_type)
    if achieved_slope is not None:
        lines.append("")
        lines.append("=== Roll-off Slope ===")
        lines.append(f"  Measured: {achieved_slope:.1f} dB/decade")
        if required_slope:
            lines.append(f"  Required: ≥{required_slope:.1f} dB/decade")
        if required_slope and achieved_slope < required_slope * 0.85:
            lines.append(f"  Your roll-off is too shallow ({achieved_slope:.0f} dB/decade achieved, "
                         f"≥{required_slope:.0f} dB/decade required).")
            lines.append(f"  Consider using a higher-order filter topology.")

    # Progress compared to previous iteration
    if prev_metrics is not None:
        lines.append("")
        lines.append("=== Progress vs Previous Iteration ===")
        prev_fc_err = (prev_metrics.get("cutoff_freq_error_pct")
                       or prev_metrics.get("cutoff_freq_low_error_pct"))
        curr_fc_err = (metrics.get("cutoff_freq_error_pct")
                       or metrics.get("cutoff_freq_low_error_pct"))
        if prev_fc_err is not None and curr_fc_err is not None:
            delta = prev_fc_err - curr_fc_err
            if delta > 1:
                lines.append(f"  Cutoff frequency error: {prev_fc_err:.1f}% → {curr_fc_err:.1f}%  "
                             f"(↓ {delta:.1f}% improvement — keep going in this direction!)")
            elif delta < -1:
                lines.append(f"  Cutoff frequency error: {prev_fc_err:.1f}% → {curr_fc_err:.1f}%  "
                             f"(↑ {-delta:.1f}% worse — you overcorrected, revert and adjust less aggressively)")
            else:
                lines.append(f"  Cutoff frequency error: {prev_fc_err:.1f}% → {curr_fc_err:.1f}%  "
                             f"(≈ no change — try a larger component value adjustment)")

    lines += [
        "",
        "=== How to Fix ===",
        (_build_correction_hint(metrics, params, task_type) if formula_hints
         else _build_correction_direction(metrics, params, task_type)),
        "",
        "Please output a revised netlist that meets all specifications.",
        "Output ONLY the netlist in a ```spice ... ``` block.",
    ]
    return "\n".join(lines)


def _format_measured_metrics(metrics: dict, params: dict, task_type: str) -> str:
    """Format what the simulation measured compared to what was required."""
    rows = []

    if task_type == "low_pass_filter":
        fc_spec  = params.get("fc_hz")
        fc_meas  = metrics.get("cutoff_freq_hz_measured")
        fc_err   = metrics.get("cutoff_freq_error_pct")
        atten    = metrics.get("attenuation_at_fs", {})

        if fc_meas and fc_spec:
            direction = "high" if fc_meas > fc_spec else "low"
            rows.append(f"  Cutoff (-3dB):  {_fmt_hz(fc_meas)} measured  |  "
                        f"target {_fmt_hz(fc_spec)}  |  error {fc_err:.1f}% too {direction}")
        if atten.get("required_db") is not None:
            met = "MET ✓" if atten.get("met") else "NOT MET ✗"
            rows.append(f"  Attenuation at {_fmt_hz(atten['fs_hz'])}: "
                        f"{atten['achieved_db']:.1f} dB measured  |  "
                        f"required ≥{atten['required_db']:.1f} dB  |  {met}")

    elif task_type == "high_pass_filter":
        fc_spec = params.get("fc_hz")
        fc_meas = metrics.get("cutoff_freq_hz_measured")
        fc_err  = metrics.get("cutoff_freq_error_pct")
        atten   = metrics.get("attenuation_at_fs", {})

        if fc_meas and fc_spec:
            direction = "high" if fc_meas > fc_spec else "low"
            rows.append(f"  Cutoff (-3dB):  {_fmt_hz(fc_meas)} measured  |  "
                        f"target {_fmt_hz(fc_spec)}  |  error {fc_err:.1f}% too {direction}")
        if atten.get("required_db") is not None:
            met = "MET ✓" if atten.get("met") else "NOT MET ✗"
            rows.append(f"  Attenuation at {_fmt_hz(atten['fs_hz'])}: "
                        f"{atten['achieved_db']:.1f} dB  |  required ≥{atten['required_db']:.1f} dB  |  {met}")

    elif task_type == "band_pass_filter":
        fc_low_spec  = params.get("fc_low_hz")
        fc_high_spec = params.get("fc_high_hz")
        fc_low_meas  = metrics.get("cutoff_freq_low_hz_measured")
        fc_high_meas = metrics.get("cutoff_freq_high_hz_measured")
        err_low      = metrics.get("cutoff_freq_low_error_pct")
        err_high     = metrics.get("cutoff_freq_high_error_pct")
        atten_low    = metrics.get("attenuation_at_fs_low",  {})
        atten_high   = metrics.get("attenuation_at_fs_high", {})

        if fc_low_meas and fc_low_spec:
            d = "high" if fc_low_meas > fc_low_spec else "low"
            rows.append(f"  Lower cutoff:  {_fmt_hz(fc_low_meas)} measured  |  "
                        f"target {_fmt_hz(fc_low_spec)}  |  error {err_low:.1f}% too {d}")
        if fc_high_meas and fc_high_spec:
            d = "high" if fc_high_meas > fc_high_spec else "low"
            rows.append(f"  Upper cutoff:  {_fmt_hz(fc_high_meas)} measured  |  "
                        f"target {_fmt_hz(fc_high_spec)}  |  error {err_high:.1f}% too {d}")
        for atten, label in [(atten_low, "lower stopband"), (atten_high, "upper stopband")]:
            if atten.get("required_db") is not None:
                met = "MET ✓" if atten.get("met") else "NOT MET ✗"
                rows.append(f"  Attenuation ({label}) at {_fmt_hz(atten['fs_hz'])}: "
                            f"{atten['achieved_db']:.1f} dB  |  required ≥{atten['required_db']:.1f} dB  |  {met}")

    elif task_type == "notch_filter":
        f_notch    = params.get("f_notch_hz")
        depth_meas = metrics.get("notch_depth_db")
        depth_req  = params.get("notch_depth_db")

        if depth_meas is not None and f_notch:
            met = "MET ✓" if metrics.get("notch_depth_met", False) else "NOT MET ✗"
            rows.append(f"  Notch depth at {_fmt_hz(f_notch)}: "
                        f"{depth_meas:.1f} dB measured  |  required ≥{depth_req:.1f} dB  |  {met}")
        for atten, label in [
            (metrics.get("attenuation_at_fs_low",  {}), "lower passband"),
            (metrics.get("attenuation_at_fs_high", {}), "upper passband"),
        ]:
            if atten.get("required_db") is not None:
                met = "MET ✓" if atten.get("met") else "NOT MET ✗"
                rows.append(f"  Attenuation ({label}) at {_fmt_hz(atten['fs_hz'])}: "
                            f"{atten['achieved_db']:.1f} dB  |  required ≥{atten['required_db']:.1f} dB  |  {met}")

    return "\n".join(rows) if rows else "  (no detailed measurements available)"


def _build_correction_direction(metrics: dict, params: dict, task_type: str) -> str:
    """
    Direction-only hints — no formulas, no computed values.
    Used when formula hints are disabled (ablation mode).
    """
    hints = []

    if task_type in ("low_pass_filter", "high_pass_filter"):
        fc_spec = params.get("fc_hz")
        fc_meas = metrics.get("cutoff_freq_hz_measured")
        if fc_spec and fc_meas:
            direction = "HIGH" if fc_meas > fc_spec else "LOW"
            action    = "INCREASE" if fc_meas > fc_spec else "DECREASE"
            hints.append(f"  Your cutoff frequency is too {direction}.")
            hints.append(f"  Action: {action} your resistor or capacitor values to shift the cutoff.")
        atten = metrics.get("attenuation_at_fs", {})
        if not atten.get("met") and atten.get("required_db"):
            hints.append("  Your stopband attenuation is insufficient.")
            hints.append("  Action: Consider using a higher-order filter topology.")

    elif task_type == "band_pass_filter":
        fc_low_spec  = params.get("fc_low_hz")
        fc_high_spec = params.get("fc_high_hz")
        fc_low_meas  = metrics.get("cutoff_freq_low_hz_measured")
        fc_high_meas = metrics.get("cutoff_freq_high_hz_measured")
        if fc_low_meas and fc_low_spec:
            d = "HIGH — shift the lower edge down" if fc_low_meas > fc_low_spec else "LOW — shift the lower edge up"
            hints.append(f"  Your lower cutoff is too {d}.")
        if fc_high_meas and fc_high_spec:
            d = "HIGH — shift the upper edge down" if fc_high_meas > fc_high_spec else "LOW — shift the upper edge up"
            hints.append(f"  Your upper cutoff is too {d}.")
        atten_low  = metrics.get("attenuation_at_fs_low", {})
        atten_high = metrics.get("attenuation_at_fs_high", {})
        if not atten_low.get("met") or not atten_high.get("met"):
            hints.append("  Stopband attenuation not met — consider a higher-order topology.")

    elif task_type == "notch_filter":
        depth_meas = metrics.get("notch_depth_db")
        depth_req  = params.get("notch_depth_db")
        if depth_meas is not None and depth_req is not None and depth_meas < depth_req:
            hints.append("  Your notch depth is insufficient.")
            hints.append("  Action: Check that your component ratios are precise.")
        for key in ("attenuation_at_fs_low", "attenuation_at_fs_high"):
            if not metrics.get(key, {}).get("met"):
                hints.append("  Passband attenuation not met — check passband components.")
                break

    return "\n".join(hints) if hints else "  Adjust component values to meet the target specifications."


def _build_correction_hint(metrics: dict, params: dict, task_type: str) -> str:
    """
    Formula-backed correction hints including computed target values and example components.
    Mirrors what the RAG formula sheet will provide — use this variant when formula hints
    are enabled (--formula-hints flag).
    """
    hints = []

    if task_type in ("low_pass_filter", "high_pass_filter"):
        fc_spec = params.get("fc_hz")
        fc_meas = metrics.get("cutoff_freq_hz_measured")
        if fc_spec and fc_meas:
            rc_needed  = 1.0 / (2.0 * math.pi * fc_spec)
            rc_current = 1.0 / (2.0 * math.pi * fc_meas)
            ratio      = fc_meas / fc_spec
            hints.append(f"  Key formula: fc = 1/(2π·R·C)  →  R·C = 1/(2π·fc)")
            hints.append(f"  Your circuit: R·C = {rc_current:.4e} s  (gives fc = {_fmt_hz(fc_meas)})")
            hints.append(f"  Required:     R·C = {rc_needed:.4e} s  (for fc = {_fmt_hz(fc_spec)})")
            action = "INCREASE" if ratio > 1 else "DECREASE"
            factor = ratio if ratio > 1 else 1.0 / ratio
            hints.append(f"  Action: {action} R or C by a factor of {factor:.2f}x")
            hints.append(f"  Example component values for fc = {_fmt_hz(fc_spec)}:")
            for r_ohm, r_label in [(1e3, "1 kΩ"), (10e3, "10 kΩ"), (100e3, "100 kΩ")]:
                c_f = rc_needed / r_ohm
                if 1e-12 < c_f < 1e-3:
                    c_label = (f"{c_f*1e6:.2f} µF" if c_f >= 1e-6
                               else f"{c_f*1e9:.2f} nF" if c_f >= 1e-9
                               else f"{c_f*1e12:.2f} pF")
                    hints.append(f"    R = {r_label}  →  C = {c_label}")
        atten = metrics.get("attenuation_at_fs", {})
        if not atten.get("met") and atten.get("required_db"):
            req   = atten["required_db"]
            fs    = atten.get("fs_hz", params.get("fs_hz"))
            fc    = params.get("fc_hz", 1)
            if fs and fc:
                decades = math.log10(fs / fc)
                min_order = math.ceil(req / (20 * decades))
                hints.append(f"  Attenuation shortfall: need {req:.0f} dB over {decades:.1f} decades "
                             f"→ minimum filter order ≈ {min_order}")

    elif task_type == "band_pass_filter":
        fc_low_spec  = params.get("fc_low_hz")
        fc_high_spec = params.get("fc_high_hz")
        fc_low_meas  = metrics.get("cutoff_freq_low_hz_measured")
        fc_high_meas = metrics.get("cutoff_freq_high_hz_measured")
        if fc_low_spec and fc_high_spec:
            f0   = math.sqrt(fc_low_spec * fc_high_spec)
            bw   = fc_high_spec - fc_low_spec
            q    = f0 / bw
            rc   = 1.0 / (2.0 * math.pi * f0)
            hints.append(f"  Centre frequency: f0 = √(fc_low·fc_high) = {_fmt_hz(f0)}")
            hints.append(f"  Bandwidth: BW = fc_high − fc_low = {_fmt_hz(bw)}")
            hints.append(f"  Quality factor: Q = f0/BW = {q:.2f}")
            hints.append(f"  Required R·C = 1/(2π·f0) = {rc:.4e} s")
            if fc_low_meas and fc_high_meas:
                f0_meas = math.sqrt(fc_low_meas * fc_high_meas)
                ratio   = f0_meas / f0
                action  = "INCREASE" if ratio > 1 else "DECREASE"
                factor  = ratio if ratio > 1 else 1.0 / ratio
                hints.append(f"  Your measured f0 = {_fmt_hz(f0_meas)} vs target {_fmt_hz(f0)}")
                hints.append(f"  Action: {action} R·C by {factor:.2f}x to shift f0")

    elif task_type == "notch_filter":
        f_notch   = params.get("f_notch_hz")
        depth_req = params.get("notch_depth_db")
        depth_meas = metrics.get("notch_depth_db")
        if f_notch:
            rc = 1.0 / (2.0 * math.pi * f_notch)
            hints.append(f"  Twin-T notch: use R·C = 1/(2π·f_notch) = {rc:.4e} s")
            hints.append(f"  Component ratios MUST be exact: R, R, R/2 and C, C, 2C")
            hints.append(f"  Example: R = 10 kΩ  →  C = {rc/10e3*1e9:.2f} nF, 2C = {2*rc/10e3*1e9:.2f} nF")
        if depth_meas is not None and depth_req is not None and depth_meas < depth_req:
            hints.append(f"  Notch depth {depth_meas:.1f} dB < required {depth_req:.1f} dB — "
                         f"precision of component ratios is critical for deep notches.")

    return "\n".join(hints) if hints else "  Adjust component values to meet the target specifications."


# ---------------------------------------------------------------------------
# AGENTIC LOOP — ONE ENTRY
# ---------------------------------------------------------------------------

def agentic_loop(model, tokenizer, entry: dict, idx: int,
                 source_file: str, max_iters: int = MAX_ITERS,
                 verbose: bool = False,
                 formula_hints: bool = True) -> dict:
    """
    Run the simulation-feedback loop for a single circuit specification.
    Returns a result dict containing all iteration records plus the final outcome.
    """
    task_type = entry.get("task_type", "unknown")
    params    = entry.get("params", {})
    prompt    = entry.get("prompt", "")

    # Initialise the conversation with CoT system prompt + user spec
    messages = [
        {"role": "system",  "content": COT_SYSTEM_PROMPT},
        {"role": "user",    "content": prompt},
    ]

    result = {
        "index":       idx,
        "source_file": source_file,
        "task_type":   task_type,
        "topology":    entry.get("topology", "unknown"),
        "params":      params,
        "prompt":      prompt,
        "iterations":  [],
    }

    total_gen_time    = 0.0
    total_tokens      = 0
    prev_metrics      = None   # track metrics from prior iteration for progress feedback
    feedback_messages = []     # collect for iteration log

    for iteration in range(1, max_iters + 1):

        # ---- LLM generation ----
        try:
            response, tokens, elapsed = generate_with_history(model, tokenizer, messages)
        except Exception as e:
            result["iterations"].append({
                "iteration": iteration, "error": f"LLM error: {e}",
                "parse_success": False, "simulation_converged": False, "spec_met": False,
            })
            break

        total_gen_time += elapsed
        total_tokens   += tokens

        if verbose:
            print(f"      iter {iteration}: generated {tokens} tokens in {elapsed:.1f}s")

        # ---- Append assistant turn so context carries forward ----
        messages.append({"role": "assistant", "content": response})

        # ---- Netlist extraction ----
        netlist       = extract_netlist(response)
        parse_success = netlist is not None

        # Capture the CoT reasoning text (everything before the ```spice block)
        cot_reasoning = ""
        spice_block_start = response.find("```spice") if response else -1
        if spice_block_start == -1:
            spice_block_start = response.find("```SPICE") if response else -1
        if spice_block_start > 0:
            cot_reasoning = response[:spice_block_start].strip()
        elif response and not parse_success:
            cot_reasoning = response.strip()

        iter_record  = {
            "iteration":          iteration,
            "generation_time_s":  round(elapsed, 3),
            "tokens_generated":   tokens,
            "parse_success":      parse_success,
            "cot_reasoning":      cot_reasoning,
            "generated_netlist":  netlist,
        }

        if not parse_success:
            iter_record.update({
                "simulation_converged": False,
                "metrics":  {},
                "spec_met": False,
            })
            result["iterations"].append(iter_record)
            feedback = build_feedback_message(
                iteration, False, False, {}, params, task_type
            )
            messages.append({"role": "user", "content": feedback})
            if verbose:
                print(f"      iter {iteration}: PARSE FAILED")
            continue

        iter_record["netlist_warnings"] = validate_netlist(netlist)

        # ---- NGSpice simulation ----
        sim_converged = False
        metrics       = {}
        stderr_text   = ""

        with tempfile.TemporaryDirectory() as tmp_dir:
            data_file    = os.path.join(tmp_dir, "ac_out.txt")
            spice_content = build_spice_file(netlist, params, task_type, data_file)
            iter_record["spice_file_content"] = spice_content

            try:
                data_path, stderr_text, returncode = run_ngspice(spice_content, tmp_dir)
                sim_converged = (returncode == 0)
                iter_record["ngspice_returncode"] = returncode
                iter_record["ngspice_stderr"]     = stderr_text[:1500]

                if sim_converged:
                    ac_data = parse_ac_results(data_path)
                    if ac_data:
                        metrics = calculate_metrics(ac_data, params, task_type)

            except subprocess.TimeoutExpired:
                iter_record["error"] = "NGSpice timeout"
            except FileNotFoundError:
                iter_record["error"] = f"NGSpice not found at '{NGSPICE_PATH}'"

        iter_record["simulation_converged"] = sim_converged
        iter_record["metrics"]              = metrics
        spec_met = metrics.get("filter_response_match", False)
        iter_record["spec_met"]             = spec_met
        result["iterations"].append(iter_record)

        if verbose:
            status = ("SPEC MET" if spec_met
                      else "converged, spec missed" if sim_converged
                      else "SIM FAILED")
            print(f"      iter {iteration}: {status}")

        # ---- Done if spec met ----
        if spec_met:
            break

        # ---- Build feedback for next iteration (if not last) ----
        if iteration < max_iters:
            feedback = build_feedback_message(
                iteration, parse_success, sim_converged,
                metrics, params, task_type,
                stderr=stderr_text,
                prev_metrics=prev_metrics,
                netlist=netlist,
                formula_hints=formula_hints,
            )
            messages.append({"role": "user", "content": feedback})
            feedback_messages.append(feedback)

        # Carry forward metrics for next iteration's progress comparison
        if sim_converged and metrics:
            prev_metrics = metrics

    # ---- Summarise final state ----
    final = result["iterations"][-1] if result["iterations"] else {}
    result["total_iterations"]         = len(result["iterations"])
    result["total_generation_time_s"]  = round(total_gen_time, 3)
    result["total_tokens_generated"]   = total_tokens
    result["final_spec_met"]           = final.get("spec_met", False)
    result["final_parse_success"]      = final.get("parse_success", False)
    result["final_simulation_converged"] = final.get("simulation_converged", False)
    result["final_metrics"]            = final.get("metrics", {})
    result["final_netlist"]            = final.get("generated_netlist")

    # Track improvement: compare fc_error iteration 1 vs final
    if len(result["iterations"]) >= 2:
        def _fc_err(rec):
            m = rec.get("metrics", {})
            return m.get("cutoff_freq_error_pct") or m.get("cutoff_freq_low_error_pct")

        err_1 = _fc_err(result["iterations"][0])
        err_f = _fc_err(final)
        result["fc_error_improvement"] = {
            "iter1_pct":  round(err_1, 2) if err_1 is not None else None,
            "final_pct":  round(err_f, 2) if err_f is not None else None,
            "improved":   (err_1 is not None and err_f is not None and err_f < err_1),
        }

    result["_feedback_messages"] = feedback_messages   # kept for iteration log, not in summary
    return result


# ---------------------------------------------------------------------------
# ITERATION LOG  (human-readable, appended after each entry)
# ---------------------------------------------------------------------------

def _fmt_params(params: dict, task_type: str) -> str:
    """One-line summary of the circuit specification."""
    p = params
    if task_type == "low_pass_filter":
        return (f"fc={_fmt_hz(p.get('fc_hz'))}  fs={_fmt_hz(p.get('fs_hz'))}  "
                f"atten≥{p.get('atten_db','?')}dB  rolloff={p.get('rolloff_dbpdec','?')}dB/dec")
    if task_type == "high_pass_filter":
        return (f"fc={_fmt_hz(p.get('fc_hz'))}  fs={_fmt_hz(p.get('fs_hz'))}  "
                f"atten≥{p.get('atten_db','?')}dB")
    if task_type == "band_pass_filter":
        return (f"fc_low={_fmt_hz(p.get('fc_low_hz'))}  fc_high={_fmt_hz(p.get('fc_high_hz'))}  "
                f"atten_low≥{p.get('atten_low_db','?')}dB  atten_high≥{p.get('atten_high_db','?')}dB")
    if task_type == "notch_filter":
        return (f"f_notch={_fmt_hz(p.get('f_notch_hz'))}  "
                f"depth≥{p.get('notch_depth_db','?')}dB")
    return str(p)


def _fmt_iter_metrics(metrics: dict, task_type: str) -> str:
    """One-line metric summary for a single iteration."""
    if not metrics:
        return "(no metrics)"
    parts = []
    if task_type in ("low_pass_filter", "high_pass_filter"):
        fc_meas = metrics.get("cutoff_freq_hz_measured")
        fc_err  = metrics.get("cutoff_freq_error_pct")
        if fc_meas:
            parts.append(f"fc_meas={_fmt_hz(fc_meas)}")
        if fc_err is not None:
            parts.append(f"fc_err={fc_err:.1f}%")
        atten = metrics.get("attenuation_at_fs", {})
        if atten:
            parts.append(f"atten={atten.get('achieved_db','?'):.1f}/{atten.get('required_db','?')}dB")
    elif task_type == "band_pass_filter":
        fl = metrics.get("cutoff_freq_low_hz_measured")
        fh = metrics.get("cutoff_freq_high_hz_measured")
        if fl:
            parts.append(f"fc_low={_fmt_hz(fl)}  err={metrics.get('cutoff_freq_low_error_pct',0):.1f}%")
        if fh:
            parts.append(f"fc_high={_fmt_hz(fh)}  err={metrics.get('cutoff_freq_high_error_pct',0):.1f}%")
    elif task_type == "notch_filter":
        d = metrics.get("notch_depth_db")
        if d is not None:
            parts.append(f"notch_depth={d:.1f}dB")
    ripple = metrics.get("passband_ripple_db")
    if ripple is not None:
        parts.append(f"ripple={ripple:.1f}dB")
    return "  ".join(parts) if parts else "(no key metrics)"


def append_iteration_log(log_path: Path, result: dict, feedback_messages: list):
    """
    Append a human-readable record of one entry's agentic loop to the log file.
    feedback_messages: list of feedback strings sent after each non-final iteration,
                       indexed to match result['iterations'][i].
    """
    task_type = result.get("task_type", "?")
    params    = result.get("params", {})
    sep       = "-" * 70

    lines = [
        "",
        "=" * 70,
        f"Entry {result['index']}  |  {task_type}  |  topology={result.get('topology','?')}",
        f"Spec: {_fmt_params(params, task_type)}",
        f"Prompt: {result.get('prompt','')[:120]}{'...' if len(result.get('prompt',''))>120 else ''}",
        "=" * 70,
    ]

    for it in result.get("iterations", []):
        n     = it["iteration"]
        parse = it.get("parse_success", False)
        conv  = it.get("simulation_converged", False)
        met   = it.get("spec_met", False)
        rc    = _extract_rc_values(it.get("generated_netlist") or "")

        status = ("✓ SPEC MET" if met
                  else "converged" if conv
                  else "SIM FAILED" if parse
                  else "PARSE FAILED")

        lines += [
            f"  Iteration {n}  [{status}]  {it.get('generation_time_s',0):.1f}s  {it.get('tokens_generated',0)} tok",
        ]
        cot = it.get("cot_reasoning", "").strip()
        if cot:
            lines.append(f"    Reasoning:")
            for cot_line in cot.splitlines()[:12]:   # cap at 12 lines to keep log readable
                lines.append(f"      {cot_line}")
            if len(cot.splitlines()) > 12:
                lines.append(f"      ... ({len(cot.splitlines())-12} more lines)")
        if rc:
            lines.append(f"    Components: {', '.join(rc)}")
        if parse and conv:
            lines.append(f"    Metrics:    {_fmt_iter_metrics(it.get('metrics',{}), task_type)}")
        if parse and not conv:
            stderr_snip = (it.get("ngspice_stderr") or "")[:200].replace("\n", " | ")
            lines.append(f"    NGSpice:    {stderr_snip}")

        # Append the feedback that was sent after this iteration (if not the last)
        fb_idx = n - 1
        if fb_idx < len(feedback_messages) and not met:
            lines.append(f"    Feedback sent:")
            for fb_line in feedback_messages[fb_idx].splitlines():
                lines.append(f"      {fb_line}")

        lines.append(sep)

    imp = result.get("fc_error_improvement", {})
    lines += [
        f"  Final: spec_met={result['final_spec_met']}  "
        f"conv={result['final_simulation_converged']}  "
        f"iters={result['total_iterations']}  "
        f"total_time={result.get('total_generation_time_s',0):.1f}s",
    ]
    if imp.get("iter1_pct") is not None:
        lines.append(f"  fc_error: iter1={imp['iter1_pct']}%  →  final={imp['final_pct']}%  "
                     f"({'improved' if imp.get('improved') else 'no improvement'})")

    with open(log_path, "a") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# PROGRESS REPORTING
# ---------------------------------------------------------------------------

def write_agentic_progress(all_results: list, current_ds: str,
                           done: int, total: int,
                           all_datasets: list, datasets_done: int):
    elapsed_s = time.time() - _agentic_start_time if _agentic_start_time else 0
    h, rem    = divmod(int(elapsed_s), 3600)
    m, s      = divmod(rem, 60)
    elapsed_str = f"{h}h {m:02d}m {s:02d}s" if h else (f"{m}m {s:02d}s" if m else f"{s}s")

    n         = len(all_results)
    spec_met  = sum(1 for r in all_results if r.get("final_spec_met"))
    conv      = sum(1 for r in all_results if r.get("final_simulation_converged"))
    improved  = sum(1 for r in all_results
                    if r.get("fc_error_improvement", {}).get("improved"))
    avg_iters_list = [r["total_iterations"] for r in all_results if r.get("total_iterations")]
    avg_iters = sum(avg_iters_list) / len(avg_iters_list) if avg_iters_list else 0

    lines = [
        "=" * 60,
        f"  AGENTIC PIPELINE PROGRESS — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        f"  Elapsed:         {elapsed_str}",
        f"  Datasets:        {datasets_done}/{len(all_datasets)}  ({', '.join(all_datasets)})",
        f"  Current dataset: {current_ds}  [{done}/{total} entries]",
        "",
        f"  Total processed: {n}",
        f"  Spec met (final): {spec_met}/{n}  ({spec_met/n*100:.1f}%)" if n else "  Spec met: n/a",
        f"  Sim converged:   {conv}/{n}  ({conv/n*100:.1f}%)" if n else "  Sim converged: n/a",
        f"  fc error improved across iters: {improved}/{n}" if n else "",
        f"  Avg iterations used: {avg_iters:.2f}" if avg_iters_list else "",
        "=" * 60,
    ]

    path = AGENTIC_OUTPUT_DIR / "progress.txt"
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# DATASET PROCESSING
# ---------------------------------------------------------------------------

def process_agentic_dataset(model, tokenizer, dataset_name: str,
                            json_path: Path, limit=None, max_iters=MAX_ITERS,
                            verbose=False, formula_hints=True,
                            all_results_ref=None,
                            all_datasets=None, datasets_done=0,
                            timestamp="") -> list:

    print(f"\n{'='*60}")
    print(f"Agentic processing: {dataset_name}  ({json_path.name})")
    print(f"  max_iters={max_iters}  formula_hints={formula_hints}  limit={limit or 'all'}")
    print(f"{'='*60}")

    with open(json_path) as f:
        entries = json.load(f)

    if limit:
        entries = entries[:limit]
    total = len(entries)
    print(f"  Entries: {total}")

    results       = []
    checkpoint_path = AGENTIC_OUTPUT_DIR / f"checkpoint_{dataset_name}.json"
    log_path        = AGENTIC_OUTPUT_DIR / f"iterations_log_{dataset_name}_{timestamp}.txt"

    # Write log header
    with open(log_path, "w") as f:
        f.write(f"AGENTIC ITERATION LOG — {dataset_name.upper()} — {datetime.now().isoformat()}\n")
        f.write(f"max_iters={max_iters}  formula_hints={formula_hints}  entries={total}\n")
        f.write("=" * 70 + "\n")

    for idx, entry in enumerate(entries):
        print(f"  [{idx+1}/{total}] task={entry.get('task_type','?')} "
              f"topo={entry.get('topology','?')} ...", end=" ", flush=True)

        result = agentic_loop(
            model, tokenizer, entry, idx,
            source_file=json_path.name,
            max_iters=max_iters,
            verbose=verbose,
            formula_hints=formula_hints,
        )

        n_iters   = result["total_iterations"]
        spec_met  = result["final_spec_met"]
        converged = result["final_simulation_converged"]
        status    = ("SPEC MET" if spec_met
                     else "converged" if converged
                     else "failed")
        print(f"{status} ({n_iters} iters)")

        # Write iteration log entry immediately (readable while job runs)
        feedback_msgs = result.pop("_feedback_messages", [])
        append_iteration_log(log_path, result, feedback_msgs)

        results.append(result)
        if all_results_ref is not None:
            all_results_ref.append(result)

        # Checkpoint every 10 entries
        if (idx + 1) % 10 == 0 or (idx + 1) == total:
            with open(checkpoint_path, "w") as f:
                json.dump(results, f, indent=2)

        write_agentic_progress(
            all_results    = all_results_ref if all_results_ref is not None else results,
            current_ds     = dataset_name,
            done           = idx + 1,
            total          = total,
            all_datasets   = all_datasets or [dataset_name],
            datasets_done  = datasets_done,
        )

    return results


# ---------------------------------------------------------------------------
# SUMMARY
# ---------------------------------------------------------------------------

def compute_agentic_summary(all_results: list) -> dict:
    if not all_results:
        return {}

    n           = len(all_results)
    spec_met    = [r for r in all_results if r.get("final_spec_met")]
    converged   = [r for r in all_results if r.get("final_simulation_converged")]
    parsed      = [r for r in all_results if r.get("final_parse_success")]
    iters_list  = [r["total_iterations"] for r in all_results if r.get("total_iterations")]
    improved    = [r for r in all_results if r.get("fc_error_improvement", {}).get("improved")]

    # Improvement in fc_error from iteration 1 to final
    fc_err_delta = []
    for r in all_results:
        imp = r.get("fc_error_improvement", {})
        if imp.get("iter1_pct") is not None and imp.get("final_pct") is not None:
            fc_err_delta.append(imp["iter1_pct"] - imp["final_pct"])

    # Per-task-type breakdown
    task_types = sorted({r.get("task_type", "unknown") for r in all_results})
    per_task   = {}
    for tt in task_types:
        sub    = [r for r in all_results if r.get("task_type") == tt]
        sm     = sum(1 for r in sub if r.get("final_spec_met"))
        cv     = sum(1 for r in sub if r.get("final_simulation_converged"))
        it_sub = [r["total_iterations"] for r in sub if r.get("total_iterations")]
        per_task[tt] = {
            "total":                  len(sub),
            "final_spec_met_pct":     round(sm / len(sub) * 100, 1) if sub else 0,
            "final_converged_pct":    round(cv / len(sub) * 100, 1) if sub else 0,
            "avg_iterations_used":    round(sum(it_sub) / len(it_sub), 2) if it_sub else None,
        }

    return {
        "generated_at":             datetime.now().isoformat(),
        "total_entries":            n,
        "max_iters_configured":     MAX_ITERS,
        "final_spec_met_pct":       round(len(spec_met) / n * 100, 1),
        "final_converged_pct":      round(len(converged) / n * 100, 1),
        "final_parse_success_pct":  round(len(parsed) / n * 100, 1),
        "avg_iterations_used":      round(sum(iters_list) / len(iters_list), 2) if iters_list else None,
        "fc_error_improved_pct":    round(len(improved) / n * 100, 1),
        "avg_fc_error_reduction":   round(sum(fc_err_delta) / len(fc_err_delta), 1) if fc_err_delta else None,
        "per_task_type":            per_task,
    }


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Agentic LLM Netlist Generation Pipeline with simulation feedback"
    )
    parser.add_argument("--limit",     type=int, default=None,
                        help="Max entries per dataset (default: all)")
    parser.add_argument("--datasets",  type=str, default=None,
                        help="Comma-separated dataset names, e.g. lpf,hpf (default: all)")
    parser.add_argument("--max-iters", type=int, default=MAX_ITERS,
                        help=f"Max simulation-feedback iterations per entry (default: {MAX_ITERS})")
    parser.add_argument("--verbose",          action="store_true",
                        help="Print per-iteration details")
    parser.add_argument("--no-formula-hints", action="store_true",
                        help="Disable formula hints in feedback (ablation mode — direction only)")
    args = parser.parse_args()

    if args.datasets:
        selected    = [d.strip() for d in args.datasets.split(",")]
        dataset_map = {k: v for k, v in DATASET_FILES.items() if k in selected}
    else:
        dataset_map = DATASET_FILES

    if not dataset_map:
        print(f"No matching datasets. Available: {', '.join(DATASET_FILES)}")
        return

    AGENTIC_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    global _agentic_start_time
    _agentic_start_time = time.time()
    max_iters = args.max_iters   # use this local everywhere below

    formula_hints = not args.no_formula_hints

    # Startup progress file
    ds_names = list(dataset_map.keys())
    with open(AGENTIC_OUTPUT_DIR / "progress.txt", "w") as f:
        f.write(
            f"{'='*60}\n"
            f"  AGENTIC PIPELINE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"  Status: LOADING MODEL...\n"
            f"  Datasets: {', '.join(ds_names)}  |  max_iters={args.max_iters}  "
            f"formula_hints={formula_hints}\n"
            f"{'='*60}\n"
        )

    print(f"Loading model: {MODEL_ID}")
    model, tokenizer = load_model()

    all_results = []

    for ds_idx, (ds_name, ds_path) in enumerate(dataset_map.items()):
        if not ds_path.exists():
            print(f"WARNING: {ds_path} not found, skipping.")
            continue

        results = process_agentic_dataset(
            model, tokenizer, ds_name, ds_path,
            limit=args.limit,
            max_iters=args.max_iters,
            verbose=args.verbose,
            formula_hints=formula_hints,
            all_results_ref=all_results,
            all_datasets=ds_names,
            datasets_done=ds_idx,
            timestamp=timestamp,
        )

        out_path = AGENTIC_OUTPUT_DIR / f"results_{ds_name}_{timestamp}.json"
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"  Saved: {out_path}")

    summary = compute_agentic_summary(all_results)
    summary_path = AGENTIC_OUTPUT_DIR / f"summary_{timestamp}.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 60)
    print("AGENTIC PIPELINE SUMMARY")
    print("=" * 60)
    print(f"  Total entries:         {summary['total_entries']}")
    print(f"  Final spec met:        {summary['final_spec_met_pct']}%")
    print(f"  Final converged:       {summary['final_converged_pct']}%")
    print(f"  Avg iterations used:   {summary['avg_iterations_used']}")
    print(f"  fc error improved:     {summary['fc_error_improved_pct']}% of entries")
    print(f"  Avg fc error reduction:{summary['avg_fc_error_reduction']}%")
    print("\n  Per task type:")
    for tt, s in summary.get("per_task_type", {}).items():
        print(f"    {tt}: spec_met={s['final_spec_met_pct']}%  "
              f"conv={s['final_converged_pct']}%  "
              f"avg_iters={s['avg_iterations_used']}")
    print(f"\nSummary saved: {summary_path}")


if __name__ == "__main__":
    main()
