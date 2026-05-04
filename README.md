# NL2SPICE

**Natural Language to SPICE Netlist generation using a RAG-augmented agentic pipeline.**

The model is [Qwen2.5-Coder-14B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct) running locally. The pipeline accepts plain-English filter specifications, retrieves the relevant topology-specific design guide via a fine-tuned dual-encoder retriever, and iteratively refines the generated SPICE netlist using structured NGSpice simulation feedback.

---

## System Architecture

```
User prompt (filter type + specs)
          │
          ▼
  Fine-tuned dual-encoder RAG retriever
  (sentence-transformers, trained contrastively)
          │
          ▼
  One of 16 topology-specific design guides
  (LPF / HPF / BPF / Notch  ×
   rc_single / buffered_rc_single / rc_multi / buffered_rc_multi)
          │
          ▼
  Retrieved guide + prompt ──► Qwen2.5-Coder-14B-Instruct
                                        │
                                        ▼
                               SPICE netlist (text)
                                        │
                                        ▼
                             NGSpice AC simulation
                                        │
                                        ▼
                         Pass/Fail metric evaluation
                          (cutoff freq, attenuation,
                           bandwidth, notch depth ...)
                                        │
                           ┌────────────┴────────────┐
                         Pass                       Fail
                           │                          │
                        Done              Structured feedback message
                                         (measured vs required values,
                                          correct R·C product, example
                                          component values; verbatim
                                          pre-computed netlist injected
                                          for badly-wrong designs)
                                                      │
                                          Back to model (up to 5 iters)
```

---

## Key Results

Evaluated on n=252 prompts per filter type (63 prompts × 4 topologies), max 5 agentic iterations. Baseline is a one-shot prompt with no retrieval or feedback loop (n=1000).

| Pipeline | LPF | HPF | BPF | Notch | Overall |
|---|---|---|---|---|---|
| Baseline (one-shot, n=1000) | 2.9% | 0.0% | 30.9% | 18.3% | 17.5% |
| RAG Final (agentic, n=252) | 100% | 99% | 61% | 79% | **85%** |

Pre-generated figures for all result breakdowns are in `results/figures/`.

---

## Repository Structure

```
NL2SPICE/
├── pipeline_v2.py          # Core SPICE engine: netlist extraction, NGSpice runner, metric evaluation
├── rag_pipeline.py         # Agentic pipeline with static RAG lookup
├── rag_final_pipeline.py   # Agentic pipeline with fine-tuned dual-encoder retrieval
│
├── demo/
│   └── filter_chat.py      # Interactive terminal chat interface
│
├── results/
│   ├── plot_results.py     # Generate main report figures from evaluation output
│   ├── plot_appendix.py    # Generate appendix figures (convergence, failure modes, Bode)
│   └── figures/            # Pre-generated result figures (8 PNG files)
│       ├── fig1_overall_spec_met.png
│       ├── fig2_topology_heatmap.png
│       ├── fig3_iteration_distribution.png
│       ├── fig4_per_topology_bars.png
│       ├── fig5_baseline_comparison.png
│       ├── fig_a1_cumulative_convergence.png
│       ├── fig_a2_failure_modes.png
│       └── fig_a3_bode_before_after.png
│
├── New_Datagen/            # Dataset generation scripts and 1000-entry prompt datasets
│   ├── gen_*.py            # Per-filter generator scripts
│   ├── prompt_templates/   # Jinja-style prompt templates
│   ├── utils/              # Cutoff/attenuation measurement helpers
│   └── prompts/            # Generated datasets (lpf/hpf/bpf/notch_dataset.json)
│
├── Rag_final/              # Fine-tuned RAG retrieval system
│   ├── RAG.py              # Dual-encoder inference (run_custom function)
│   ├── best_query_model/   # Fine-tuned query encoder weights
│   ├── best_doc_model/     # Fine-tuned document encoder weights
│   └── RAG_docs/           # 16 topology-specific design guide documents
│
├── RAG stuff/              # RAG training code and filter system prompts
│   ├── build_rag.py        # Dual-encoder training script
│   └── filter_system_prompts/  # Design guides + model weights (used by rag_pipeline.py)
│
├── archive/                # Earlier pipeline versions and baseline outputs
│
├── requirements.txt
├── README.md
└── LukeChats.txt           # Full list of prompts Luke used for his portions of the pipeline
```

---

## Prerequisites

