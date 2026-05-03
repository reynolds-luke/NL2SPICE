"""
rag_final_pipeline.py — Agentic netlist generation with fine-tuned RAG retrieval

Replaces the hard-coded topology lookup in rag_pipeline.py with the fine-tuned
dual-encoder model from Rag_final/. The model semantically retrieves the most
relevant topology-specific design guide for each prompt, then the agentic loop
generates and iteratively refines the SPICE netlist using simulation feedback.

Key differences from rag_pipeline.py:
  - Retrieval: Rag_final/RAG.py run_custom(prompt) instead of task+topology lookup
  - Docs: Rag_final/RAG_docs/ (the corpus the embedding model was trained on)
  - Everything else (feedback, simulation, metrics) is identical

Usage:
    python rag_final_pipeline.py --datasets lpf --sample-per-topology 6
    python rag_final_pipeline.py --datasets lpf,hpf,bpf,notch --sample-per-topology 6
    python rag_final_pipeline.py --datasets lpf --limit 5 --max-iters 3 --verbose
"""

import argparse
import json
import math
import os
import re
import sys
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
# Import the fine-tuned RAG retriever
# ---------------------------------------------------------------------------
_SCRIPT_DIR   = Path(__file__).parent
_RAG_FINAL_DIR = _SCRIPT_DIR / "Rag_final"
sys.path.insert(0, str(_RAG_FINAL_DIR))
from RAG import run_custom  # noqa: E402 — intentional after sys.path insert

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR   = _SCRIPT_DIR / "New_Datagen" / "prompts"
OUTPUT_DIR = _SCRIPT_DIR / "rag_final_output"

DATASET_FILES = {
    "lpf":   DATA_DIR / "lpf_dataset.json",
    "hpf":   DATA_DIR / "hpf_dataset.json",
    "bpf":   DATA_DIR / "bpf_dataset.json",
    "notch": DATA_DIR / "notch_dataset.json",
}

MAX_ITERS      = 3
MAX_NEW_TOKENS = 1024

# CoT header prepended to every system prompt (same as rag_pipeline.py)
_COT_HEADER = """\
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
"""


def build_system_prompt(prompt: str) -> tuple[str, str]:
    """
    Use the fine-tuned dual-encoder to retrieve the best-matching design guide,
    then prepend the CoT header.

    Returns (system_prompt, detected_doc_name).
    """
    result = run_custom(prompt)
    detected = result["detected_topology"]   # e.g. "lpf_rc_single"
    rag_body = result["full_RAG_system_prompt"]  # base_prompt + topology doc
    return _COT_HEADER + rag_body, detected


# ---------------------------------------------------------------------------
# Reuse helpers from rag_pipeline (REQUIREMENTS parser, feedback, generation)
# These are imported by re-using the functions directly.
# ---------------------------------------------------------------------------
from rag_pipeline import (  # noqa: E402
    parse_requirements,
    build_feedback,
    generate_with_history,
    _fmt_hz,
)


# ---------------------------------------------------------------------------
# Agentic loop — one entry
# ---------------------------------------------------------------------------

def agentic_loop(model, tokenizer, entry: dict, idx: int,
                 max_iters: int = MAX_ITERS, verbose: bool = False) -> dict:

    topology = entry.get("topology", "unknown")
    prompt   = entry.get("prompt", "")

    task_type, params = parse_requirements(prompt)
    if not task_type:
        raise ValueError(f"Entry {idx}: could not parse REQUIREMENTS block from prompt")

    system_prompt, rag_doc_used = build_system_prompt(prompt)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": prompt},
    ]

    result = {
        "index":                idx,
        "task_type":            task_type,
        "topology":             topology,
        "params":               params,
        "prompt":               prompt,
        "ground_truth_netlist": entry.get("netlist", ""),
        "rag_doc_retrieved":    rag_doc_used + ".md",
        "rag_doc_expected":     f"{entry.get('task','unknown')}_{topology}.md".replace("low_pass","lpf").replace("high_pass","hpf").replace("band_pass","bpf"),
        "retrieval_correct":    None,   # filled below
        "iterations":           [],
    }
    result["retrieval_correct"] = (
        result["rag_doc_retrieved"].rstrip(".md") == result["rag_doc_expected"].rstrip(".md")
    )

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
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                data_file = os.path.join(tmp, "ac_data.txt")
                spice     = build_spice_file(netlist, params, task_type, data_file)
                stdout, stderr, rc = run_ngspice(spice, tmp)
                sim_ok = (rc == 0)
                if sim_ok:
                    ac_data = parse_ac_results(data_file)
                    metrics = calculate_metrics(ac_data, params, task_type) if ac_data else {}

        iter_rec.update({
            "simulation_converged": sim_ok,
            "metrics":              metrics,
            "spec_met":             bool(metrics.get("filter_response_match")),
        })
        result["iterations"].append(iter_rec)

        if verbose:
            spec    = "✓" if iter_rec["spec_met"] else "✗"
            ret_str = "✓" if result["retrieval_correct"] else f"✗({rag_doc_used})"
            pb_str  = ""
            sb_str  = ""
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
                  f"sim={'✓' if sim_ok else '✗'}  spec={spec}{pb_str}{sb_str}  "
                  f"retrieval={ret_str}  {elapsed:.1f}s")

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
        "parse_success":        final.get("parse_success", False),
        "simulation_converged": final.get("simulation_converged", False),
        "metrics":              final.get("metrics", {}),
        "generated_netlist":    final.get("generated_netlist", ""),
        "generation_time_s":    round(total_time, 2),
        "tokens_generated":     total_tokens,
        "final_spec_met":       final.get("spec_met", False),
        "iterations_used":      len(result["iterations"]),
    })
    return result


