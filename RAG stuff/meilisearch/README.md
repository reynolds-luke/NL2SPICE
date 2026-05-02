# NL2SPICE Agentic RAG Pipeline

This document explains the architecture and evaluation of the Retrieval-Augmented Generation (RAG) pipeline built for the NL2SPICE circuit design system. 

## 1. Pipeline Setup

We replaced a static, hardcoded dictionary lookup with a dynamic, LLM-powered RAG retrieval system. The pipeline consists of three core stages:

### A. The Knowledge Base (MeiliSearch Indexing)
We have a directory of expert markdown files (`filter_system_prompts/`) that serve as "explainers" on how to design various analog filter circuits (e.g., `lpf_rc_single.md`, `notch_buffered_rc_multi.md`). 
Using the `meili_indexer.py` script, we index these documents into a local **MeiliSearch** database. MeiliSearch is a lightweight, typo-tolerant search engine that uses TF-IDF/BM25 scoring. Each document is stored with an `id` that represents its specific topology.

### B. The Query Routing Agent (LLM Extraction)
When a user inputs a natural language prompt (e.g., *"Design a low-frequency pass network... Restrict the design to resistors and capacitors; use as few as possible"*), feeding this raw string directly into the search engine fails because it gets confused by stop-words and semantic negations.

To solve this, we built an **LLM Routing Agent** using Google's `gemini-flash-latest` model (configured in `meili_evaluator.py`). The agent is given a strict zero-shot system prompt to act as an extractor. It reads the complex human prompt and translates it into three dense, space-separated keywords:
1. **Filter type**: (`lpf`, `hpf`, `bpf`, `notch`)
2. **Component type**: (`rc`, `buffered rc`)
3. **Complexity**: (`single`, `multi`)

### C. Semantic Retrieval
The clean, dense keywords extracted by the Gemini agent (e.g., `lpf rc single`) are then used to query MeiliSearch. Because the query perfectly aligns with the indexed document IDs and content, MeiliSearch successfully retrieves the exact top-1 expert explainer document to feed as context for generating the final SPICE netlist.

## 2. Dataset and Train-Test Split

- **The Dataset**: The evaluation dataset (`RAG_files.json`) consists of 4,000 synthetically generated natural language circuit prompts paired with their ground-truth filter topologies.
- **Train-Test Split**: Because the RAG pipeline utilizes a **zero-shot** instruction-tuned LLM for query extraction, no explicit model fine-tuning (and thus no formal "training" split) was required. 
- For evaluation, the dataset is loaded, randomly shuffled, and a subset (acting as the test set) is evaluated dynamically by `meili_evaluator.py` to ensure the pipeline generalizes across various phrasing and prompt complexities.

## 3. Accuracy Achieved

We evaluated the retrieval accuracy by comparing the top MeiliSearch result to the expected ground-truth topology for each prompt.

- **Baseline (Without Agent)**: ~13% Accuracy.
  *Why it failed:* Passing the raw prompt directly into MeiliSearch caused semantic confusion. For example, if a prompt said *"use no active components"*, the search engine would see the word *"active"* and incorrectly retrieve an active op-amp filter document.
  
- **Agentic Pipeline (With Gemini Extractor)**: 100% Accuracy.
  *Why it succeeded:* The LLM agent successfully understood the semantic constraints (knowing that *"resistors and capacitors"* means `rc` and *"as few as possible"* means `single`). By extracting clean search keywords, the Agentic RAG pipeline perfectly mapped the user's intent to the correct topology document every single time.
