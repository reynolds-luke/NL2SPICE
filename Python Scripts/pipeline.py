"""
pipeline.py — LLM Netlist Generation & NGSpice Evaluation Pipeline

Usage:
    python pipeline.py                              # run all datasets, all entries
    python pipeline.py --limit 5                    # first 5 entries per dataset
    python pipeline.py --datasets lpf,hpf           # only LPF and HPF datasets
    python pipeline.py --datasets bpf --limit 3     # 3 BPF entries only
    python pipeline.py --batch-size 4               # batch 4 prompts per LLM call (recommended for 4 GPUs)

Batch size guidance (model parallelism via device_map="auto"):
    1 GPU  → batch_size=1 (default)
    2 GPUs → batch_size=2
    4 GPUs → batch_size=4  ← recommended starting point
    Try batch_size=8 if you have A100 80GB cards and want higher throughput.
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
from transformers import AutoTokenizer, AutoModelForCausalLM

# ---------------------------------------------------------------------------
# CONFIG — edit these if paths differ on your cluster
# ---------------------------------------------------------------------------
MODEL_ID    = "Qwen/Qwen2.5-Coder-14B-Instruct"
NGSPICE_PATH = "ngspice"   # set to full path if not in PATH, e.g. "/usr/bin/ngspice"

_SCRIPT_DIR = Path(__file__).parent
DATA_DIR    = _SCRIPT_DIR / "Project_Baseline" / "Test_Data"
OUTPUT_DIR  = _SCRIPT_DIR / "Project_Baseline" / "output"

DATASET_FILES = {
    "lpf":   DATA_DIR / "lpf_dataset.json",
    "hpf":   DATA_DIR / "hpf_dataset.json",
    "bpf":   DATA_DIR / "bpf_dataset.json",
    "notch": DATA_DIR / "notch_dataset.json",
}

MAX_NEW_TOKENS = 512   # SPICE netlists are ~150-400 tokens; 512 gives headroom without wasting time
TEMPERATURE    = 0.2

# ---------------------------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are a circuit design assistant specialized in SPICE netlist generation. "
    "When asked to design a filter, output ONLY the SPICE netlist wrapped in a "
    "```spice ... ``` code block. "
    "\n\n"
    "MANDATORY NODE NAMES — use these exact strings as node names in your netlist:\n"
    "  VIN  = the input node (do NOT create a component named VIN)\n"
    "  VOUT = the output node (the last node of your filter chain MUST be named VOUT)\n"
    "  GND  = ground / 0 V reference\n"
    "\n"
    "VOLTAGE SOURCE — always write the AC stimulus exactly like this:\n"
    "  V1 VIN GND AC 1\n"
    "Do NOT write 'VIN 1 0 ...' or any other element whose name starts with V and is called VIN.\n"
    "\n"
    "COMPONENT NAMING: resistors R1, R2, …; capacitors C1, C2, …; op-amp U1.\n"
    "\n"
    "OP-AMP — if needed, use subcircuit name OPAMP_IDEAL with five pins: INP INN VCC VEE OUT.\n"
    "  Example instance line: U1 node_inp node_inn VCC VEE node_out OPAMP_IDEAL\n"
    "  Do NOT define .SUBCKT OPAMP_IDEAL yourself — it will be provided externally.\n"
    "  Do NOT add power supply sources for VCC or VEE — they are handled externally.\n"
    "\n"
    "Do NOT write 'GND 0' or any standalone ground declaration — GND is just a node name.\n"
    "End the netlist with .END. Do NOT include .AC, .TRAN, or any simulation commands."
)

# Ideal op-amp subcircuit (VCVS-based, gain = 1e6)
# Notes:
#  - Pin names use INP/INN instead of IN+/IN- (NGSpice misparses +/- in .SUBCKT headers)
#  - RVCC/RVEE bleed resistors (1 GΩ) tie the supply pins to ground so they never float,
#    even when the LLM omits power supplies or wires them incorrectly.
#    1 GΩ has negligible effect on any filter frequency response.
OPAMP_IDEAL_SUBCKT = """\
.SUBCKT OPAMP_IDEAL INP INN VCC VEE OUT
EGAIN NET_GAIN 0 INP INN 1E6
ROUT NET_GAIN OUT 75
RLIM OUT 0 1T
RVCC VCC 0 1G
RVEE VEE 0 1G
.ENDS OPAMP_IDEAL
"""

# ---------------------------------------------------------------------------
# MODEL LOADING
# ---------------------------------------------------------------------------

def load_model():
    print(f"Loading tokenizer from {MODEL_ID} ...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    # Left-padding is required for batched generation with decoder-only models.
    # With right-padding the model would attend to padding tokens on the right,
    # corrupting generation for all sequences in the batch except the longest one.
    tokenizer.padding_side = "left"
    print("Loading model ...")
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.bfloat16,
        device_map="auto",
    )
    print(f"Model loaded. Device: {next(model.parameters()).device}")
    return model, tokenizer


# ---------------------------------------------------------------------------
# LLM GENERATION
# ---------------------------------------------------------------------------

def generate_batch(model, tokenizer, prompts: list):
    """
    Run a batch of prompts through the model in a single model.generate() call.
    This amortises the fixed per-forward-pass overhead across all N prompts,
    giving much better GPU utilisation than N separate calls.

    Requires tokenizer.padding_side = "left" (set in load_model).

    Returns a list of (response_text, tokens_generated, elapsed_s) — one per prompt.
    elapsed_s is the wall-clock time for the whole batch divided by batch size,
    giving a per-sequence average comparable to single-prompt timing.
    """
    messages_list = [
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": p}]
        for p in prompts
    ]
    texts = [
        tokenizer.apply_chat_template(m, tokenize=False, add_generation_prompt=True)
        for m in messages_list
    ]

    # Tokenize with padding; left-padding means all sequences are right-aligned
    # so outputs[:, input_len:] correctly isolates the generated tokens for every sequence.
    inputs = tokenizer(texts, return_tensors="pt", padding=True).to(model.device)
    input_len = inputs.input_ids.shape[1]  # padded length, same for all in batch

    t0 = time.time()
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            temperature=TEMPERATURE,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
        )
    elapsed = time.time() - t0
    per_seq_elapsed = elapsed / len(prompts)

    results = []
    for i in range(len(prompts)):
        generated_ids = outputs[i][input_len:]
        tokens_gen = int((generated_ids != tokenizer.eos_token_id).sum()) or generated_ids.shape[0]
        reply = tokenizer.decode(generated_ids, skip_special_tokens=True)
        results.append((reply, tokens_gen, per_seq_elapsed))

    return results


def generate_netlist(model, tokenizer, prompt: str):
    """Single-prompt wrapper around generate_batch. Returns (response, tokens, elapsed_s)."""
    return generate_batch(model, tokenizer, [prompt])[0]


# ---------------------------------------------------------------------------
# NETLIST EXTRACTION
# ---------------------------------------------------------------------------

def validate_netlist(netlist: str) -> list:
    """
    Return a list of warning strings for common LLM mistakes.
    An empty list means the netlist looks structurally sound.
    These don't block simulation but are recorded in the output.
    """
    warnings = []
    upper = netlist.upper()

    # VOUT must appear as a node somewhere
    if not re.search(r'\bVOUT\b', netlist, re.IGNORECASE):
        warnings.append("VOUT node not found — v(vout) will fail in NGSpice")

    # V1 should be present as the AC stimulus
    if not re.search(r'^V1\b', netlist, re.IGNORECASE | re.MULTILINE):
        warnings.append("V1 source not found — no AC stimulus defined")

    # Detect a component named VIN (starts with V, so SPICE treats it as a vsource)
    # This causes duplicate parallel sources when V1 is also present
    if re.search(r'^VIN\b', netlist, re.IGNORECASE | re.MULTILINE):
        warnings.append("Component named 'VIN' found — conflicts with VIN node name; "
                        "likely causes a duplicate voltage source")

    # Detect standalone 'GND 0' line — invalid SPICE, NGSpice aborts with bad syntax
    if re.search(r'^GND\s+0\s*$', netlist, re.IGNORECASE | re.MULTILINE):
        warnings.append("Standalone 'GND 0' line found — not valid SPICE syntax")

    return warnings


def extract_netlist(response_text: str):
    """
    Extract SPICE netlist from LLM response.
    Returns the netlist string, or None if extraction fails.
    """
    # Primary: ```spice ... ``` block
    m = re.search(r"```(?:spice|SPICE)?\s*\n(.*?)```", response_text, re.DOTALL | re.IGNORECASE)
    if m:
        netlist = m.group(1).strip()
        if ".END" in netlist.upper():
            return netlist

    # Fallback: look for lines from first '*' or component line up to .END
    lines = response_text.splitlines()
    start = None
    end = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if start is None:
            # A line starting with * (comment/title) or a component (R/C/V/L/E/U/X...)
            if stripped.startswith("*") or re.match(r"^[RCVLEUXB]\w*\s", stripped, re.IGNORECASE):
                start = i
        if stripped.upper() == ".END" or stripped.upper().startswith(".END "):
            end = i
            break

    if start is not None and end is not None and end >= start:
        return "\n".join(lines[start : end + 1]).strip()

    return None


# ---------------------------------------------------------------------------
# SPICE FILE CONSTRUCTION
# ---------------------------------------------------------------------------

def _has_node(netlist: str, node: str) -> bool:
    """Check if a node name appears in the netlist (case-insensitive)."""
    return bool(re.search(r'\b' + re.escape(node) + r'\b', netlist, re.IGNORECASE))


def build_spice_file(netlist: str, params: dict, task_type: str, out_data_file: str) -> str:
    """
    Takes the raw netlist (no .AC command) and returns a complete .cir string
    ready for NGSpice batch simulation.

    Uses a .control block with 'wrdata' (matching the NGSpice_Trials/test_rc_ac.py pattern)
    to write frequency-domain results to out_data_file.
    """
    # In SPICE the first line is ALWAYS the circuit title (ignored by the simulator).
    # We must start with a title comment so nothing useful is silently discarded.
    lines = ["* LLM-generated filter netlist — auto-simulated by pipeline.py"]
    lines.append("")

    # ---- Inject ideal op-amp subcircuit if U1 present and not already defined ----
    needs_opamp = bool(re.search(r'\bU1\b', netlist, re.IGNORECASE))
    has_subckt  = bool(re.search(r'\.SUBCKT\s+OPAMP_IDEAL', netlist, re.IGNORECASE))

    if needs_opamp and not has_subckt:
        # Inject subcircuit definition only — no VVCC/VVEE power supplies.
        # The subcircuit's internal RVCC/RVEE bleed resistors prevent VCC/VEE from
        # floating regardless of what the LLM does with power supplies.
        lines.append(OPAMP_IDEAL_SUBCKT)

    # Strip any existing .END so we can append the control block cleanly
    netlist_body = re.sub(r'^\s*\.END\s*$', '', netlist, flags=re.IGNORECASE | re.MULTILINE).rstrip()

    # In SPICE, subcircuit instances MUST use the X prefix.
    # The dataset spec uses U1 as the op-amp designator, so we substitute here
    # rather than changing the LLM output convention.
    netlist_body = re.sub(r'\bU(\d+)\b', r'X\1', netlist_body)

    # Remove shorted voltage sources — lines where a V-element has both terminals
    # on the same node (e.g. "VCC 0 0" or "VEE 0 0 DC -15").
    # The LLM sometimes writes these as power-supply placeholders; NGSpice aborts on them.
    def _remove_shorted_vsrcs(text):
        clean = []
        for line in text.splitlines():
            stripped = line.strip()
            # Match: Vxxx  node1  node2  [rest]  where node1 == node2
            m = re.match(r'^(V\S+)\s+(\S+)\s+(\S+)', stripped, re.IGNORECASE)
            if m and m.group(2).lower() == m.group(3).lower():
                continue  # drop shorted source
            clean.append(line)
        return '\n'.join(clean)

    netlist_body = _remove_shorted_vsrcs(netlist_body)

    # Remove standalone "GND 0" lines — the LLM writes these as ground declarations
    # but they are not valid SPICE syntax and cause NGSpice to abort.
    netlist_body = re.sub(r'^\s*GND\s+0\s*$', '', netlist_body, flags=re.IGNORECASE | re.MULTILINE)

    lines.append(netlist_body)
    lines.append("")

    # ---- Build AC sweep frequency range from params ----
    ac_start, ac_stop = _ac_freq_range(params, task_type)

    # Use .control block with wrdata — same pattern as NGSpice_Trials/test_rc_ac.py
    lines.append(f".ac dec 200 {ac_start:.6g} {ac_stop:.6g}")
    lines.append("")
    lines.append(".control")
    lines.append("run")
    lines.append(f"wrdata {out_data_file} v(vout)")
    lines.append(".endc")
    lines.append("")
    lines.append(".end")

    return "\n".join(lines)


def _ac_freq_range(params: dict, task_type: str):
    """Return (start_hz, stop_hz) for the .AC sweep, spanning well beyond the filter specs."""
    decade_margin = 2  # decades below/above key frequencies

    if task_type == "low_pass_filter":
        fc = params.get("fc_hz", 1000)
        return fc / 10**decade_margin, fc * 10**decade_margin

    if task_type == "high_pass_filter":
        fc = params.get("fc_hz", 1000)
        return fc / 10**decade_margin, fc * 10**decade_margin

    if task_type == "band_pass_filter":
        fc_low  = params.get("fc_low_hz", 100)
        fc_high = params.get("fc_high_hz", 1000)
        return fc_low / 10**decade_margin, fc_high * 10**decade_margin

    if task_type == "notch_filter":
        fc_low  = params.get("fc_low_hz",  params.get("f_notch_hz", 1000) / 10)
        fc_high = params.get("fc_high_hz", params.get("f_notch_hz", 1000) * 10)
        return fc_low / 10**decade_margin, fc_high * 10**decade_margin

    # Generic fallback
    return 1.0, 1e6


# ---------------------------------------------------------------------------
# NGSPICE SIMULATION
# ---------------------------------------------------------------------------

def run_ngspice(spice_content: str, tmp_dir: str):
    """
    Write circuit to a temp file and run NGSpice in batch mode.
    Matches the pattern in NGSpice_Trials/test_rc_ac.py:
      - uses 'ngspice -b circuit.cir' (no -o flag)
      - data is written by the .control 'wrdata' command inside the netlist

    Returns (data_file_path, stderr_text, returncode).
    The data file path is where 'wrdata' wrote the AC results.
    """
    cir_path  = os.path.join(tmp_dir, "circuit.cir")
    data_path = os.path.join(tmp_dir, "ac_out.txt")

    with open(cir_path, "w") as f:
        f.write(spice_content)

    # NGSpice writes ac_out.txt relative to its CWD — run from tmp_dir
    result = subprocess.run(
        [NGSPICE_PATH, "-b", cir_path],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=tmp_dir,
    )

    return data_path, result.stderr, result.returncode


# ---------------------------------------------------------------------------
# NGSPICE OUTPUT PARSING
# ---------------------------------------------------------------------------

def parse_ac_results(data_file_path: str) -> dict:
    """
    Parse the wrdata output file written by NGSpice's .control block.
    Matches the parse_wrdata pattern in NGSpice_Trials/test_rc_ac.py.

    wrdata writes rows of:  frequency  real [imag]
    (2 or 3 columns; for complex AC data NGSpice may write real+imag separately)

    Returns a dict: {freq_hz: magnitude_db}
    """
    results = {}

    if not os.path.exists(data_file_path):
        return results

    with open(data_file_path) as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            freq = float(parts[0])
            real = float(parts[1])
            imag = float(parts[2]) if len(parts) >= 3 else 0.0
            mag_linear = math.sqrt(real * real + imag * imag)
            if mag_linear > 0:
                mag_db = 20.0 * math.log10(mag_linear)
            else:
                mag_db = -300.0
            results[freq] = mag_db
        except (ValueError, OverflowError, IndexError):
            continue

    return results


# ---------------------------------------------------------------------------
# METRICS CALCULATION
# ---------------------------------------------------------------------------

def calculate_metrics(ac_data: dict, params: dict, task_type: str) -> dict:
    """
    Compute performance metrics from the simulated frequency response.
    ac_data: {freq_hz: magnitude_db}
    """
    if not ac_data:
        return {}

    freqs = sorted(ac_data.keys())
    mags  = [ac_data[f] for f in freqs]

    metrics = {}

    if task_type == "low_pass_filter":
        metrics.update(_lpf_metrics(freqs, mags, params))

    elif task_type == "high_pass_filter":
        metrics.update(_hpf_metrics(freqs, mags, params))

    elif task_type == "band_pass_filter":
        metrics.update(_bpf_metrics(freqs, mags, params))

    elif task_type == "notch_filter":
        metrics.update(_notch_metrics(freqs, mags, params))

    return metrics


def _interp_mag(freqs, mags, target_freq):
    """Linear interpolation of magnitude at target_freq (log-freq scale)."""
    if target_freq <= freqs[0]:
        return mags[0]
    if target_freq >= freqs[-1]:
        return mags[-1]
    for i in range(len(freqs) - 1):
        if freqs[i] <= target_freq <= freqs[i + 1]:
            t = math.log(target_freq / freqs[i]) / math.log(freqs[i + 1] / freqs[i])
            return mags[i] + t * (mags[i + 1] - mags[i])
    return mags[-1]


def _find_cutoff(freqs, mags, ref_db, threshold_db=-3.0, direction="falling"):
    """
    Find the frequency where the magnitude first crosses ref_db + threshold_db.
    direction='falling' for LPF/notch, 'rising' for HPF.
    """
    target = ref_db + threshold_db
    if direction == "falling":
        for i in range(len(freqs) - 1):
            if mags[i] >= target >= mags[i + 1]:
                t = (mags[i] - target) / (mags[i] - mags[i + 1])
                return freqs[i] * (freqs[i + 1] / freqs[i]) ** t
    else:  # rising
        for i in range(len(freqs) - 1):
            if mags[i] <= target <= mags[i + 1]:
                t = (target - mags[i]) / (mags[i + 1] - mags[i])
                return freqs[i] * (freqs[i + 1] / freqs[i]) ** t
    return None


def _passband_ripple(freqs, mags, f_low, f_high):
    """Max peak-to-trough variation within [f_low, f_high]."""
    pb_mags = [m for f, m in zip(freqs, mags) if f_low <= f <= f_high]
    if len(pb_mags) < 2:
        return None
    return max(pb_mags) - min(pb_mags)


def _lpf_metrics(freqs, mags, params):
    fc_spec   = params.get("fc_hz", None)
    fs_spec   = params.get("fs_hz", None)
    atten_req = params.get("atten_db", None)
    pb_loss   = params.get("pb_loss_db", 3.0)

    ref_db = max(mags)  # passband reference level

    m = {}
    # -3dB cutoff
    fc_meas = _find_cutoff(freqs, mags, ref_db, threshold_db=-3.0, direction="falling")
    if fc_meas and fc_spec:
        m["cutoff_freq_hz_measured"] = fc_meas
        m["cutoff_freq_error_pct"]   = abs(fc_meas - fc_spec) / fc_spec * 100

    # Passband ripple (DC to fc)
    if fc_spec:
        ripple = _passband_ripple(freqs, mags, freqs[0], fc_spec)
        if ripple is not None:
            m["passband_ripple_db"] = round(ripple, 4)

    # Attenuation at stopband freq
    if fs_spec:
        atten_meas = ref_db - _interp_mag(freqs, mags, fs_spec)
        m["attenuation_at_fs"] = {
            "fs_hz":        fs_spec,
            "achieved_db":  round(atten_meas, 2),
            "required_db":  atten_req,
            "met":          (atten_req is None) or (atten_meas >= atten_req),
        }

    # Filter response match: cutoff within 20% + stopband met
    cutoff_ok   = fc_meas and fc_spec and (abs(fc_meas - fc_spec) / fc_spec < 0.20)
    stopband_ok = (atten_req is None) or (
        fs_spec and (ref_db - _interp_mag(freqs, mags, fs_spec)) >= atten_req
    )
    m["filter_response_match"] = bool(cutoff_ok and stopband_ok)

    return m


def _hpf_metrics(freqs, mags, params):
    fc_spec   = params.get("fc_hz", None)
    fs_spec   = params.get("fs_hz", None)
    atten_req = params.get("atten_db", None)

    ref_db = max(mags)
    m = {}

    fc_meas = _find_cutoff(freqs, mags, ref_db, threshold_db=-3.0, direction="rising")
    if fc_meas and fc_spec:
        m["cutoff_freq_hz_measured"] = fc_meas
        m["cutoff_freq_error_pct"]   = abs(fc_meas - fc_spec) / fc_spec * 100

    if fc_spec:
        ripple = _passband_ripple(freqs, mags, fc_spec, freqs[-1])
        if ripple is not None:
            m["passband_ripple_db"] = round(ripple, 4)

    if fs_spec:
        atten_meas = ref_db - _interp_mag(freqs, mags, fs_spec)
        m["attenuation_at_fs"] = {
            "fs_hz":       fs_spec,
            "achieved_db": round(atten_meas, 2),
            "required_db": atten_req,
            "met":         (atten_req is None) or (atten_meas >= atten_req),
        }

    cutoff_ok   = fc_meas and fc_spec and (abs(fc_meas - fc_spec) / fc_spec < 0.20)
    stopband_ok = (atten_req is None) or (
        fs_spec and (ref_db - _interp_mag(freqs, mags, fs_spec)) >= atten_req
    )
    m["filter_response_match"] = bool(cutoff_ok and stopband_ok)

    return m


def _bpf_metrics(freqs, mags, params):
    fc_low   = params.get("fc_low_hz", None)
    fc_high  = params.get("fc_high_hz", None)
    fs_low   = params.get("fs_low_hz", None)
    fs_high  = params.get("fs_high_hz", None)
    al_req   = params.get("atten_low_db", None)
    ah_req   = params.get("atten_high_db", None)
    pb_loss  = params.get("pb_loss_db", 3.0)

    ref_db = max(mags)
    m = {}

    # Lower -3dB
    fc_low_meas  = _find_cutoff(freqs, mags, ref_db, threshold_db=-3.0, direction="rising")
    # Upper -3dB (search from peak downward on the high side)
    peak_idx = mags.index(ref_db)
    upper_freqs = freqs[peak_idx:]
    upper_mags  = mags[peak_idx:]
    fc_high_meas = _find_cutoff(upper_freqs, upper_mags, ref_db, threshold_db=-3.0, direction="falling")

    if fc_low_meas and fc_low:
        m["cutoff_freq_low_hz_measured"] = fc_low_meas
        m["cutoff_freq_low_error_pct"]   = abs(fc_low_meas - fc_low) / fc_low * 100
    if fc_high_meas and fc_high:
        m["cutoff_freq_high_hz_measured"] = fc_high_meas
        m["cutoff_freq_high_error_pct"]   = abs(fc_high_meas - fc_high) / fc_high * 100

    if fc_low and fc_high:
        ripple = _passband_ripple(freqs, mags, fc_low, fc_high)
        if ripple is not None:
            m["passband_ripple_db"] = round(ripple, 4)

    if fs_low:
        al_meas = ref_db - _interp_mag(freqs, mags, fs_low)
        m["attenuation_at_fs_low"] = {
            "fs_hz": fs_low, "achieved_db": round(al_meas, 2),
            "required_db": al_req, "met": (al_req is None) or (al_meas >= al_req),
        }
    if fs_high:
        ah_meas = ref_db - _interp_mag(freqs, mags, fs_high)
        m["attenuation_at_fs_high"] = {
            "fs_hz": fs_high, "achieved_db": round(ah_meas, 2),
            "required_db": ah_req, "met": (ah_req is None) or (ah_meas >= ah_req),
        }

    low_ok  = (fc_low_meas  is None or fc_low  is None) or (abs(fc_low_meas  - fc_low)  / fc_low  < 0.20)
    high_ok = (fc_high_meas is None or fc_high is None) or (abs(fc_high_meas - fc_high) / fc_high < 0.20)
    stop_low_ok  = (al_req is None) or (fs_low  and (ref_db - _interp_mag(freqs, mags, fs_low))  >= al_req)
    stop_high_ok = (ah_req is None) or (fs_high and (ref_db - _interp_mag(freqs, mags, fs_high)) >= ah_req)
    m["filter_response_match"] = bool(low_ok and high_ok and stop_low_ok and stop_high_ok)

    return m


def _notch_metrics(freqs, mags, params):
    f_notch  = params.get("f_notch_hz", None)
    fc_low   = params.get("fc_low_hz",  None)
    fc_high  = params.get("fc_high_hz", None)
    fs_low   = params.get("fs_low_hz",  None)
    fs_high  = params.get("fs_high_hz", None)
    depth_req = params.get("notch_depth_db", None)
    al_req    = params.get("atten_low_db", None)
    ah_req    = params.get("atten_high_db", None)

    ref_db = max(mags)
    m = {}

    # Notch depth: attenuation at f_notch
    if f_notch:
        notch_mag   = _interp_mag(freqs, mags, f_notch)
        notch_depth = ref_db - notch_mag
        m["notch_depth_db"] = round(notch_depth, 2)
        if depth_req:
            m["notch_depth_met"] = notch_depth >= depth_req

    if fc_low and fc_high:
        ripple = _passband_ripple(freqs, mags, freqs[0], fc_low)
        ripple2 = _passband_ripple(freqs, mags, fc_high, freqs[-1])
        if ripple is not None:
            m["passband_ripple_low_db"]  = round(ripple,  4)
        if ripple2 is not None:
            m["passband_ripple_high_db"] = round(ripple2, 4)

    if fs_low:
        al_meas = ref_db - _interp_mag(freqs, mags, fs_low)
        m["attenuation_at_fs_low"] = {
            "fs_hz": fs_low, "achieved_db": round(al_meas, 2),
            "required_db": al_req, "met": (al_req is None) or (al_meas >= al_req),
        }
    if fs_high:
        ah_meas = ref_db - _interp_mag(freqs, mags, fs_high)
        m["attenuation_at_fs_high"] = {
            "fs_hz": fs_high, "achieved_db": round(ah_meas, 2),
            "required_db": ah_req, "met": (ah_req is None) or (ah_meas >= ah_req),
        }

    depth_ok = (depth_req is None) or (
        f_notch and (ref_db - _interp_mag(freqs, mags, f_notch)) >= depth_req
    )
    m["filter_response_match"] = bool(depth_ok)

    return m


# ---------------------------------------------------------------------------
# PER-ENTRY PROCESSING
# ---------------------------------------------------------------------------

def process_entry(model, tokenizer, entry: dict, idx: int, source_file: str,
                  prefetched_response=None, prefetched_tokens=None,
                  prefetched_elapsed=None) -> dict:
    result = {
        "index":       idx,
        "source_file": source_file,
        "task_type":   entry.get("task_type", "unknown"),
        "topology":    entry.get("topology",  "unknown"),
        "params":      entry.get("params",    {}),
        "template_i":  entry.get("template_i", None),
        "prompt":      entry.get("prompt",    ""),
    }

    # --- LLM generation (use pre-fetched result from generate_batch, or fall back to single call) ---
    if prefetched_response is not None:
        response, tokens, elapsed = prefetched_response, prefetched_tokens or 0, prefetched_elapsed or 0.0
    else:
        try:
            response, tokens, elapsed = generate_netlist(model, tokenizer, entry["prompt"])
        except Exception as e:
            result.update({
                "llm_response":        None,
                "generation_time_s":   None,
                "tokens_generated":    0,
                "parse_success":       False,
                "simulation_converged": False,
                "metrics":             {},
                "error":               f"LLM generation error: {e}",
            })
            return result

    if response is None:
        result.update({
            "llm_response":        None,
            "generation_time_s":   None,
            "tokens_generated":    0,
            "parse_success":       False,
            "simulation_converged": False,
            "metrics":             {},
            "error":               "LLM generation failed (batch error)",
        })
        return result

    result["llm_response"]      = response
    result["generation_time_s"] = round(elapsed, 3)
    result["tokens_generated"]  = tokens

    # --- Netlist extraction ---
    netlist = extract_netlist(response)
    result["generated_netlist"] = netlist
    result["parse_success"]     = netlist is not None

    if not netlist:
        result.update({
            "simulation_converged": False,
            "metrics": {},
        })
        return result

    # --- Structural validation (non-blocking — warns but still attempts simulation) ---
    result["netlist_warnings"] = validate_netlist(netlist)

    # --- NGSpice simulation ---
    # build_spice_file needs to know where wrdata will write its output
    # We use a temp dir; the data file path is passed into the netlist's .control block
    with tempfile.TemporaryDirectory() as tmp_dir:
        data_file = os.path.join(tmp_dir, "ac_out.txt")
        spice_content = build_spice_file(
            netlist, entry.get("params", {}), entry.get("task_type", ""), data_file
        )
        result["spice_file_content"] = spice_content

        try:
            data_path, stderr, returncode = run_ngspice(spice_content, tmp_dir)
        except subprocess.TimeoutExpired:
            result.update({
                "simulation_converged": False,
                "metrics": {},
                "error": "NGSpice timeout",
            })
            return result
        except FileNotFoundError:
            result.update({
                "simulation_converged": False,
                "metrics": {},
                "error": f"NGSpice not found at '{NGSPICE_PATH}'. Set NGSPICE_PATH in the config.",
            })
            return result

        result["ngspice_returncode"]    = returncode
        result["ngspice_stderr"]        = stderr[:2000]  # truncate for storage
        result["simulation_converged"]  = (returncode == 0)

        # --- Metrics (parse while still inside tmp_dir) ---
        if result["simulation_converged"]:
            ac_data = parse_ac_results(data_path)
            if ac_data:
                metrics = calculate_metrics(
                    ac_data, entry.get("params", {}), entry.get("task_type", "")
                )
            else:
                metrics = {"warning": "No AC data parsed from NGSpice wrdata output"}
        else:
            metrics = {}

    result["metrics"] = metrics
    return result


# ---------------------------------------------------------------------------
# PROGRESS REPORTING
# ---------------------------------------------------------------------------

_pipeline_start_time = None  # set in main()

def write_progress(results_so_far: list, current_dataset: str,
                   dataset_done: int, dataset_total: int,
                   all_datasets: list, datasets_done: int):
    """
    Write a human-readable progress file to OUTPUT_DIR/progress.txt.
    Safe to call after every batch — overwrites in place.
    Read from the login node with:   watch -n 30 cat progress.txt
    """
    now        = time.time()
    elapsed_s  = now - _pipeline_start_time if _pipeline_start_time else 0
    elapsed_str = _fmt_duration(elapsed_s)

    total_done  = len(results_so_far)
    parsed      = sum(1 for r in results_so_far if r.get("parse_success"))
    simulated   = sum(1 for r in results_so_far if r.get("simulation_converged"))
    matched     = sum(1 for r in results_so_far if r.get("metrics", {}).get("filter_response_match"))

    parse_pct = parsed    / total_done * 100 if total_done else 0
    sim_pct   = simulated / total_done * 100 if total_done else 0
    match_pct = matched   / simulated  * 100 if simulated  else 0

    # ETA: based on average time per entry so far
    gen_times = [r["generation_time_s"] for r in results_so_far if r.get("generation_time_s")]
    if gen_times and total_done > 0:
        # Use elapsed wall-clock time per entry (includes NGSpice time)
        rate = elapsed_s / total_done          # seconds per entry
        # Remaining: entries left in current dataset + full remaining datasets
        # We don't know totals for future datasets so estimate from current average
        entries_remaining = (dataset_total - dataset_done)
        remaining_datasets_entries = 0  # unknown without loading files; show "?" later
        eta_s = rate * entries_remaining
        eta_str = _fmt_duration(eta_s) + " (current dataset)"
    else:
        eta_str = "calculating..."

    lines = [
        "=" * 56,
        f"  PIPELINE PROGRESS  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 56,
        f"  Elapsed:         {elapsed_str}",
        f"  Datasets:        {datasets_done}/{len(all_datasets)}  "
        f"({', '.join(all_datasets)})",
        f"  Current dataset: {current_dataset}  "
        f"[{dataset_done}/{dataset_total} entries]",
        "",
        f"  Total processed: {total_done}",
        f"  Parse success:   {parsed}/{total_done}  ({parse_pct:.1f}%)",
        f"  Sim converged:   {simulated}/{total_done}  ({sim_pct:.1f}%)",
        f"  Response match:  {matched}/{simulated}  ({match_pct:.1f}%)"
        if simulated else "  Response match:  n/a",
        "",
        f"  ETA:             {eta_str}",
        "=" * 56,
    ]

    # Per-dataset breakdown
    task_types = {}
    for r in results_so_far:
        tt = r.get("task_type", "unknown")
        if tt not in task_types:
            task_types[tt] = {"done": 0, "parsed": 0, "simulated": 0}
        task_types[tt]["done"]      += 1
        task_types[tt]["parsed"]    += int(r.get("parse_success", False))
        task_types[tt]["simulated"] += int(r.get("simulation_converged", False))

    if task_types:
        lines.append("  Per task type:")
        for tt, s in sorted(task_types.items()):
            pp = s["parsed"]    / s["done"] * 100
            sp = s["simulated"] / s["done"] * 100
            lines.append(f"    {tt:<22} done={s['done']:>4}  "
                         f"parse={pp:5.1f}%  sim={sp:5.1f}%")
        lines.append("=" * 56)

    progress_path = OUTPUT_DIR / "progress.txt"
    with open(progress_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem  = divmod(seconds, 3600)
    m, s    = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


# ---------------------------------------------------------------------------
# DATASET PROCESSING
# ---------------------------------------------------------------------------

def process_dataset(model, tokenizer, dataset_name: str, json_path: Path,
                    limit=None, batch_size=1,
                    all_results_ref: list = None,
                    all_datasets: list = None, datasets_done: int = 0) -> list:
    """
    all_results_ref: the shared list of ALL results so far (across datasets),
                     used to compute cumulative stats in progress.txt.
    """
    print(f"\n{'='*60}")
    print(f"Processing dataset: {dataset_name}  ({json_path.name})")
    print(f"{'='*60}")

    with open(json_path) as f:
        entries = json.load(f)

    if limit:
        entries = entries[:limit]
    total = len(entries)
    print(f"Entries to process: {total}  |  batch_size: {batch_size}")

    results = []
    checkpoint_path = OUTPUT_DIR / f"checkpoint_{dataset_name}.json"
    completed = 0

    # Iterate in chunks of batch_size
    for batch_start in range(0, total, batch_size):
        batch_entries = entries[batch_start : batch_start + batch_size]
        prompts = [e["prompt"] for e in batch_entries]

        # --- Batched LLM generation ---
        print(f"  Generating batch [{batch_start+1}–{batch_start+len(batch_entries)}/{total}] ...",
              end=" ", flush=True)
        try:
            llm_results = generate_batch(model, tokenizer, prompts)
            print(f"done ({llm_results[0][2]*len(batch_entries):.1f}s for batch)")
        except Exception as e:
            print(f"ERROR: {e}")
            llm_results = [(None, 0, 0.0)] * len(batch_entries)

        # --- Per-entry post-processing (netlist extraction + NGSpice, CPU-bound) ---
        for local_i, (entry, (response, tokens, elapsed)) in enumerate(
            zip(batch_entries, llm_results)
        ):
            global_i = batch_start + local_i
            print(f"    [{global_i+1}/{total}] task={entry.get('task_type','?')} "
                  f"topo={entry.get('topology','?')} ...", end=" ", flush=True)

            result = process_entry(
                model, tokenizer, entry, global_i, json_path.name,
                prefetched_response=response,
                prefetched_tokens=tokens,
                prefetched_elapsed=elapsed,
            )

            status = []
            if result.get("parse_success"):
                status.append("parsed")
            if result.get("simulation_converged"):
                status.append("simulated")
            print(" | ".join(status) if status else "FAILED")

            results.append(result)
            if all_results_ref is not None:
                all_results_ref.append(result)
            completed += 1

        # Save checkpoint + update progress file after each batch
        if completed % 10 == 0 or completed == total:
            with open(checkpoint_path, "w") as f:
                json.dump(results, f, indent=2)

        write_progress(
            results_so_far  = all_results_ref if all_results_ref is not None else results,
            current_dataset = dataset_name,
            dataset_done    = completed,
            dataset_total   = total,
            all_datasets    = all_datasets or [dataset_name],
            datasets_done   = datasets_done,
        )

    return results


# ---------------------------------------------------------------------------
# SUMMARY COMPUTATION
# ---------------------------------------------------------------------------

def compute_summary(all_results: list) -> dict:
    if not all_results:
        return {}

    total = len(all_results)
    parsed   = [r for r in all_results if r.get("parse_success")]
    simulated = [r for r in all_results if r.get("simulation_converged")]
    matched   = [r for r in all_results if r.get("metrics", {}).get("filter_response_match")]

    gen_times = [r["generation_time_s"] for r in all_results if r.get("generation_time_s")]
    tokens    = [r["tokens_generated"]  for r in parsed if r.get("tokens_generated")]

    # Per task_type breakdown
    task_types = sorted({r.get("task_type", "unknown") for r in all_results})
    per_task = {}
    for tt in task_types:
        subset  = [r for r in all_results  if r.get("task_type") == tt]
        sim_sub = [r for r in simulated    if r.get("task_type") == tt]
        par_sub = [r for r in parsed       if r.get("task_type") == tt]
        mat_sub = [r for r in matched      if r.get("task_type") == tt]

        cutoff_errs = [
            r["metrics"].get("cutoff_freq_error_pct") or
            r["metrics"].get("cutoff_freq_low_error_pct")
            for r in sim_sub if r.get("metrics")
        ]
        cutoff_errs = [e for e in cutoff_errs if e is not None]

        per_task[tt] = {
            "total":                   len(subset),
            "parse_success_rate_pct":  round(len(par_sub) / len(subset) * 100, 1) if subset else 0,
            "simulation_convergence_pct": round(len(sim_sub) / len(subset) * 100, 1) if subset else 0,
            "filter_response_match_pct": round(len(mat_sub) / len(sim_sub) * 100, 1) if sim_sub else 0,
            "avg_cutoff_freq_error_pct": round(sum(cutoff_errs) / len(cutoff_errs), 2) if cutoff_errs else None,
        }

    summary = {
        "generated_at": datetime.now().isoformat(),
        "total_entries": total,
        "parse_success_rate_pct":       round(len(parsed)    / total * 100, 1),
        "simulation_convergence_pct":   round(len(simulated) / total * 100, 1),
        "filter_response_match_pct":    round(len(matched)   / len(simulated) * 100, 1) if simulated else 0,
        "avg_generation_time_s":        round(sum(gen_times) / len(gen_times), 3) if gen_times else None,
        "token_efficiency_per_netlist": round(sum(tokens) / len(tokens), 1) if tokens else None,
        "per_task_type":                per_task,
    }
    return summary


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LLM Netlist Generation & NGSpice Evaluation Pipeline")
    parser.add_argument("--limit",      type=int, default=None,
                        help="Max entries to process per dataset (default: all)")
    parser.add_argument("--datasets",   type=str, default=None,
                        help="Comma-separated dataset names to run, e.g. lpf,hpf (default: all)")
    parser.add_argument("--batch-size", type=int, default=1,
                        help="Number of prompts per LLM generate() call. "
                             "Recommended: 4 for 4 GPUs, 1 for single GPU (default: 1)")
    args = parser.parse_args()

    # Select datasets
    if args.datasets:
        selected = [d.strip() for d in args.datasets.split(",")]
        dataset_map = {k: v for k, v in DATASET_FILES.items() if k in selected}
    else:
        dataset_map = DATASET_FILES

    if not dataset_map:
        print(f"No matching datasets found. Available: {', '.join(DATASET_FILES)}")
        return

    # Ensure output dir exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Record start time for ETA calculations in progress.txt
    global _pipeline_start_time
    _pipeline_start_time = time.time()

    # Write an immediate status so progress.txt shows the job has started
    # even while the model is still loading (can take 2-5 minutes)
    ds_names_preview = list(dataset_map.keys())
    progress_path = OUTPUT_DIR / "progress.txt"
    with open(progress_path, "w") as f:
        f.write(
            f"========================================================\n"
            f"  PIPELINE PROGRESS  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"========================================================\n"
            f"  Status:   LOADING MODEL (this takes 2-5 minutes) ...\n"
            f"  Datasets: {', '.join(ds_names_preview)}\n"
            f"  Batch size: {args.batch_size}\n"
            f"========================================================\n"
        )

    # Load model once
    model, tokenizer = load_model()

    all_results = []      # shared across datasets — passed into process_dataset
    ds_names    = list(dataset_map.keys())

    for ds_idx, (ds_name, ds_path) in enumerate(dataset_map.items()):
        if not ds_path.exists():
            print(f"WARNING: {ds_path} not found, skipping.")
            continue

        results = process_dataset(
            model, tokenizer, ds_name, ds_path,
            limit=args.limit, batch_size=args.batch_size,
            all_results_ref=all_results,
            all_datasets=ds_names,
            datasets_done=ds_idx,
        )
        # all_results already populated via all_results_ref; no extend needed

        # Save per-dataset results (results list returned by process_dataset)
        out_path = OUTPUT_DIR / f"results_{ds_name}_{timestamp}.json"
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"  Saved: {out_path}")

        # Mark dataset complete in progress file
        write_progress(
            results_so_far  = all_results,
            current_dataset = ds_name + " (done)",
            dataset_done    = len(results),
            dataset_total   = len(results),
            all_datasets    = ds_names,
            datasets_done   = ds_idx + 1,
        )

    # Save summary
    summary = compute_summary(all_results)
    summary_path = OUTPUT_DIR / f"summary_{timestamp}.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved: {summary_path}")

    # Print summary to console
    print("\n" + "="*60)
    print("PIPELINE SUMMARY")
    print("="*60)
    print(f"  Total entries:              {summary.get('total_entries')}")
    print(f"  Parse success rate:         {summary.get('parse_success_rate_pct')}%")
    print(f"  Simulation convergence:     {summary.get('simulation_convergence_pct')}%")
    print(f"  Filter response match:      {summary.get('filter_response_match_pct')}%")
    print(f"  Avg generation time:        {summary.get('avg_generation_time_s')} s")
    print(f"  Token efficiency:           {summary.get('token_efficiency_per_netlist')} tokens/netlist")
    print("\n  Per task type:")
    for tt, stats in summary.get("per_task_type", {}).items():
        print(f"    {tt}:")
        print(f"      parse={stats['parse_success_rate_pct']}%  "
              f"sim={stats['simulation_convergence_pct']}%  "
              f"match={stats['filter_response_match_pct']}%  "
              f"fc_err={stats['avg_cutoff_freq_error_pct']}%")


if __name__ == "__main__":
    main()
