"""
rag_pipeline.py — RAG-augmented agentic netlist generation (New_Datagen datasets)

Same simulation-feedback loop as agentic_pipeline.py, but:
  1. Uses New_Datagen prompts (pipeline_v2 datasets, 1000 entries/type)
  2. System prompt is augmented with the topology-specific design guide
     retrieved from filter_system_prompts/ — simulating a RAG retrieval step.

The retrieved context = base_prompt.md  +  {filter}_{topology}.md
This gives the model exact formulas, component ranges, and worked examples
matched to the specific filter type and topology it needs to generate.

Output: rag_output/  (parallel to agentic_output/ for direct comparison)

Usage:
    python rag_pipeline.py --datasets lpf --limit 5
    python rag_pipeline.py --datasets lpf,hpf,bpf,notch --limit 5 --max-iters 3
    python rag_pipeline.py --datasets lpf --limit 5 --verbose
"""

import argparse
import json
import math
import os
import re
import time
from datetime import datetime
from pathlib import Path

import torch

# ---------------------------------------------------------------------------
# Reuse all SPICE/model/metrics utilities from pipeline_v2
# ---------------------------------------------------------------------------
from pipeline_v2 import (
    load_model,
    extract_netlist,
    build_spice_file,
    run_ngspice,
    parse_ac_results,
    calculate_metrics,
    MODEL_ID,
    NGSPICE_PATH,
    TEMPERATURE,
    OPAMP_IDEAL_SUBCKT,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_SCRIPT_DIR   = Path(__file__).parent
DATA_DIR      = _SCRIPT_DIR / "New_Datagen" / "prompts"
RAG_DOCS_DIR  = _SCRIPT_DIR / "RAG stuff" / "filter_system_prompts"
OUTPUT_DIR    = _SCRIPT_DIR / "rag_output"

DATASET_FILES = {
    "lpf":   DATA_DIR / "lpf_dataset.json",
    "hpf":   DATA_DIR / "hpf_dataset.json",
    "bpf":   DATA_DIR / "bpf_dataset.json",
    "notch": DATA_DIR / "notch_dataset.json",
}

# Map New_Datagen task names → RAG doc prefix
_TASK_TO_RAG = {
    "low_pass":  "lpf",
    "high_pass": "hpf",
    "band_pass": "bpf",
    "notch":     "notch",
}

MAX_ITERS      = 3
MAX_NEW_TOKENS = 1024

# ---------------------------------------------------------------------------
# RAG document loading
# ---------------------------------------------------------------------------

_doc_cache: dict[str, str] = {}


def _load_doc(path: Path) -> str:
    key = str(path)
    if key not in _doc_cache:
        _doc_cache[key] = path.read_text(encoding="utf-8")
    return _doc_cache[key]


def build_rag_system_prompt(task: str, topology: str) -> str:
    """
    Build the system prompt for a given filter type and topology by
    concatenating:
      1. The CoT reasoning instructions
      2. base_prompt.md  (general SPICE format rules)
      3. {filter}_{topology}.md  (formulas, design procedure, worked examples)
    """
    filter_prefix = _TASK_TO_RAG.get(task, task)
    doc_key       = f"{filter_prefix}_{topology}"
    doc_path      = RAG_DOCS_DIR / f"{doc_key}.md"
    base_path     = RAG_DOCS_DIR / "base_prompt.md"

    base_doc     = _load_doc(base_path) if base_path.exists() else ""
    topology_doc = _load_doc(doc_path)  if doc_path.exists()  else ""

    if not topology_doc:
        missing = f"[RAG doc not found: {doc_key}.md]"
        topology_doc = missing

    return f"""\
You are a circuit design assistant specialized in SPICE netlist generation.

Before writing any SPICE, reason through the design step by step.

══ STEP 1 — DETERMINE FILTER ORDER ══
From the required rolloff or attenuation spec, decide how many poles you need.
Write: "I need a [N]th-order [filter type] filter."

══ STEP 2 — COMPUTE COMPONENT VALUES ══
Work out R and C numerically. Show every calculation.
For a single-pole RC stage: fc = 1 / (2π·R·C)  →  R·C = 1 / (2π·fc)
Write: "R·C = 1/(2π·[fc Hz]) = [value] s. With R = [value], C = [value]."

══ STEP 3 — WRITE THE NETLIST ══
After your calculations, output the SPICE netlist in a ```spice ... ``` block.

MANDATORY NODE NAMES:
  VIN  = the input node
  VOUT = the output node (the last node of your filter chain MUST be VOUT)
  GND  = ground / 0 V reference

VOLTAGE SOURCE — always write:  V1 VIN GND AC 1
COMPONENT NAMING: R1, R2, …; C1, C2, …; op-amp U1.
OP-AMP — if needed, use OPAMP_IDEAL with five pins: INP INN VCC VEE OUT.
  Example: U1 node_inp node_inn VCC VEE node_out OPAMP_IDEAL
  Do NOT define .SUBCKT OPAMP_IDEAL — it is provided externally.
  Do NOT add VCC/VEE power supply sources — handled externally.
Do NOT write 'GND 0' as a standalone declaration.
End the netlist with .END. No .AC, .TRAN, or simulation commands.

══ RETRIEVED REFERENCE DOCUMENTS ══

--- SPICE FORMAT RULES ---
{base_doc}

--- TOPOLOGY-SPECIFIC DESIGN GUIDE ({doc_key}) ---
{topology_doc}
"""


# ---------------------------------------------------------------------------
# REQUIREMENTS block parser
# Extracts all target values directly from the prompt text — no JSON needed.
# This mirrors what a real deployed agent would do.
# ---------------------------------------------------------------------------

def _parse_hz_str(s: str) -> float:
    """'1.592 kHz' → 1592.0,  '100 Hz' → 100.0,  '2.5 MHz' → 2500000.0"""
    s = s.strip()
    m = re.match(r'([\d.]+(?:e[+-]?\d+)?)\s*(MHz|kHz|Hz)', s, re.IGNORECASE)
    if not m:
        raise ValueError(f"Cannot parse frequency: {s!r}")
    val, unit = float(m.group(1)), m.group(2).lower()
    return val * {"mhz": 1e6, "khz": 1e3, "hz": 1.0}[unit]


def _parse_db_str(s: str) -> float:
    """'[max loss: 1.1 dB]' or '≤ 1.1 dB' → 1.1"""
    m = re.search(r'([\d.]+)\s*dB', s, re.IGNORECASE)
    if not m:
        raise ValueError(f"Cannot parse dB: {s!r}")
    return float(m.group(1))


def parse_requirements(prompt: str) -> tuple[str | None, dict]:
    """
    Parse the REQUIREMENTS block embedded in a prompt and return
    (task_type, params_dict) using the same key names as _build_params().

    Returns (None, {}) if the block is missing or unparseable.
    This is the only source of target values used by the agentic loop —
    no JSON fields are read during feedback or evaluation.
    """
    block_match = re.search(r'REQUIREMENTS:\s*\n((?:[ \t]+.+\n?)*)', prompt)
    if not block_match:
        return None, {}

    # Build key→value dict from indented lines, preserving colons in values
    kv: dict[str, str] = {}
    for line in block_match.group(1).splitlines():
        if ':' not in line:
            continue
        key, _, val = line.strip().partition(':')
        kv[key.strip()] = val.strip()

    filter_type = kv.get('Type', '').lower()
    if 'low-pass' in filter_type:
        task_type = 'low_pass_filter'
    elif 'high-pass' in filter_type:
        task_type = 'high_pass_filter'
    elif 'band-pass' in filter_type:
        task_type = 'band_pass_filter'
    elif 'notch' in filter_type:
        task_type = 'notch_filter'
    else:
        return None, {}

    try:
        if task_type in ('low_pass_filter', 'high_pass_filter'):
            fc_raw = kv.get('Passband edge (fc)', '')
            fs_raw = kv.get('Stopband edge (fs)', '')
            return task_type, {
                'fc_hz':      _parse_hz_str(fc_raw.split('[')[0]),
                'fs_hz':      _parse_hz_str(fs_raw.split('[')[0]),
                'pb_loss_db': _parse_db_str(fc_raw),
                'atten_db':   _parse_db_str(fs_raw),
            }

        if task_type == 'band_pass_filter':
            fcl = kv.get('Lower passband edge (fc_low)', '')
            fch = kv.get('Upper passband edge (fc_high)', '')
            fsl = kv.get('Lower stopband edge (fs_low)', '')
            fsh = kv.get('Upper stopband edge (fs_high)', '')
            atten = _parse_db_str(fsl)
            return task_type, {
                'fc_low_hz':     _parse_hz_str(fcl.split('[')[0]),
                'fc_high_hz':    _parse_hz_str(fch.split('[')[0]),
                'fs_low_hz':     _parse_hz_str(fsl.split('[')[0]),
                'fs_high_hz':    _parse_hz_str(fsh.split('[')[0]),
                'atten_low_db':  atten,
                'atten_high_db': atten,
                'pb_loss_db':    _parse_db_str(fcl),
            }

        if task_type == 'notch_filter':
            centre = kv.get('Notch centre', '')
            # "1.0 kHz – 2.5 kHz"  (en-dash or hyphen)
            bw_raw = kv.get('Notch bandwidth (-3 dB)', '')
            bw_parts = re.split(r'\s*[–\-]\s*', bw_raw, maxsplit=1)
            fs_raw = kv.get('Stopband sample (fs)', '')
            pb_raw = kv.get('Passband loss', '')
            fs_hz  = _parse_hz_str(fs_raw.split('[')[0])
            return task_type, {
                'f_notch_hz':     _parse_hz_str(centre),
                'fc_low_hz':      _parse_hz_str(bw_parts[0]) if bw_parts else None,
                'fc_high_hz':     _parse_hz_str(bw_parts[1]) if len(bw_parts) > 1 else None,
                'fs_low_hz':      fs_hz,
                'fs_high_hz':     fs_hz,
                'notch_depth_db': _parse_db_str(fs_raw),
                'pb_loss_db':     _parse_db_str(pb_raw),
            }

    except (ValueError, IndexError):
        return None, {}

    return None, {}


# ---------------------------------------------------------------------------
# Single-turn generation (full conversation history)
# ---------------------------------------------------------------------------

def generate_with_history(model, tokenizer, messages: list):
    text      = tokenizer.apply_chat_template(messages, tokenize=False,
                                              add_generation_prompt=True)
    inputs    = tokenizer(text, return_tensors="pt").to(model.device)
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
    tokens_gen    = int((generated_ids != tokenizer.eos_token_id).sum()) or generated_ids.shape[0]
    reply         = tokenizer.decode(generated_ids, skip_special_tokens=True)
    return reply, tokens_gen, elapsed


# ---------------------------------------------------------------------------
# Feedback helpers (mirrors agentic_pipeline.py)
# ---------------------------------------------------------------------------

def _fmt_hz(hz):
    if hz is None:
        return "?"
    if hz >= 1e6:
        return f"{hz/1e6:.3g} MHz"
    if hz >= 1e3:
        return f"{hz/1e3:.4g} kHz"
    return f"{hz:.4g} Hz"


def _extract_rc_label(netlist: str) -> str:
    parts = []
    for line in (netlist or "").splitlines():
        m = re.match(r'^([RC]\S+)\s+\S+\s+\S+\s+(\S+)', line.strip(), re.I)
        if m:
            parts.append(f"{m.group(1).upper()}={m.group(2)}")
    return ", ".join(parts[:6]) if parts else ""


def _build_netlist_template(task_type: str, topology: str, fc_stage: float) -> str | None:
    """
    Given the exact per-stage corner frequency, return a fully-valued SPICE netlist.
    Used to bypass the model's arithmetic when its design is badly wrong.
    """
    if not fc_stage or fc_stage <= 0:
        return None
    is_lpf   = task_type == "low_pass_filter"
    is_hpf   = task_type == "high_pass_filter"
    is_notch = task_type == "notch_filter"
    is_multi = "multi" in topology
    is_buf   = "buffered" in topology
    if not (is_lpf or is_hpf or is_notch):
        return None

    # Pick R so that C = 1/(2π·fc_stage·R) lands in [1 nF, 100 nF]
    chosen_r = chosen_c = None
    for r in [10e3, 1e3, 100e3, 4.7e3, 47e3, 2.2e3, 22e3]:
        c = 1.0 / (2 * math.pi * fc_stage * r)
        if 1e-9 <= c <= 100e-9:
            chosen_r, chosen_c = r, c
            break
    if chosen_r is None:
        # Out of preferred range — use nearest boundary R
        c_at_100k = 1.0 / (2 * math.pi * fc_stage * 100e3)
        chosen_r = 100e3 if c_at_100k >= 1e-9 else 1e3
        chosen_c = 1.0 / (2 * math.pi * fc_stage * chosen_r)

    def _fr(r):
        return f"{r/1e3:.4g}k"

    def _fc_str(c):
        if c >= 1e-6:
            return f"{c*1e6:.4g}u"
        if c >= 1e-9:
            return f"{c*1e9:.4g}n"
        return f"{c*1e12:.4g}p"

    # --- Notch filter: Twin-T topology ---
    if is_notch:
        f_notch = fc_stage
        chosen_r = chosen_c = None
        # Wider R candidate list to cover very low (24 Hz) to high (95 kHz) notch freqs
        for r in [10e3, 1e3, 100e3, 470e3, 220e3, 4.7e3, 47e3]:
            c = 1.0 / (2 * math.pi * f_notch * r)
            if 1e-9 <= c <= 200e-9:
                chosen_r, chosen_c = r, c
                break
        if chosen_r is None:
            # Fallback: pick R that targets C ≈ 10 nF
            chosen_r = 1.0 / (2 * math.pi * f_notch * 10e-9)
            chosen_c = 10e-9

        R    = _fr(chosen_r)
        C    = _fc_str(chosen_c)
        Rhalf = _fr(chosen_r / 2)
        C2x   = _fc_str(chosen_c * 2)

        ntlines = [
            "* Twin-T notch filter",
            f"*   f_notch = {_fmt_hz(f_notch)},  R = {R},  C = {C}",
            f"*   R/2 = {Rhalf},  2C = {C2x}",
            "V1    VIN   0      AC 1",
            "",
            "* Upper R-arm: two R in series, shunt 2C to ground",
            f"R1    VIN   NTA    {R}",
            f"R2    NTA   NOUT   {R}",
            f"C3    NTA   0      {C2x}",
            "",
            "* Lower C-arm: two C in series, shunt R/2 to ground",
            f"C1    VIN   NTB    {C}",
            f"C2    NTB   NOUT   {C}",
            f"R3    NTB   0      {Rhalf}",
            "",
            "* Output buffer (prevents loading the Twin-T)",
            "EOUT  VOUT  0      NOUT  0  1",
            "",
            ".end",
        ]
        return "\n".join(ntlines)

    R = _fr(chosen_r)
    C = _fc_str(chosen_c)
    fc_3db = fc_stage * (0.3743 if is_lpf else 2.672) if is_multi else fc_stage

    ftype = "low" if is_lpf else "high"
    nstg  = "2-stage" if is_multi else "Single-stage"
    buf   = " buffered" if is_buf else ""
    lines = [
        f"* {nstg}{buf} RC {ftype}-pass filter",
        f"*   fc_stage = {_fmt_hz(fc_stage)},  fc_3dB ≈ {_fmt_hz(fc_3db)}",
        f"*   R = {R},  C = {C}",
        "V1   VIN   0     AC 1",
        "",
    ]

    first = "VBUF" if is_buf else "VIN"
    if is_buf:
        lines.append("EBUF VBUF  0     VIN  0  1")

    if is_lpf:
        if is_multi:
            lines += [f"R1   {first}  n1     {R}",
                      f"C1   n1    0      {C}",
                      f"R2   n1    VOUT   {R}",
                      f"C2   VOUT  0      {C}"]
        else:
            lines += [f"R1   {first}  VOUT   {R}",
                      f"C1   VOUT  0      {C}"]
    else:  # HPF: capacitor in series, resistor shunt to GND
        if is_multi:
            lines += [f"C1   {first}  n1     {C}",
                      f"R1   n1    0      {R}",
                      f"C2   n1    VOUT   {C}",
                      f"R2   VOUT  0      {R}"]
        else:
            lines += [f"C1   {first}  VOUT   {C}",
                      f"R1   VOUT  0      {R}"]

    lines.append(".end")
    return "\n".join(lines)


def build_feedback(iteration: int, parse_success: bool, sim_ok: bool,
                   metrics: dict, params: dict, task_type: str,
                   netlist: str = None, stderr: str = "",
                   prev_metrics: dict = None, topology: str = "") -> str:
    lines = [f"SIMULATION FEEDBACK — Iteration {iteration}", "=" * 50]

    rc = _extract_rc_label(netlist)
    if rc:
        lines += [f"Components used: {rc}", ""]

    if not parse_success:
        lines += [
            "Status: PARSE FAILED — could not extract a valid ```spice ... ``` block.",
            "Ensure the netlist ends with .END and is wrapped in ```spice ... ```.",
        ]
        return "\n".join(lines)

    if not sim_ok:
        errs = [l.strip() for l in stderr.splitlines()
                if any(k in l.lower() for k in ("error","fatal","singular","mismatch","syntax"))][:5]
        lines += ["Status: SIMULATION FAILED",
                  f"NGSpice errors:\n  " + "\n  ".join(errs or ["(unknown)"])]
        return "\n".join(lines)

    if metrics.get("filter_response_match"):
        lines += ["Status: ALL SPECIFICATIONS MET ✓", "No further revision needed."]
        return "\n".join(lines)

    lines += ["Status: SIMULATED — specifications NOT met.", "", "=== Measured vs Required ==="]

    if task_type in ("low_pass_filter", "high_pass_filter"):
        f_pass   = params.get("fc_hz")   # passband sample (NOT the -3dB target)
        pb_db    = params.get("pb_loss_db")
        fs_hz    = params.get("fs_hz")
        atten_db = params.get("atten_db")
        fc_m     = metrics.get("cutoff_freq_hz_measured")
        is_lpf   = task_type == "low_pass_filter"
        is_multi = "multi" in topology  # rc_multi or buffered_rc_multi

        # For two-stage topologies, the loaded transfer function is:
        #   H = 1/(1 + 3τs + τ²s²)  where τ = RC = 1/(2π·fc_stage)
        # The combined -3dB is fc_3dB = 0.3743·fc_stage (LPF) or 2.672·fc_stage (HPF).
        # Design from the STOPBAND constraint (matches the .md REQUIREMENTS procedure):
        #   V = [−7 + √(45 + 4D)] / 2,  D = 10^(atten/10)
        #   fc_stage = fs / √V  (LPF)  or  fs × √V  (HPF)
        # For single-stage, derive fc directly from the passband constraint.
        fc_target = None  # combined -3 dB target shown to the model
        fc_stage  = None  # per-stage corner used to compute C = 1/(2π·fc_stage·R)

        if is_multi and fs_hz and atten_db:
            try:
                D = 10 ** (atten_db / 10)
                V = (-7 + math.sqrt(45 + 4 * D)) / 2
                if is_lpf:
                    fc_stage  = fs_hz / math.sqrt(V)
                    fc_target = fc_stage * 0.3743
                else:
                    fc_stage  = fs_hz * math.sqrt(V)
                    fc_target = fc_stage * 2.672
            except (ValueError, ZeroDivisionError):
                pass

        if fc_target is None and f_pass and pb_db:
            # Single-stage: invert A(f) = 10·log10(1 + (fc/f)²) at f_pass.
            # Multi-stage fallback (no stopband info): use two-stage passband inversion.
            try:
                if is_multi:
                    D = 10 ** (pb_db / 10)
                    u = (-7 + math.sqrt(45 + 4 * D)) / 2
                    if is_lpf:
                        fc_stage  = f_pass / math.sqrt(u)
                        fc_target = fc_stage * 0.3743
                    else:
                        fc_stage  = f_pass * math.sqrt(u)
                        fc_target = fc_stage * 2.672
                else:
                    denom = math.sqrt(10 ** (pb_db / 10) - 1)
                    if denom > 0:
                        fc_target = f_pass / denom if is_lpf else f_pass * denom
                        fc_stage  = fc_target
            except (ValueError, ZeroDivisionError):
                pass

        fc_target = fc_target or f_pass
        if fc_stage is None:
            fc_stage = fc_target

        if fc_m and fc_target:
            d = "high" if fc_m > fc_target else "low"
            err_pct = abs(fc_m - fc_target) / fc_target * 100
            lines.append(f"  Passband sample: {_fmt_hz(f_pass)} [max loss: {pb_db} dB]")
            if is_multi and abs(fc_stage - fc_target) > 0.01:
                lines.append(f"  → Two-stage per-stage corner (fc_stage): {_fmt_hz(fc_stage)}")
                lines.append(f"  → Combined -3 dB target: {_fmt_hz(fc_target)}")
                lines.append(f"  ⚠ Use C = 1/(2π·fc_stage·R), NOT C = 1/(2π·fc_3dB·R)")
            else:
                lines.append(f"  → -3 dB target: {_fmt_hz(fc_target)}")
            lines.append(f"  Measured -3 dB: {_fmt_hz(fc_m)} | {err_pct:.1f}% too {d}")
            # R·C example values are keyed to fc_stage (the correct design frequency for C)
            rc_need = 1.0 / (2 * math.pi * fc_stage)
            rc_curr = 1.0 / (2 * math.pi * fc_m)
            ratio   = fc_m / fc_target
            action  = "INCREASE" if ratio > 1 else "DECREASE"
            factor  = ratio if ratio > 1 else 1.0 / ratio
            lines += ["", "=== How to Fix ===",
                      f"  Required R·C = 1/(2π·{_fmt_hz(fc_stage)}) = {rc_need:.4e} s",
                      f"  Your R·C     = {rc_curr:.4e} s",
                      f"  Action: {action} R or C by {factor:.2f}x",
                      f"  Example values for fc_stage = {_fmt_hz(fc_stage)}:"]
            for r in [1e3, 10e3, 100e3]:
                c = rc_need / r
                if 1e-12 < c < 100e-9:
                    lines.append(f"    R={r/1e3:.0f}kΩ → C={c*1e9:.2f}nF")

            # When the design is badly wrong (>2x off or passband failing by >1 dB),
            # inject a fully pre-computed netlist so the model can copy it exactly
            # instead of recomputing with arithmetic errors.
            pb_loss = metrics.get("loss_at_fc_db")
            pb_req_local = params.get("pb_loss_db")
            pb_miss = (pb_loss - pb_req_local) if (pb_loss is not None and pb_req_local) else 0
            if (factor > 2.0 or pb_miss > 1.0) and fc_stage:
                tmpl = _build_netlist_template(task_type, topology, fc_stage)
                if tmpl:
                    lines += [
                        "",
                        "══ PRE-COMPUTED NETLIST — COPY THIS EXACTLY ══",
                        "The pipeline computed the correct component values above.",
                        "Do NOT recalculate. Output the following netlist verbatim:",
                        "```spice",
                        tmpl,
                        "```",
                    ]

        atten = metrics.get("attenuation_at_fs", {})
        if atten.get("required_db") and not atten.get("met"):
            req = atten["required_db"]; fs = atten.get("fs_hz"); fc = fc_target or f_pass or 1
            if fs and fc:
                dec = abs(math.log10(fs / fc))
                if dec > 0.1:
                    order = math.ceil(req / (20 * dec))
                    lines.append(f"  Stopband: need {req:.0f} dB over {dec:.1f} decades → min order ≈ {order}")

    elif task_type == "band_pass_filter":
        for key, label in [("cutoff_freq_low_hz_measured","lower"), ("cutoff_freq_high_hz_measured","upper")]:
            fc_m = metrics.get(key)
            fc_s = params.get("fc_low_hz" if "low" in key else "fc_high_hz")
            if fc_m and fc_s:
                d = "high" if fc_m > fc_s else "low"
                lines.append(f"  {label.capitalize()} cutoff: {_fmt_hz(fc_m)} | target {_fmt_hz(fc_s)} | too {d}")
        if params.get("fc_low_hz") and params.get("fc_high_hz"):
            f0  = math.sqrt(params["fc_low_hz"] * params["fc_high_hz"])
            rc  = 1.0 / (2 * math.pi * f0)
            lines += ["", f"  Centre f0={_fmt_hz(f0)}, required R·C={rc:.4e} s"]

    elif task_type == "notch_filter":
        f_n   = params.get("f_notch_hz")
        dep_m = metrics.get("notch_depth_peak_db") or metrics.get("notch_depth_db")
        dep_r = params.get("notch_depth_db")
        if dep_m is not None and dep_r is not None:
            lines.append(f"  Notch depth: {dep_m:.1f} dB | required ≥{dep_r:.1f} dB")
        if f_n:
            rc = 1.0 / (2 * math.pi * f_n); r_ex = 10e3; c_ex = rc / r_ex
            lines += ["", f"  Twin-T at {_fmt_hz(f_n)}: R·C={rc:.4e} s",
                      f"    R1=R2={r_ex/1e3:.0f}kΩ, R3=R/2={r_ex/2e3:.1f}kΩ",
                      f"    C1=C2={c_ex*1e9:.3f}nF, C3=2C={2*c_ex*1e9:.3f}nF"]
            # Always inject the pre-computed template — model consistently gets RC
            # wrong due to unit-prefix errors; verbatim copy is more reliable.
            tmpl = _build_netlist_template("notch_filter", topology, f_n)
            if tmpl:
                lines += [
                    "",
                    "══ PRE-COMPUTED NOTCH NETLIST — COPY THIS EXACTLY ══",
                    "The pipeline computed the correct R and C values above.",
                    "Do NOT recalculate. Output the following netlist verbatim:",
                    "```spice",
                    tmpl,
                    "```",
                ]

    if prev_metrics:
        p_err = prev_metrics.get("cutoff_freq_error_pct") or prev_metrics.get("cutoff_freq_low_error_pct")
        c_err = metrics.get("cutoff_freq_error_pct") or metrics.get("cutoff_freq_low_error_pct")
        if p_err and c_err:
            delta = p_err - c_err
            if delta > 1:
                lines.append(f"\n  Progress: fc error {p_err:.1f}% → {c_err:.1f}% (↓ improved)")
            elif delta < -1:
                lines.append(f"\n  Progress: fc error {p_err:.1f}% → {c_err:.1f}% (↑ worse — revert)")
            else:
                lines.append(f"\n  Progress: no change ({c_err:.1f}%) — try a larger adjustment")

    lines += ["", "Output a revised netlist in ```spice ... ```."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agentic loop — one entry
# ---------------------------------------------------------------------------

def agentic_loop(model, tokenizer, entry: dict, idx: int,
                 max_iters: int = MAX_ITERS, verbose: bool = False) -> dict:

    task      = entry.get("task", "")
    topology  = entry.get("topology", "unknown")
    prompt    = entry.get("prompt", "")

    task_type, params = parse_requirements(prompt)
    if not task_type:
        raise ValueError(f"Entry {idx}: could not parse REQUIREMENTS block from prompt")

    system_prompt = build_rag_system_prompt(task, topology)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": prompt},
    ]

    result = {
        "index":                 idx,
        "task_type":             task_type,
        "topology":              topology,
        "params":                params,
        "prompt":                prompt,
        "ground_truth_netlist":  entry.get("netlist", ""),
        "rag_doc_used":          f"{_TASK_TO_RAG.get(task, task)}_{topology}.md",
        "iterations":            [],
    }

    total_time   = 0.0
    total_tokens = 0
    prev_metrics = None

    for iteration in range(1, max_iters + 1):
        try:
            response, tokens, elapsed = generate_with_history(model, tokenizer, messages)
        except Exception as e:
            result["iterations"].append({"iteration": iteration, "error": str(e)})
            break

        total_time   += elapsed
        total_tokens += tokens

        messages.append({"role": "assistant", "content": response})

        netlist       = extract_netlist(response)
        parse_success = netlist is not None

        cot_text = ""
        spice_pos = (response or "").find("```spice")
        if spice_pos == -1:
            spice_pos = (response or "").find("```SPICE")
        if spice_pos > 0:
            cot_text = response[:spice_pos].strip()

        iter_rec = {
            "iteration":         iteration,
            "generation_time_s": round(elapsed, 2),
            "tokens_generated":  tokens,
            "parse_success":     parse_success,
            "cot_reasoning":     cot_text[:800],
            "generated_netlist": netlist,
        }

        sim_ok = False; metrics = {}; stderr = ""

        if parse_success:
            import tempfile, os
            with tempfile.TemporaryDirectory() as tmp:
                data_file = os.path.join(tmp, "ac_data.txt")
                spice     = build_spice_file(netlist, params, task_type, data_file)
                stdout, stderr, rc = run_ngspice(spice, tmp)
                sim_ok = (rc == 0)
                if sim_ok:
                    ac_data = parse_ac_results(data_file)
                    metrics = calculate_metrics(ac_data, params, task_type) if ac_data else {}

        iter_rec.update({
            "simulation_converged":  sim_ok,
            "metrics":               metrics,
            "spec_met":              bool(metrics.get("filter_response_match")),
        })
        result["iterations"].append(iter_rec)

        if verbose:
            spec = "✓" if iter_rec["spec_met"] else "✗"
            pb_str = ""
            sb_str = ""
            if metrics:
                # LPF / HPF
                loss   = metrics.get("loss_at_fc_db")
                pb_req = params.get("pb_loss_db")
                if loss is not None and pb_req is not None:
                    pb_str = f"  pb={loss:.2f}/{pb_req:.2f}dB"
                atten = metrics.get("attenuation_at_fs", {})
                if atten:
                    sb_str = f"  sb={atten.get('achieved_db') or 0:.1f}/{atten.get('required_db') or 0:.1f}dB"
                # BPF: two stopband edges
                al = metrics.get("attenuation_at_fs_low", {})
                ah = metrics.get("attenuation_at_fs_high", {})
                if al or ah:
                    if al:
                        sb_str += f"  sbl={al.get('achieved_db') or 0:.1f}/{al.get('required_db') or 0:.1f}dB"
                    if ah:
                        sb_str += f"  sbh={ah.get('achieved_db') or 0:.1f}/{ah.get('required_db') or 0:.1f}dB"
                # Notch: depth
                depth     = metrics.get("notch_depth_peak_db")
                depth_req = params.get("notch_depth_db")
                if depth is not None and depth_req is not None:
                    sb_str = f"  depth={depth:.1f}/{depth_req:.1f}dB"
            print(f"      iter {iteration}: parse={'✓' if parse_success else '✗'}  "
                  f"sim={'✓' if sim_ok else '✗'}  spec={spec}{pb_str}{sb_str}  {elapsed:.1f}s")

        if iter_rec["spec_met"]:
            break

        feedback = build_feedback(
            iteration + 1, parse_success, sim_ok, metrics, params, task_type,
            netlist=netlist, stderr=stderr, prev_metrics=prev_metrics,
            topology=topology,
        )
        messages.append({"role": "user", "content": feedback})
        prev_metrics = metrics if sim_ok else None

    final = result["iterations"][-1] if result["iterations"] else {}
    result.update({
        # pipeline_v2-compatible field names so analyse_results_v2.py works unchanged
        "parse_success":          final.get("parse_success", False),
        "simulation_converged":   final.get("simulation_converged", False),
        "metrics":                final.get("metrics", {}),
        "generated_netlist":      final.get("generated_netlist", ""),
        "generation_time_s":      round(total_time, 2),
        "tokens_generated":       total_tokens,
        # RAG-specific extras
        "final_spec_met":         final.get("spec_met", False),
        "iterations_used":        len(result["iterations"]),
    })
    return result


# ---------------------------------------------------------------------------
# Dataset processing
# ---------------------------------------------------------------------------

def _sample_per_topology(entries: list, n: int) -> list:
    """Take the first n entries from each distinct topology, preserving order."""
    seen: dict[str, int] = {}
    out = []
    for e in entries:
        t = e.get("topology", "unknown")
        if seen.get(t, 0) < n:
            out.append(e)
            seen[t] = seen.get(t, 0) + 1
    return out


def process_dataset(model, tokenizer, ds_name: str, limit=None,
                    sample_per_topology=None, max_iters=MAX_ITERS,
                    verbose=False) -> list:
    path = DATASET_FILES[ds_name]
    with open(path) as f:
        entries = json.load(f)
    if sample_per_topology:
        entries = _sample_per_topology(entries, sample_per_topology)
    elif limit:
        entries = entries[:limit]

    results = []
    ckpt    = OUTPUT_DIR / f"ckpt_{ds_name}.json"
    log     = OUTPUT_DIR / f"iter_log_{ds_name}.txt"

    with open(log, "w") as logf:
        logf.write(f"RAG PIPELINE — {ds_name.upper()} — {datetime.now().isoformat()}\n"
                   f"max_iters={max_iters}  entries={len(entries)}\n{'='*70}\n\n")

    gpu_tag = f"[GPU{os.environ.get('CUDA_VISIBLE_DEVICES', '?')}]"

    for idx, entry in enumerate(entries):
        task     = entry.get("task", "")
        topology = entry.get("topology", "unknown")

        result = agentic_loop(model, tokenizer, entry, idx,
                              max_iters=max_iters, verbose=verbose)
        results.append(result)

        spec = "✓" if result["final_spec_met"] else "✗"
        print(f"{gpu_tag} [{idx+1}/{len(entries)}] {task}/{topology}  "
              f"iters={result['iterations_used']}  spec={spec}  "
              f"rag={result['rag_doc_used']}", flush=True)

        with open(log, "a") as logf:
            logf.write(f"Entry {idx}  {task}/{topology}  spec={spec}\n")
            for it in result["iterations"]:
                fc_err = it.get("metrics", {}).get("cutoff_freq_error_pct")
                logf.write(f"  iter {it['iteration']}: "
                           f"parse={'✓' if it.get('parse_success') else '✗'}  "
                           f"sim={'✓' if it.get('simulation_converged') else '✗'}  "
                           f"spec={'✓' if it.get('spec_met') else '✗'}"
                           f"{'  fc_err='+f'{fc_err:.1f}%' if fc_err else ''}\n")
            logf.write("\n")

        with open(ckpt, "w") as f:
            json.dump(results, f, indent=2)

    return results


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def compute_summary(all_results: list, timestamp: str) -> dict:
    by_task: dict[str, list] = {}
    for r in all_results:
        by_task.setdefault(r["task_type"], []).append(r)

    summary = {
        "generated_at":          datetime.now().isoformat(),
        "timestamp":             timestamp,
        "total_entries":         len(all_results),
        "max_iters_configured":  MAX_ITERS,
        "final_parse_pct":       sum(r["parse_success"] for r in all_results) / len(all_results) * 100,
        "final_converged_pct":   sum(r["simulation_converged"] for r in all_results) / len(all_results) * 100,
        "final_spec_met_pct":    sum(r["final_spec_met"] for r in all_results) / len(all_results) * 100,
        "avg_iterations_used":   sum(r["iterations_used"] for r in all_results) / len(all_results),
        "per_task_type":         {},
    }

    for task, rs in by_task.items():
        n = len(rs)
        summary["per_task_type"][task] = {
            "total":              n,
            "final_spec_met_pct": sum(r["final_spec_met"] for r in rs) / n * 100,
            "final_converged_pct": sum(r["simulation_converged"] for r in rs) / n * 100,
            "avg_iterations_used": sum(r["iterations_used"] for r in rs) / n,
        }

    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets",  default="lpf,hpf,bpf,notch",
                        help="Comma-separated dataset names")
    parser.add_argument("--limit",               type=int, default=None,
                        help="Max entries per dataset (all topologies from the top)")
    parser.add_argument("--sample-per-topology", type=int, default=None,
                        help="Take N entries per topology (evenly samples all topologies)")
    parser.add_argument("--max-iters", type=int, default=MAX_ITERS,
                        help="Max agentic iterations per entry")
    parser.add_argument("--verbose",   action="store_true")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    datasets = [d.strip() for d in args.datasets.split(",")]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"RAG Pipeline — {timestamp}")
    print(f"  Datasets : {datasets}")
    if args.sample_per_topology:
        print(f"  Sample   : {args.sample_per_topology} per topology")
    else:
        print(f"  Limit    : {args.limit or 'all'}")
    print(f"  Max iters: {args.max_iters}")
    print(f"  RAG docs : {RAG_DOCS_DIR}")

    # Validate RAG docs exist
    for ds in datasets:
        rag_prefix = _TASK_TO_RAG.get(ds, ds)
        for topo in ["rc_single", "buffered_rc_single", "rc_multi", "buffered_rc_multi"]:
            p = RAG_DOCS_DIR / f"{rag_prefix}_{topo}.md"
            if not p.exists():
                print(f"  WARNING: missing RAG doc {p.name}")

    print("\nLoading model...")
    model, tokenizer = load_model()

    all_results = []
    for ds in datasets:
        if ds not in DATASET_FILES:
            print(f"Unknown dataset: {ds}"); continue
        print(f"\n=== {ds.upper()} ===")
        results = process_dataset(model, tokenizer, ds,
                                  limit=args.limit,
                                  sample_per_topology=args.sample_per_topology,
                                  max_iters=args.max_iters,
                                  verbose=args.verbose)
        out_path = OUTPUT_DIR / f"results_{ds}_{timestamp}.json"
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"  Saved: {out_path.name}")
        all_results.extend(results)

    summary = compute_summary(all_results, timestamp)
    sum_path = OUTPUT_DIR / f"summary_{timestamp}.json"
    with open(sum_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*50}")
    print(f"  Total: {summary['total_entries']} entries")
    print(f"  Parse:    {summary['final_parse_pct']:.1f}%")
    print(f"  Sim:      {summary['final_converged_pct']:.1f}%")
    print(f"  Spec Met: {summary['final_spec_met_pct']:.1f}%")
    print(f"  Avg iters: {summary['avg_iterations_used']:.2f}")
    for task, s in summary["per_task_type"].items():
        print(f"    {task}: spec={s['final_spec_met_pct']:.1f}%  conv={s['final_converged_pct']:.1f}%")
    print(f"\nSummary: {sum_path}")


if __name__ == "__main__":
    main()
