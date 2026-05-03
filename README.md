# NL2SPICE

Evaluation framework for **natural-language-to-SPICE netlist generation** using large language models. The pipeline feeds filter design prompts to [Qwen2.5-Coder-14B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct), runs the generated netlists through NGSpice AC simulation, and measures how closely the circuits meet their specifications.

Three evaluation modes are provided:

| Script | What it does |
|--------|-------------|
| `Python Scripts/pipeline.py` | **Baseline** — one-shot generation per prompt |
| `Python Scripts/agentic_pipeline.py` | **Agentic** — iterative feedback loop: LLM revises on simulation failure or spec mismatch |
| `Rag_final/RAG.py` + pipeline | **RAG** — dual-encoder semantic search selects a topology-specific system prompt before generation |

---

## Repository layout

```
NL2SPICE/
├── Python Scripts/
│   ├── pipeline.py            # Baseline evaluation pipeline
│   ├── agentic_pipeline.py    # Agentic (iterative revision) pipeline
│   └── analyse_results.py     # Post-run analysis and figure generation
│
├── prompts/                   # Evaluation datasets (JSON) + system prompt
│   ├── lpf_dataset.json       # ~2 000 low-pass filter specs
│   ├── hpf_dataset.json       # ~2 000 high-pass filter specs
│   ├── bpf_dataset.json       # ~2 700 band-pass filter specs
│   ├── notch_dataset.json     # ~2 700 notch filter specs
│   └── system_prompt.md       # Baseline one-shot system prompt
│
├── datagen_new/               # Dataset generation scripts (refactored)
│   ├── gen_lowpass.py
│   ├── gen_highpass.py
│   ├── gen_bandpass.py
│   ├── gen_notch.py
│   ├── prompt_templates/      # Per-filter-type prompt template libraries
│   └── utils/                 # find_cutoffs.py, measure_atten.py
│
├── New_Datagen/               # Alternate datagen iteration (used for final datasets)
│   ├── gen_*.py
│   ├── prompt_templates/
│   ├── utils/
│   └── prompts/               # Regenerated datasets (same format as prompts/)
│
├── Rag_final/                 # RAG-augmented generation
│   ├── RAG.py                 # Dual-encoder retrieval: query → best topology doc
│   ├── best_query_model/      # Fine-tuned sentence-transformer query encoder
│   ├── best_doc_model/        # Fine-tuned sentence-transformer document encoder
│   ├── RAG_docs/              # 16 Markdown topology descriptions (one per topology)
│   └── example_usage.ipynb   # Jupyter notebook walkthrough
│
├── RAG stuff/                 # RAG development / experimentation
│   ├── build_rag.py           # Training script for the dual-encoder models
│   ├── filter_system_prompts/ # Older RAG docs + model checkpoints
│   └── meilisearch/           # Alternative: BM25 lexical search via Meilisearch
│
├── agentic_rag_output/        # Saved outputs from agentic+RAG runs (Apr 2026)
└── archive/                   # Archived baseline outputs and old datagen scripts
```

---

## Prerequisites

### Python dependencies

```bash
pip install torch transformers accelerate sentencepiece
pip install sentence-transformers
pip install matplotlib numpy
```

Minimum tested versions are listed at the top of `Rag_final/RAG.py`.

### NGSpice

NGSpice must be installed and available as `ngspice` on your `PATH`.

```bash
# Debian/Ubuntu
sudo apt install ngspice

# RHEL/Rocky/AlmaLinux (HPC clusters)
module load ngspice       # if available as a module
# or build from source: https://ngspice.sourceforge.io/
```

If `ngspice` is not on `PATH`, set the `NGSPICE_PATH` constant at the top of `pipeline.py`:

```python
NGSPICE_PATH = "/usr/local/bin/ngspice"   # full path
```

### GPU / compute