# ---------------------------------------------------------------------------
# Dataset processing
# ---------------------------------------------------------------------------

def _sample_per_topology(entries: list, n: int) -> list:
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
                    verbose=False, resume=False) -> list:
    path = DATASET_FILES[ds_name]
    with open(path) as f:
        entries = json.load(f)
    if sample_per_topology:
        entries = _sample_per_topology(entries, sample_per_topology)
    elif limit:
        entries = entries[:limit]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ckpt = OUTPUT_DIR / f"ckpt_{ds_name}.json"
    log  = OUTPUT_DIR / f"iter_log_{ds_name}.txt"

    results = []
    skip = 0
    if resume and ckpt.exists():
        with open(ckpt) as f:
            results = json.load(f)
        skip = len(results)
        print(f"  [resume] {ds_name}: skipping {skip} already-done entries, "
              f"{len(entries) - skip} remaining")
        log_mode = "a"
    else:
        log_mode = "w"

    with open(log, log_mode) as logf:
        logf.write(f"RAG FINAL PIPELINE — {ds_name.upper()} — {datetime.now().isoformat()}"
                   f"{'  (RESUMED)' if skip else ''}\n"
                   f"max_iters={max_iters}  entries={len(entries)}  skip={skip}\n{'='*70}\n\n")

    gpu_tag = f"[GPU{os.environ.get('CUDA_VISIBLE_DEVICES', '?')}]"

    for idx, entry in enumerate(entries):
        if idx < skip:
            continue
        task     = entry.get("task", "")
        topology = entry.get("topology", "unknown")

        result = agentic_loop(model, tokenizer, entry, idx,
                              max_iters=max_iters, verbose=verbose)
        results.append(result)

        spec = "✓" if result["final_spec_met"] else "✗"
        ret  = "✓" if result.get("retrieval_correct") else f"✗(got {result.get('rag_doc_retrieved','')})"
        print(f"{gpu_tag} [{idx+1}/{len(entries)}] {task}/{topology}  "
              f"iters={result['iterations_used']}  spec={spec}  retrieval={ret}", flush=True)

        with open(log, "a") as logf:
            logf.write(f"Entry {idx}  {task}/{topology}  spec={spec}  retrieval={ret}\n")
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

    total = len(all_results)
    functional = [r for r in all_results if r.get("simulation_converged")]

    summary = {
        "generated_at":         datetime.now().isoformat(),
        "timestamp":            timestamp,
        "total_entries":        total,
        "max_iters_configured": MAX_ITERS,
        "final_parse_pct":      sum(r["parse_success"] for r in all_results) / total * 100,
        "final_converged_pct":  len(functional) / total * 100,
        "final_spec_met_pct":   sum(r["final_spec_met"] for r in all_results) / total * 100,
        "retrieval_accuracy_pct": sum(r.get("retrieval_correct", False) for r in all_results) / total * 100,
        "avg_iterations_used":  sum(r["iterations_used"] for r in all_results) / total,
        "per_task_type":        {},
    }

    for task, rs in by_task.items():
        n = len(rs)
        summary["per_task_type"][task] = {
            "total":               n,
            "final_spec_met_pct":  sum(r["final_spec_met"] for r in rs) / n * 100,
            "final_converged_pct": sum(r["simulation_converged"] for r in rs) / n * 100,
            "retrieval_accuracy_pct": sum(r.get("retrieval_correct", False) for r in rs) / n * 100,
            "avg_iterations_used": sum(r["iterations_used"] for r in rs) / n,
        }

    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets",  default="lpf,hpf,bpf,notch")
    parser.add_argument("--limit",               type=int, default=None)
    parser.add_argument("--sample-per-topology", type=int, default=None)
    parser.add_argument("--max-iters", type=int, default=MAX_ITERS)
    parser.add_argument("--verbose",   action="store_true")
    parser.add_argument("--resume",    action="store_true",
                        help="Continue from existing ckpt_<dataset>.json checkpoints")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    datasets  = [d.strip() for d in args.datasets.split(",")]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"RAG Final Pipeline — {timestamp}")
    print(f"  Datasets   : {datasets}")
    print(f"  RAG model  : {_RAG_FINAL_DIR}")
    if args.sample_per_topology:
        print(f"  Sample     : {args.sample_per_topology} per topology")
    else:
        print(f"  Limit      : {args.limit or 'all'}")
    print(f"  Max iters  : {args.max_iters}")

    print("\nLoading LLM...")
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
                                  verbose=args.verbose,
                                  resume=args.resume)
        out_path = OUTPUT_DIR / f"results_{ds}_{timestamp}.json"
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"  Saved: {out_path.name}")
        all_results.extend(results)

    if all_results:
        summary  = compute_summary(all_results, timestamp)
        sum_path = OUTPUT_DIR / f"summary_{timestamp}.json"
        with open(sum_path, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\nSummary saved: {sum_path.name}")
        print(f"  spec_met:   {summary['final_spec_met_pct']:.1f}%")
        print(f"  retrieval:  {summary['retrieval_accuracy_pct']:.1f}%")
        print(f"  avg iters:  {summary['avg_iterations_used']:.2f}")


if __name__ == "__main__":
    main()
