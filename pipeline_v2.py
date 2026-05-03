"""
pipeline_v2.py — LLM Netlist Evaluation Pipeline for New_Datagen datasets

Usage:
    python pipeline_v2.py                              # run all datasets
    python pipeline_v2.py --limit 5                    # first 5 entries per dataset
    python pipeline_v2.py --datasets lpf,hpf           # only LPF and HPF
    python pipeline_v2.py --datasets bpf --limit 3     # 3 BPF entries
    python pipeline_v2.py --batch-size 4               # batch 4 prompts per LLM call
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
# CONFIG
# ---------------------------------------------------------------------------
MODEL_ID     = "Qwen/Qwen2.5-Coder-14B-Instruct"
NGSPICE_PATH = "ngspice"

_SCRIPT_DIR = Path(__file__).parent
DATA_DIR    = _SCRIPT_DIR / "New_Datagen" / "prompts"
OUTPUT_DIR  = _SCRIPT_DIR / "New_Datagen" / "output"

DATASET_FILES = {
    "lpf":   DATA_DIR / "lpf_dataset.json",
    "hpf":   DATA_DIR / "hpf_dataset.json",
    "bpf":   DATA_DIR / "bpf_dataset.json",
    "notch": DATA_DIR / "notch_dataset.json",
}

MAX_NEW_TOKENS = 512
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
# FIELD MAPPING — new dataset uses different key names than the old one
# ---------------------------------------------------------------------------

# Map new dataset "task" values to the task_type strings the metrics functions expect
_TASK_MAP = {
    "low_pass":  "low_pass_filter",
    "high_pass": "high_pass_filter",
    "band_pass": "band_pass_filter",
    "notch":     "notch_filter",
}


def _get_task_type(entry: dict) -> str:
    return _TASK_MAP.get(entry.get("task", ""), entry.get("task", "unknown"))


def _build_params(entry: dict) -> dict:
    """
    Translate new-dataset field names into the params dict that calculate_metrics
    and _ac_freq_range expect (same keys as the old dataset's 'params' sub-dict).
    """
    task = entry.get("task", "")

    if task == "low_pass":
        return {
            "fc_hz":      entry.get("fc_hz"),       # ground-truth -3dB cutoff
            "f_pass_hz":  entry.get("f_pass_hz"),   # passband sample (where pb_spec was measured)
            "fs_hz":      entry.get("f_stop_hz"),   # stopband edge
            "atten_db":   entry.get("atten_spec_db"),
            "pb_loss_db": entry.get("pb_spec_db"),
        }

    if task == "high_pass":
        return {
            "fc_hz":      entry.get("fc_hz"),
            "f_pass_hz":  entry.get("f_pass_hz"),   # passband sample (where pb_spec was measured)
            "fs_hz":      entry.get("f_stop_hz"),
            "atten_db":   entry.get("atten_spec_db"),
            "pb_loss_db": entry.get("pb_spec_db"),
        }

    if task == "band_pass":
        return {
            "fc_low_hz":     entry.get("f_low_hz"),
            "fc_high_hz":    entry.get("f_high_hz"),
            "fs_low_hz":     entry.get("f_stop_low_hz"),
            "fs_high_hz":    entry.get("f_stop_high_hz"),
            "atten_low_db":  entry.get("atten_spec_db"),
            "atten_high_db": entry.get("atten_spec_db"),
            "pb_loss_db":    entry.get("pb_spec_db"),
        }

    if task == "notch":
        return {
            "f_notch_hz":    entry.get("f_notch_hz"),
            "fc_low_hz":     entry.get("f_low_hz"),
            "fc_high_hz":    entry.get("f_high_hz"),
            # single stopband edge — use as both sides (symmetric twin-T)
            "fs_low_hz":     entry.get("f_stop_hz"),
            "fs_high_hz":    entry.get("f_stop_hz"),
            "notch_depth_db": entry.get("atten_spec_db"),
            "pb_loss_db":    entry.get("pb_spec_db"),
        }

    return {}


# ---------------------------------------------------------------------------
# MODEL LOADING
# ---------------------------------------------------------------------------

def load_model():
    print(f"Loading tokenizer from {MODEL_ID} ...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    tokenizer.padding_side = "left"
    print("Loading model ...")
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        dtype=torch.bfloat16,
        device_map="cuda:0",
    )
    model = torch.compile(model, mode="reduce-overhead")
    print(f"Model loaded. Device: {next(model.parameters()).device}")
    return model, tokenizer


# ---------------------------------------------------------------------------
# LLM GENERATION
# ---------------------------------------------------------------------------

def generate_batch(model, tokenizer, prompts: list):
    messages_list = [
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": p}]
        for p in prompts
    ]
    texts = [
        tokenizer.apply_chat_template(m, tokenize=False, add_generation_prompt=True)
        for m in messages_list
    ]
    inputs = tokenizer(texts, return_tensors="pt", padding=True).to(model.device)
    input_len = inputs.input_ids.shape[1]

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
    return generate_batch(model, tokenizer, [prompt])[0]


# ---------------------------------------------------------------------------
# NETLIST EXTRACTION
# ---------------------------------------------------------------------------

def validate_netlist(netlist: str) -> list:
    warnings = []
    if not re.search(r'\bVOUT\b', netlist, re.IGNORECASE):
        warnings.append("VOUT node not found — v(vout) will fail in NGSpice")
    if not re.search(r'^V1\b', netlist, re.IGNORECASE | re.MULTILINE):
        warnings.append("V1 source not found — no AC stimulus defined")
    if re.search(r'^VIN\b', netlist, re.IGNORECASE | re.MULTILINE):
        warnings.append("Component named 'VIN' found — likely duplicate voltage source")
    if re.search(r'^GND\s+0\s*$', netlist, re.IGNORECASE | re.MULTILINE):
        warnings.append("Standalone 'GND 0' line found — not valid SPICE syntax")
    return warnings


def extract_netlist(response_text: str):
    m = re.search(r"```(?:spice|SPICE)?\s*\n(.*?)```", response_text, re.DOTALL | re.IGNORECASE)
    if m:
        netlist = m.group(1).strip()
        if ".END" in netlist.upper():
            return netlist

    lines = response_text.splitlines()
    start = None
    end = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if start is None:
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

def build_spice_file(netlist: str, params: dict, task_type: str, out_data_file: str) -> str:
    lines = ["* LLM-generated filter netlist — auto-simulated by pipeline_v2.py"]
    lines.append("")

    needs_opamp = bool(re.search(r'\bU1\b', netlist, re.IGNORECASE))
    has_subckt  = bool(re.search(r'\.SUBCKT\s+OPAMP_IDEAL', netlist, re.IGNORECASE))
    if needs_opamp and not has_subckt:
        lines.append(OPAMP_IDEAL_SUBCKT)

    netlist_body = re.sub(r'^\s*\.END\s*$', '', netlist, flags=re.IGNORECASE | re.MULTILINE).rstrip()
    netlist_body = re.sub(r'\bU(\d+)\b', r'X\1', netlist_body)

    def _remove_shorted_vsrcs(text):
        clean = []
        for line in text.splitlines():
            stripped = line.strip()
            m = re.match(r'^(V\S+)\s+(\S+)\s+(\S+)', stripped, re.IGNORECASE)
            if m and m.group(2).lower() == m.group(3).lower():
                continue
            clean.append(line)
        return '\n'.join(clean)

    netlist_body = _remove_shorted_vsrcs(netlist_body)
    netlist_body = re.sub(r'^\s*GND\s+0\s*$', '', netlist_body, flags=re.IGNORECASE | re.MULTILINE)

    lines.append(netlist_body)
    lines.append("")

    ac_start, ac_stop = _ac_freq_range(params, task_type)
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
    decade_margin = 2

    if task_type == "low_pass_filter":
        fc = params.get("fc_hz", 1000)
        fs = params.get("fs_hz", fc / 10)
        lo = min(fc, fs) / 10**decade_margin
        hi = max(fc, fs) * 10**decade_margin
        return max(lo, 0.01), hi

    if task_type == "high_pass_filter":
        fc = params.get("fc_hz", 1000)
        fs = params.get("fs_hz", fc * 10)
        lo = min(fc, fs) / 10**decade_margin
        hi = max(fc, fs) * 10**decade_margin
        return max(lo, 0.01), hi

    if task_type == "band_pass_filter":
        fc_low  = params.get("fc_low_hz", 100)
        fc_high = params.get("fc_high_hz", 1000)
        fs_low  = params.get("fs_low_hz", fc_low / 10)
        fs_high = params.get("fs_high_hz", fc_high * 10)
        lo = min(fc_low, fs_low or fc_low) / 10**decade_margin
        hi = max(fc_high, fs_high or fc_high) * 10**decade_margin
        return max(lo, 0.01), hi

    if task_type == "notch_filter":
        fc_low  = params.get("fc_low_hz",  params.get("f_notch_hz", 1000) / 10)
        fc_high = params.get("fc_high_hz", params.get("f_notch_hz", 1000) * 10)
        lo = fc_low / 10**decade_margin
        hi = fc_high * 10**decade_margin
        return max(lo, 0.01), hi

    return 1.0, 1e6


# ---------------------------------------------------------------------------
# NGSPICE SIMULATION
# ---------------------------------------------------------------------------

def run_ngspice(spice_content: str, tmp_dir: str):
    cir_path  = os.path.join(tmp_dir, "circuit.cir")
    data_path = os.path.join(tmp_dir, "ac_out.txt")

    with open(cir_path, "w") as f:
        f.write(spice_content)

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
            mag_db = 20.0 * math.log10(mag_linear) if mag_linear > 0 else -300.0
            results[freq] = mag_db
        except (ValueError, OverflowError, IndexError):
            continue

    return results


# ---------------------------------------------------------------------------
# METRICS CALCULATION
# ---------------------------------------------------------------------------

def calculate_metrics(ac_data: dict, params: dict, task_type: str) -> dict:
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
    target = ref_db + threshold_db
    if direction == "falling":
        for i in range(len(freqs) - 1):
            if mags[i] >= target >= mags[i + 1]:
                t = (mags[i] - target) / (mags[i] - mags[i + 1])
                return freqs[i] * (freqs[i + 1] / freqs[i]) ** t
    else:
        for i in range(len(freqs) - 1):
            if mags[i] <= target <= mags[i + 1]:
                t = (target - mags[i]) / (mags[i + 1] - mags[i])
                return freqs[i] * (freqs[i + 1] / freqs[i]) ** t
    return None


def _passband_ripple(freqs, mags, f_low, f_high):
    pb_mags = [m for f, m in zip(freqs, mags) if f_low <= f <= f_high]
    if len(pb_mags) < 2:
        return None
    return max(pb_mags) - min(pb_mags)


# NGSpice AC simulation uses discrete frequency points; interpolated values at
# exactly fc/fs can differ from the true continuous-frequency value by ~0.05 dB.
# This tolerance avoids penalising designs that analytically meet spec but fall
# just below the threshold due to simulation/interpolation rounding.
_METRIC_TOLERANCE_DB = 0.1


def _lpf_metrics(freqs, mags, params):
    fc_spec   = params.get("fc_hz")
    fs_spec   = params.get("fs_hz")
    atten_req = params.get("atten_db")
    ref_db = max(mags)
    m = {}

    fc_meas = _find_cutoff(freqs, mags, ref_db, threshold_db=-3.0, direction="falling")
    if fc_meas and fc_spec:
        m["cutoff_freq_hz_measured"] = fc_meas
        m["cutoff_freq_error_pct"]   = abs(fc_meas - fc_spec) / fc_spec * 100

    if fc_spec:
        ripple = _passband_ripple(freqs, mags, freqs[0], fc_spec)
        if ripple is not None:
            m["passband_ripple_db"] = round(ripple, 4)

    if fs_spec:
        atten_meas = ref_db - _interp_mag(freqs, mags, fs_spec)
        m["attenuation_at_fs"] = {
            "fs_hz": fs_spec, "achieved_db": round(atten_meas, 2),
            "required_db": atten_req, "met": (atten_req is None) or (atten_meas >= atten_req),
        }

    # Passband check: measure loss at the passband sample point (f_pass_hz), which is where
    # pb_spec_db was actually measured during dataset generation (inside the passband,
    # 0-1 decades below the -3dB cutoff). Fall back to fc_spec if f_pass_hz not present
    # (e.g. when called from the RAG pipeline, which already maps fc_hz = f_pass).
    pb_loss_req = params.get("pb_loss_db")
    f_pass_spec = params.get("f_pass_hz") or fc_spec
    if f_pass_spec:
        loss_at_fc = ref_db - _interp_mag(freqs, mags, f_pass_spec)
        m["loss_at_fc_db"] = round(loss_at_fc, 3)
        passband_ok = (pb_loss_req is None) or (loss_at_fc <= pb_loss_req + _METRIC_TOLERANCE_DB)
    else:
        passband_ok = True

    stopband_ok = (atten_req is None) or (
        fs_spec and (ref_db - _interp_mag(freqs, mags, fs_spec)) >= atten_req - _METRIC_TOLERANCE_DB
    )
    m["filter_response_match"] = bool(passband_ok and stopband_ok)
    return m


def _hpf_metrics(freqs, mags, params):
    fc_spec   = params.get("fc_hz")
    fs_spec   = params.get("fs_hz")
    atten_req = params.get("atten_db")
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
            "fs_hz": fs_spec, "achieved_db": round(atten_meas, 2),
            "required_db": atten_req, "met": (atten_req is None) or (atten_meas >= atten_req),
        }

    # Passband check: measure loss at f_pass_hz (where pb_spec was actually measured),
    # falling back to fc_spec if not present.
    pb_loss_req = params.get("pb_loss_db")
    f_pass_spec = params.get("f_pass_hz") or fc_spec
    if f_pass_spec:
        loss_at_fc = ref_db - _interp_mag(freqs, mags, f_pass_spec)
        m["loss_at_fc_db"] = round(loss_at_fc, 3)
        passband_ok = (pb_loss_req is None) or (loss_at_fc <= pb_loss_req + _METRIC_TOLERANCE_DB)
    else:
        passband_ok = True

    stopband_ok = (atten_req is None) or (
        fs_spec and (ref_db - _interp_mag(freqs, mags, fs_spec)) >= atten_req - _METRIC_TOLERANCE_DB
    )
    m["filter_response_match"] = bool(passband_ok and stopband_ok)
    return m


def _bpf_metrics(freqs, mags, params):
    fc_low  = params.get("fc_low_hz")
    fc_high = params.get("fc_high_hz")
    fs_low  = params.get("fs_low_hz")
    fs_high = params.get("fs_high_hz")
    al_req  = params.get("atten_low_db")
    ah_req  = params.get("atten_high_db")
    peak_db = max(mags)
    # Use absolute reference (VIN = AC 1 → 0 dB) for all gain/attenuation checks.
    # The spec was generated by simulate_attenuation() which returns absolute dB
    # relative to V(VIN). For rc_single BPF the passband peak can be 10-15 dB
    # below 0 dB due to HP/LP loading — using peak_db as reference would
    # systematically undercount attenuation and fail correct GT netlists.
    vin_db = 0.0
    m = {}

    fc_low_meas = _find_cutoff(freqs, mags, peak_db, threshold_db=-3.0, direction="rising")
    peak_idx = mags.index(peak_db)
    fc_high_meas = _find_cutoff(freqs[peak_idx:], mags[peak_idx:], peak_db, threshold_db=-3.0, direction="falling")

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
        al_meas = vin_db - _interp_mag(freqs, mags, fs_low)
        m["attenuation_at_fs_low"] = {
            "fs_hz": fs_low, "achieved_db": round(al_meas, 2),
            "required_db": al_req, "met": (al_req is None) or (al_meas >= al_req),
        }
    if fs_high:
        ah_meas = vin_db - _interp_mag(freqs, mags, fs_high)
        m["attenuation_at_fs_high"] = {
            "fs_hz": fs_high, "achieved_db": round(ah_meas, 2),
            "required_db": ah_req, "met": (ah_req is None) or (ah_meas >= ah_req),
        }

    # Record passband loss at fc_low and fc_high for diagnostic purposes.
    # NOTE: pb_loss_db was generated at a random INTERIOR passband frequency,
    # so checking it at the EDGE frequencies (fc_low, fc_high) systematically
    # overstates the loss by 1-3 dB. filter_response_match uses only the
    # stopband check, which is the authoritative criterion (generated at the
    # exact stopband frequency).
    if fc_low:
        loss_at_fc_low = vin_db - _interp_mag(freqs, mags, fc_low)
        m["loss_at_fc_low_db"] = round(loss_at_fc_low, 3)
    if fc_high:
        loss_at_fc_high = vin_db - _interp_mag(freqs, mags, fc_high)
        m["loss_at_fc_high_db"] = round(loss_at_fc_high, 3)
    stop_low_ok  = (al_req is None) or (fs_low  and (vin_db - _interp_mag(freqs, mags, fs_low))  >= al_req)
    stop_high_ok = (ah_req is None) or (fs_high and (vin_db - _interp_mag(freqs, mags, fs_high)) >= ah_req)
    m["filter_response_match"] = bool(stop_low_ok and stop_high_ok)
    return m


def _notch_metrics(freqs, mags, params):
    f_notch   = params.get("f_notch_hz")
    fc_low    = params.get("fc_low_hz")
    fc_high   = params.get("fc_high_hz")
    fs_low    = params.get("fs_low_hz")
    fs_high   = params.get("fs_high_hz")
    depth_req = params.get("notch_depth_db")
    al_req    = params.get("atten_low_db")
    ah_req    = params.get("atten_high_db")
    ref_db = max(mags)
    m = {}

    # Diagnostic: depth at the nominal notch centre (geometric mean of -3dB cutoffs).
    if f_notch:
        notch_depth_at_centre = ref_db - _interp_mag(freqs, mags, f_notch)
        m["notch_depth_db"] = round(notch_depth_at_centre, 2)

    # For filter_response_match, find the maximum depth (minimum magnitude) in the
    # notch region [fc_low, fc_high]. The spec's depth was measured at a single
    # random interior point (f_stop_hz). For sharp Twin-T notches the depth is
    # extremely frequency-sensitive, so checking at the geometric mean (f_notch_hz)
    # can miss the actual minimum by tens of dB due to tiny rounding in the prompt
    # string. Searching the sweep for the deepest point in the notch band is robust.
    if fc_low and fc_high:
        notch_band_mags = [mags[i] for i, f in enumerate(freqs) if fc_low <= f <= fc_high]
        if notch_band_mags:
            peak_notch_depth = ref_db - min(notch_band_mags)
            m["notch_depth_peak_db"] = round(peak_notch_depth, 2)
            if depth_req:
                m["notch_depth_met"] = peak_notch_depth >= depth_req
        r1 = _passband_ripple(freqs, mags, freqs[0], fc_low)
        r2 = _passband_ripple(freqs, mags, fc_high, freqs[-1])
        if r1 is not None:
            m["passband_ripple_low_db"]  = round(r1, 4)
        if r2 is not None:
            m["passband_ripple_high_db"] = round(r2, 4)

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

    # Use peak depth in notch band if available; otherwise fall back to centre.
    peak_depth = m.get("notch_depth_peak_db", m.get("notch_depth_db"))
    depth_ok = (depth_req is None) or (peak_depth is not None and peak_depth >= depth_req)
    m["filter_response_match"] = bool(depth_ok)
    return m


# ---------------------------------------------------------------------------
# PER-ENTRY PROCESSING
# ---------------------------------------------------------------------------

def process_entry(model, tokenizer, entry: dict, idx: int, source_file: str,
                  prefetched_response=None, prefetched_tokens=None,
                  prefetched_elapsed=None) -> dict:
    task_type = _get_task_type(entry)
    params    = _build_params(entry)

    result = {
        "index":               idx,
        "source_file":         source_file,
        "task_type":           task_type,
        "topology":            entry.get("topology", "unknown"),
        "stages":              entry.get("stages"),
        "params":              params,
        "ground_truth_netlist": entry.get("netlist"),
        "prompt":              entry.get("prompt", ""),
    }

    if prefetched_response is not None:
        response, tokens, elapsed = prefetched_response, prefetched_tokens or 0, prefetched_elapsed or 0.0
    else:
        try:
            response, tokens, elapsed = generate_netlist(model, tokenizer, entry["prompt"])
        except Exception as e:
            result.update({
                "llm_response": None, "generation_time_s": None, "tokens_generated": 0,
                "parse_success": False, "simulation_converged": False,
                "metrics": {}, "error": f"LLM generation error: {e}",
            })
            return result

    if response is None:
        result.update({
            "llm_response": None, "generation_time_s": None, "tokens_generated": 0,
            "parse_success": False, "simulation_converged": False,
            "metrics": {}, "error": "LLM generation failed (batch error)",
        })
        return result

    result["llm_response"]      = response
    result["generation_time_s"] = round(elapsed, 3)
    result["tokens_generated"]  = tokens

    netlist = extract_netlist(response)
    result["generated_netlist"] = netlist
    result["parse_success"]     = netlist is not None

    if not netlist:
        result.update({"simulation_converged": False, "metrics": {}})
        return result

    result["netlist_warnings"] = validate_netlist(netlist)

    with tempfile.TemporaryDirectory() as tmp_dir:
        data_file = os.path.join(tmp_dir, "ac_out.txt")
        spice_content = build_spice_file(netlist, params, task_type, data_file)
        result["spice_file_content"] = spice_content

        try:
            data_path, stderr, returncode = run_ngspice(spice_content, tmp_dir)
        except subprocess.TimeoutExpired:
            result.update({"simulation_converged": False, "metrics": {}, "error": "NGSpice timeout"})
            return result
        except FileNotFoundError:
            result.update({
                "simulation_converged": False, "metrics": {},
                "error": f"NGSpice not found at '{NGSPICE_PATH}'.",
            })
            return result

        result["ngspice_returncode"]   = returncode
        result["ngspice_stderr"]       = stderr[:2000]
        result["simulation_converged"] = (returncode == 0)

        if result["simulation_converged"]:
            ac_data = parse_ac_results(data_path)
            metrics = calculate_metrics(ac_data, params, task_type) if ac_data else {
                "warning": "No AC data parsed from NGSpice output"
            }
        else:
            metrics = {}

    result["metrics"] = metrics
    return result


# ---------------------------------------------------------------------------
# PROGRESS REPORTING
# ---------------------------------------------------------------------------

_pipeline_start_time = None


def write_progress(results_so_far, current_dataset, dataset_done, dataset_total,
                   all_datasets, datasets_done):
    now = time.time()
    elapsed_s  = now - _pipeline_start_time if _pipeline_start_time else 0
    total_done = len(results_so_far)
    parsed     = sum(1 for r in results_so_far if r.get("parse_success"))
    simulated  = sum(1 for r in results_so_far if r.get("simulation_converged"))
    functional = sum(1 for r in results_so_far if _is_functional(r))
    matched    = sum(1 for r in results_so_far if r.get("metrics", {}).get("filter_response_match"))

    parse_pct = parsed    / total_done * 100 if total_done else 0
    sim_pct   = simulated / total_done * 100 if total_done else 0
    func_pct  = functional / total_done * 100 if total_done else 0
    match_pct = matched   / functional * 100 if functional else 0

    eta_str = "calculating..."
    if total_done > 0:
        rate  = elapsed_s / total_done
        eta_s = rate * (dataset_total - dataset_done)
        eta_str = _fmt_duration(eta_s) + " (current dataset)"

    lines = [
        "=" * 56,
        f"  PIPELINE v2  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 56,
        f"  Elapsed:         {_fmt_duration(elapsed_s)}",
        f"  Datasets:        {datasets_done}/{len(all_datasets)}  ({', '.join(all_datasets)})",
        f"  Current dataset: {current_dataset}  [{dataset_done}/{dataset_total}]",
        "",
        f"  Total processed: {total_done}",
        f"  Parse success:   {parsed}/{total_done}  ({parse_pct:.1f}%)",
        f"  Sim converged:   {simulated}/{total_done}  ({sim_pct:.1f}%)",
        f"  Functional:      {functional}/{total_done}  ({func_pct:.1f}%)",
        f"  Response match:  {matched}/{functional}  ({match_pct:.1f}%)" if functional else "  Response match:  n/a",
        "",
        f"  ETA:             {eta_str}",
        "=" * 56,
    ]

    task_types = {}
    for r in results_so_far:
        tt = r.get("task_type", "unknown")
        if tt not in task_types:
            task_types[tt] = {"done": 0, "parsed": 0, "simulated": 0, "functional": 0}
        task_types[tt]["done"]      += 1
        task_types[tt]["parsed"]    += int(r.get("parse_success", False))
        task_types[tt]["simulated"] += int(r.get("simulation_converged", False))
        task_types[tt]["functional"] += int(_is_functional(r))

    if task_types:
        lines.append("  Per task type:")
        for tt, s in sorted(task_types.items()):
            pp = s["parsed"]    / s["done"] * 100
            sp = s["simulated"] / s["done"] * 100
            fp = s["functional"] / s["done"] * 100
            lines.append(f"    {tt:<22} done={s['done']:>4}  "
                         f"parse={pp:5.1f}%  sim={sp:5.1f}%  func={fp:5.1f}%")
        lines.append("=" * 56)

    with open(OUTPUT_DIR / "progress.txt", "w") as f:
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
# FUNCTIONAL CONVERGENCE CHECK
# ---------------------------------------------------------------------------

def _is_functional(result: dict) -> bool:
    if not result.get("simulation_converged"):
        return False
    m = result.get("metrics", {})
    if not m:
        return False
    if result.get("task_type") in ("low_pass_filter", "high_pass_filter"):
        return m.get("cutoff_freq_hz_measured") is not None
    if result.get("task_type") == "band_pass_filter":
        return (m.get("cutoff_freq_low_hz_measured") is not None or
                m.get("cutoff_freq_high_hz_measured") is not None)
    if result.get("task_type") == "notch_filter":
        return m.get("notch_depth_db") is not None
    return False


# ---------------------------------------------------------------------------
# DATASET PROCESSING
# ---------------------------------------------------------------------------

def process_dataset(model, tokenizer, dataset_name, json_path, limit=None,
                    batch_size=1, all_results_ref=None, all_datasets=None,
                    datasets_done=0):
    print(f"\n{'='*60}")
    print(f"Processing dataset: {dataset_name}  ({json_path.name})")
    print(f"{'='*60}")

    with open(json_path) as f:
        entries = json.load(f)

    if limit:
        entries = entries[:limit]
    total = len(entries)
    print(f"Entries: {total}  |  batch_size: {batch_size}")

    results = []
    checkpoint_path = OUTPUT_DIR / f"checkpoint_{dataset_name}.json"
    completed = 0

    for batch_start in range(0, total, batch_size):
        batch_entries = entries[batch_start : batch_start + batch_size]
        prompts = [e["prompt"] for e in batch_entries]

        print(f"  Generating batch [{batch_start+1}–{batch_start+len(batch_entries)}/{total}] ...",
              end=" ", flush=True)
        try:
            llm_results = generate_batch(model, tokenizer, prompts)
            print(f"done ({llm_results[0][2]*len(batch_entries):.1f}s)")
        except Exception as e:
            print(f"ERROR: {e}")
            llm_results = [(None, 0, 0.0)] * len(batch_entries)

        for local_i, (entry, (response, tokens, elapsed)) in enumerate(
            zip(batch_entries, llm_results)
        ):
            global_i = batch_start + local_i
            print(f"    [{global_i+1}/{total}] task={entry.get('task','?')} "
                  f"topo={entry.get('topology','?')} ...", end=" ", flush=True)

            result = process_entry(
                model, tokenizer, entry, global_i, json_path.name,
                prefetched_response=response,
                prefetched_tokens=tokens,
                prefetched_elapsed=elapsed,
            )

            status = []
            if result.get("parse_success"):       status.append("parsed")
            if result.get("simulation_converged"): status.append("simulated")
            if _is_functional(result):             status.append("functional")
            print(" | ".join(status) if status else "FAILED")

            results.append(result)
            if all_results_ref is not None:
                all_results_ref.append(result)
            completed += 1

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

    total      = len(all_results)
    parsed     = [r for r in all_results if r.get("parse_success")]
    simulated  = [r for r in all_results if r.get("simulation_converged")]
    functional = [r for r in all_results if _is_functional(r)]
    matched    = [r for r in all_results if r.get("metrics", {}).get("filter_response_match")]

    gen_times = [r["generation_time_s"] for r in all_results if r.get("generation_time_s")]
    tokens    = [r["tokens_generated"]  for r in parsed if r.get("tokens_generated")]

    task_types = sorted({r.get("task_type", "unknown") for r in all_results})
    per_task = {}
    for tt in task_types:
        subset   = [r for r in all_results if r.get("task_type") == tt]
        sim_sub  = [r for r in simulated   if r.get("task_type") == tt]
        func_sub = [r for r in functional  if r.get("task_type") == tt]
        par_sub  = [r for r in parsed      if r.get("task_type") == tt]
        mat_sub  = [r for r in matched     if r.get("task_type") == tt]

        cutoff_errs = [
            r["metrics"].get("cutoff_freq_error_pct") or
            r["metrics"].get("cutoff_freq_low_error_pct")
            for r in func_sub if r.get("metrics")
        ]
        cutoff_errs = [e for e in cutoff_errs if e is not None]

        per_task[tt] = {
            "total":                       len(subset),
            "parse_success_rate_pct":      round(len(par_sub)  / len(subset) * 100, 1) if subset else 0,
            "simulation_convergence_pct":  round(len(sim_sub)  / len(subset) * 100, 1) if subset else 0,
            "functional_convergence_pct":  round(len(func_sub) / len(subset) * 100, 1) if subset else 0,
            "filter_response_match_pct":   round(len(mat_sub)  / len(func_sub) * 100, 1) if func_sub else 0,
            "avg_cutoff_freq_error_pct":   round(sum(cutoff_errs) / len(cutoff_errs), 2) if cutoff_errs else None,
        }

    return {
        "generated_at":                     datetime.now().isoformat(),
        "total_entries":                    total,
        "parse_success_rate_pct":           round(len(parsed)     / total * 100, 1),
        "simulation_convergence_pct":       round(len(simulated)  / total * 100, 1),
        "functional_convergence_pct":       round(len(functional) / total * 100, 1),
        "filter_response_match_pct":        round(len(matched) / len(functional) * 100, 1) if functional else 0,
        "filter_response_match_pct_of_all": round(len(matched) / total * 100, 1),
        "avg_generation_time_s":            round(sum(gen_times) / len(gen_times), 3) if gen_times else None,
        "token_efficiency_per_netlist":     round(sum(tokens) / len(tokens), 1) if tokens else None,
        "per_task_type":                    per_task,
    }


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LLM Netlist Pipeline v2 — New_Datagen datasets")
    parser.add_argument("--limit",      type=int, default=None)
    parser.add_argument("--datasets",   type=str, default=None,
                        help="Comma-separated: lpf,hpf,bpf,notch (default: all)")
    parser.add_argument("--batch-size", type=int, default=1)
    args = parser.parse_args()

    if args.datasets:
        selected = [d.strip() for d in args.datasets.split(",")]
        dataset_map = {k: v for k, v in DATASET_FILES.items() if k in selected}
    else:
        dataset_map = DATASET_FILES

    if not dataset_map:
        print(f"No matching datasets. Available: {', '.join(DATASET_FILES)}")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    global _pipeline_start_time
    _pipeline_start_time = time.time()

    ds_names_preview = list(dataset_map.keys())
    with open(OUTPUT_DIR / "progress.txt", "w") as f:
        f.write(
            f"========================================================\n"
            f"  PIPELINE v2  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"========================================================\n"
            f"  Status:     LOADING MODEL ...\n"
            f"  Datasets:   {', '.join(ds_names_preview)}\n"
            f"  Batch size: {args.batch_size}\n"
            f"========================================================\n"
        )

    model, tokenizer = load_model()

    all_results = []
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

        out_path = OUTPUT_DIR / f"results_{ds_name}_{timestamp}.json"
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"  Saved: {out_path}")

        write_progress(
            results_so_far  = all_results,
            current_dataset = ds_name + " (done)",
            dataset_done    = len(results),
            dataset_total   = len(results),
            all_datasets    = ds_names,
            datasets_done   = ds_idx + 1,
        )

    summary = compute_summary(all_results)
    summary_path = OUTPUT_DIR / f"summary_{timestamp}.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved: {summary_path}")

    print("\n" + "="*60)
    print("PIPELINE v2 SUMMARY")
    print("="*60)
    print(f"  Total entries:          {summary.get('total_entries')}")
    print(f"  Parse success:          {summary.get('parse_success_rate_pct')}%")
    print(f"  Simulation convergence: {summary.get('simulation_convergence_pct')}%")
    print(f"  Functional convergence: {summary.get('functional_convergence_pct')}%")
    print(f"  Filter response match:  {summary.get('filter_response_match_pct')}%")
    print(f"  Avg generation time:    {summary.get('avg_generation_time_s')} s")
    print("\n  Per task type:")
    for tt, stats in summary.get("per_task_type", {}).items():
        print(f"    {tt}:")
        print(f"      parse={stats['parse_success_rate_pct']}%  "
              f"sim={stats['simulation_convergence_pct']}%  "
              f"func={stats['functional_convergence_pct']}%  "
              f"match={stats['filter_response_match_pct']}%")


if __name__ == "__main__":
    main()