- Python 3.10+
- NGSpice installed and on `PATH` (or set `NGSPICE_PATH` at the top of `pipeline_v2.py`)
- CUDA GPU with ~30 GB VRAM for Qwen2.5-Coder-14B-Instruct (tested on A100 80 GB)
- HuggingFace access to [`Qwen/Qwen2.5-Coder-14B-Instruct`](https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct)

Install Python dependencies:

```bash
pip install -r requirements.txt
```

---

## How to Run

### 1. Batch evaluation on a dataset

```bash
# Run on all 4 filter types, 63 samples per topology (~252 total per type)
python rag_final_pipeline.py --datasets lpf,hpf,bpf,notch --sample-per-topology 63 --max-iters 5 --verbose

# Resume an interrupted run
python rag_final_pipeline.py --datasets bpf,notch --sample-per-topology 63 --resume

# With two GPUs (split datasets across processes)
CUDA_VISIBLE_DEVICES=0 python rag_final_pipeline.py --datasets lpf,hpf --sample-per-topology 63 &
CUDA_VISIBLE_DEVICES=1 python rag_final_pipeline.py --datasets bpf,notch --sample-per-topology 63 &
```

Results are written to `rag_final_output/results_<filter>_<timestamp>.json`.

### 2. Interactive demo

```bash
python demo/filter_chat.py
```

Guides the user through entering filter specs (type, cutoff frequency, stopband attenuation, etc.), runs the full agentic loop, displays the generated netlist and simulation outcome, and saves a frequency response plot to `demo/chat_output/`.

### 3. Generate result figures

```bash
python results/plot_results.py
```

Reads the JSON result files from `rag_final_output/` and writes all 5 report figures to `results/figures/`.

---

## Feedback Loop Details

The agentic loop runs up to `MAX_ITERS` iterations (default 5):

1. **Iteration 1** — Model generates a netlist from scratch using the RAG-retrieved design guide as the system prompt.
2. **If spec not met** — A structured feedback message is constructed containing:
   - Measured vs. required values for every failed metric (cutoff frequency, attenuation, bandwidth, notch depth)
   - The correct target R·C (or R·C·L) product derived analytically from the spec
   - Concrete example component values that satisfy the product
   - For badly-wrong designs (error > 2× tolerance): a fully pre-computed verbatim netlist is injected so the model copies correct values rather than recomputing
3. **Iterations 2–5** — Model revises the netlist guided by increasingly explicit feedback.

For notch filters, a pre-computed Twin-T template is always injected because the component value relationships are non-trivial and the model rarely derives them correctly from scratch.

---

## Topology Auto-Selection

`filter_chat.py` (and the agentic pipeline internals) choose between the four topologies automatically:

1. Compute the single-stage RC attenuation at the stopband frequency analytically.
2. If the required attenuation is met by a single stage → select `rc_single`.
3. Otherwise → select `buffered_rc_multi` (empirically the most robust topology across all filter types and spec ranges).
4. **Exception**: Notch filters always use `buffered_rc_single` — a buffer is required to prevent the load from disturbing the Twin-T null condition.

---

## RAG Retrieval System

`rag_final_pipeline.py` uses a fine-tuned dual-encoder model (`Rag_final/RAG.py`):

- **Query encoder** — encodes the user's filter spec prompt
- **Document encoder** — encodes each of the 16 design guide documents at startup
- Retrieval is by cosine similarity; the top-1 document is used as the system prompt

The encoders were fine-tuned contrastively (script: `RAG stuff/build_rag.py`) using positive pairs (filter spec → correct topology guide) and in-batch negatives. Weights are stored in `Rag_final/best_query_model/` and `Rag_final/best_doc_model/`.

`rag_pipeline.py` uses a static lookup (filter type + topology string → fixed system prompt file) without any neural retrieval.

---

## File-Level Notes

| File | Role |
|---|---|
| `pipeline_v2.py` | `load_model`, `extract_netlist`, `build_spice_file`, `run_ngspice`, `parse_ac_results`, `calculate_metrics` — the simulation substrate used by all pipelines |
| `rag_pipeline.py` | Static-RAG agentic loop; `_fmt_hz` utility re-exported by `filter_chat.py` |
| `rag_final_pipeline.py` | Fine-tuned dual-encoder RAG agentic loop; exports `agentic_loop`, `MAX_ITERS` |
| `demo/filter_chat.py` | Terminal UI; calls `agentic_loop` and plots the Bode response |
| `results/plot_results.py` | Reads `rag_final_output/*.json`, writes 5 figures to `results/figures/` |