The model (`Qwen2.5-Coder-14B-Instruct`, bfloat16) requires approximately **28 GB** of GPU VRAM total. It loads with `device_map="auto"`, so it will split across however many GPUs are available.

| GPU configuration | Recommended `--batch-size` | Throughput |
|-------------------|---------------------------|-----------|
| 1× A100 80 GB | 4–8 | ~2.5 s/entry |
| 2× A100 40 GB | 4 | ~3.0 s/entry |
| 4× A100 40 GB | 4–8 | ~1.4–1.8 s/entry |

Full run (~9 400 entries) at 4× A100, batch=8: **≈ 3.7 hours**.

---

## Dataset format

Each dataset file is a JSON array. Every entry has this shape:

```json
{
  "task_type": "low_pass_filter",
  "topology":  "rc_single",
  "params": {
    "fc_hz":     1500,
    "fs_hz":     6000,
    "atten_db":  20.0,
    "pb_loss_db": 3.0
  },
  "prompt":    "Design a passive RC low-pass filter with a cutoff frequency of 1500 Hz ...",
  "template_i": 3
}
```

`task_type` is one of: `low_pass_filter`, `high_pass_filter`, `band_pass_filter`, `notch_filter`.

---

## Setting up dataset paths

By default `pipeline.py` looks for datasets relative to its own directory:

```
Python Scripts/Project_Baseline/Test_Data/lpf_dataset.json
Python Scripts/Project_Baseline/Test_Data/hpf_dataset.json
...
```

The actual dataset files live in `prompts/` at the repo root. The simplest fix is to create a symlink or update the `DATA_DIR` constant near the top of `pipeline.py`:

```python
# Option A — symlink (run once from the repo root)
# mkdir -p "Python Scripts/Project_Baseline/Test_Data"
# ln -s ../../../../prompts/*.json "Python Scripts/Project_Baseline/Test_Data/"

# Option B — edit DATA_DIR directly in pipeline.py
_SCRIPT_DIR = Path(__file__).parent
DATA_DIR    = _SCRIPT_DIR.parent / "prompts"   # ← point at repo root prompts/
```

Results are written to `Python Scripts/Project_Baseline/output/` by default. That directory is created automatically on first run.

---

## Running the baseline pipeline

```bash
cd "Python Scripts"

# Full run — all 4 datasets, all entries
python pipeline.py --batch-size 4

# Quick smoke test — 20 entries from LPF only
python pipeline.py --datasets lpf --limit 20

# Two datasets, larger batch
python pipeline.py --datasets lpf,hpf --batch-size 8
```

### CLI arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--datasets` | all | Comma-separated list: `lpf`, `hpf`, `bpf`, `notch` |
| `--limit N` | all | Process only the first N entries per dataset |
| `--batch-size N` | 1 | Prompts per `model.generate()` call — set to number of GPUs |

### Monitoring a running job

The pipeline writes a live progress file after every batch:

```bash
watch -n 30 cat "Python Scripts/Project_Baseline/output/progress.txt"
```

The file is written immediately on startup (before the model even loads), so you can confirm the job is alive right away.

### Output files

After a run the output directory contains:

```
Project_Baseline/output/
├── progress.txt                          # Live status (overwritten each batch)
├── checkpoint_lpf.json                   # Incremental checkpoint — survives crashes
├── checkpoint_hpf.json
├── checkpoint_bpf.json
├── checkpoint_notch.json
├── results_lpf_<timestamp>.json          # Full per-entry results for LPF
├── results_hpf_<timestamp>.json
├── results_bpf_<timestamp>.json
├── results_notch_<timestamp>.json
└── summary_<timestamp>.json             # Aggregate statistics
```

Each entry in a results file records the LLM response, extracted netlist, NGSpice stderr, convergence flag, and all computed metrics.

---

## Running the agentic pipeline

The agentic pipeline wraps the same SPICE engine but adds an **iterative revision loop**: on parse failure, simulation failure, or spec mismatch, structured feedback is sent back to the LLM so it can revise the netlist — up to `--max-iters` times.

```bash
cd "Python Scripts"

# 100 LPF entries, up to 5 revision attempts each
python agentic_pipeline.py --datasets lpf --limit 100

# Verbose mode — prints the full LLM revision dialogue
python agentic_pipeline.py --datasets lpf --limit 10 --max-iters 3 --verbose
```

### CLI arguments

Inherits all arguments from `pipeline.py`, plus:

| Argument | Default | Description |
|----------|---------|-------------|
| `--max-iters N` | 5 | Maximum revision iterations per entry |
| `--verbose` | off | Print full LLM feedback/response each iteration |

### Chain-of-thought prompting

The agentic pipeline uses a different system prompt (`COT_SYSTEM_PROMPT`) that instructs the model to show its component-value calculations step-by-step before writing SPICE. This is the primary mechanism expected to improve cutoff-frequency accuracy over the baseline.

### Output files

```
Project_Baseline/output/
├── agentic_progress.txt
├── agentic_results_lpf_<timestamp>.json   # Per-entry, all iterations recorded
├── agentic_summary_<timestamp>.json
└── iterations_log_<ds>_<timestamp>.txt    # Human-readable revision transcript
```

---

## Running the RAG pipeline

`Rag_final/RAG.py` provides a drop-in system-prompt selector. Given the user's prompt, it uses a fine-tuned dual-encoder to retrieve the most relevant topology description from `Rag_final/RAG_docs/` and prepend it to the system prompt.

### Standalone usage

```python
import sys
sys.path.insert(0, "Rag_final")
from RAG import run_custom

system_prompt = run_custom(
    "Design a 2nd-order Sallen-Key low-pass filter at 1 kHz",
    verbose=True
)
print(system_prompt)
```

### Integration with the pipeline

To run RAG-augmented generation, update `pipeline.py` (or a copy of it) to call `run_custom(entry["prompt"])` and replace `SYSTEM_PROMPT` with its return value before generating. See `Rag_final/example_usage.ipynb` for a worked example.

### RAG model files

The models are stored in `Rag_final/best_query_model/` and `Rag_final/best_doc_model/`. `RAG.py` loads them with relative paths, so you must run it from inside `Rag_final/` or adjust `Path(__file__).parent` accordingly.

---

## Analysing results

After a completed run, generate figures and a text summary:

```bash
cd "Python Scripts"

# Analyse the most recent complete run (all 4 datasets present)
python analyse_results.py

# Analyse a specific run by timestamp
python analyse_results.py --run 20260414_020619
```

Outputs are written to `Project_Baseline/output/analysis/`:

| File | Description |
|------|-------------|
| `fig1_pipeline_quality.png` | Parse / convergence / spec-match rates per filter type |
| `fig2_cutoff_frequency.png` | Specified vs measured cutoff scatter + error histogram |
| `fig3_passband_ripple.png` | Passband ripple distribution (box + histogram) |
| `fig4_attenuation.png` | Achieved vs required stopband attenuation per filter type |
| `fig5_notch_depth.png` | Notch depth distribution and achieved-vs-required scatter |
| `fig6_topology_breakdown.png` | Spec match rate broken down by circuit topology |
| `fig7_generation_stats.png` | LLM generation time and token count distributions |
| `summary_report.txt` | Plain-text table of all key metrics |

`analyse_results.py` requires `matplotlib` and `numpy`. Figures are saved as 150 dpi PNGs (`.png` files are gitignored).

---

## Regenerating the datasets

If you want to create new or expanded datasets:

```bash
# From the repo root
python datagen_new/gen_lowpass.py
python datagen_new/gen_highpass.py
python datagen_new/gen_bandpass.py
python datagen_new/gen_notch.py
```

Each script writes a `*_dataset.json` to its output directory. Prompt templates are in `datagen_new/prompt_templates/`. Utility functions for computing cutoff frequencies and attenuation are in `datagen_new/utils/`.

---

## Evaluation metrics

For each successfully simulated entry the pipeline measures:

| Metric | Filter types | Description |
|--------|-------------|-------------|
| `cutoff_freq_error_pct` | LPF, HPF | `|fc_measured − fc_spec| / fc_spec × 100` |
| `cutoff_freq_low/high_error_pct` | BPF | Same, for lower and upper −3 dB edges |
| `passband_ripple_db` | All | Peak-to-trough variation within the passband |
| `attenuation_at_fs` | LPF, HPF, BPF, Notch | Achieved stopband attenuation vs required |
| `notch_depth_db` | Notch | Attenuation at the notch centre frequency |
| `filter_response_match` | All | Boolean: cutoff within 20% of spec **and** stopband requirement met |

---

## Known SPICE pitfalls

These are bugs encountered during development and handled automatically by the pipeline. Understanding them helps when extending or debugging the code.

1. **SPICE title line** — The first line of every `.cir` file is silently treated as the circuit title and ignored by the simulator. `build_spice_file()` always prepends a `*` comment line so nothing gets discarded.

2. **`IN+` / `IN−` in `.SUBCKT` headers** — NGSpice misparses `+` and `-` in subcircuit pin names. The ideal op-amp subcircuit uses `INP` / `INN` instead.

3. **`U1` → `X1` substitution** — SPICE subcircuit instances must start with `X`. The dataset uses `U1` for the op-amp; `build_spice_file()` rewrites `U` prefixes to `X` before simulation.

4. **Shorted voltage sources** — The LLM sometimes writes `VCC 0 0` or `VEE VEE 0` as power-supply placeholders. NGSpice aborts on zero-voltage short circuits. `_remove_shorted_vsrcs()` strips them.

5. **`GND 0` declarations** — Writing `GND 0` as a standalone ground reference is not valid SPICE. It is stripped by regex in `build_spice_file()`.

6. **Floating VCC/VEE pins** — Removing power supplies (point 4) would leave the op-amp supply pins floating. The `OPAMP_IDEAL` subcircuit includes 1 GΩ bleed resistors on `VCC` and `VEE` to ground. These have negligible effect on any filter response.

7. **Duplicate `VIN` voltage source** — If the LLM names a component `VIN`, SPICE treats it as a voltage source in parallel with `V1`, causing a short. `validate_netlist()` flags this as a warning.

---

## Baseline results (80-entry test run)

Results from a quick 20-entry-per-dataset validation run with the baseline pipeline:

| Filter | Parse rate | Sim convergence | Spec match |
|--------|-----------|-----------------|-----------|
| LPF    | 100%      | 95%             | ~7%       |
| HPF    | 100%      | 100%            | ~7%       |
| BPF    | 95%       | 90%             | ~7%       |
| Notch  | 100%      | 90%             | ~7%       |

The low spec-match rate is the primary finding, not a bug: the model reliably produces structurally valid netlists but uses generic component values (e.g. R = 10 kΩ, C = 10 nF) rather than computing values for the target cutoff frequency. The agentic and RAG pipelines are designed to address this.

---

## HPC / cluster tips

- Use `sbatch` or `qsub` with a 24-hour wall-time limit — a full 4-dataset run at 4× A100 takes ≈ 4–5 hours.
- The pipeline writes incremental checkpoints (`checkpoint_<ds>.json`) after every 10 entries, so a crashed job can be resumed by loading the checkpoint and skipping already-processed indices.
- Monitor from the login node without SSH-ing into the compute node: `watch -n 30 cat output/progress.txt`.
- `HuggingFace` model weights (~29 GB) are cached in `~/.cache/huggingface/` by default. On shared NFS clusters consider setting `HF_HOME` to a project-local directory to avoid re-downloading.

```bash
export HF_HOME=/path/to/project/.hf_cache
```
