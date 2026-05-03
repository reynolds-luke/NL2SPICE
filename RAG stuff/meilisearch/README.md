# NL2SPICE MeiliSearch Retrieval Pipeline (Deprecated)

This document explains the architecture, experimentation, and final evaluation of the MeiliSearch-based document retrieval pipeline built for the NL2SPICE circuit design system. 

**Conclusion:** After extensive evaluation, we decided to drop the MeiliSearch approach.

## 1. Pipeline Setup & Experimentation

We experimented with replacing our static, hardcoded dictionary lookup with a dynamic MeiliSearch retrieval system. The experimental pipeline consisted of three core stages:

### A. The Knowledge Base (MeiliSearch Indexing)
We have a directory of expert markdown files (`filter_system_prompts/`) that serve as "explainers" on how to design various analog filter circuits (e.g., `lpf_rc_single.md`, `notch_buffered_rc_multi.md`). 
Using the `meili_indexer.py` script, we indexed these documents into a local **MeiliSearch** database. Each document was stored with an `id` that represents its specific topology.

### B. Query Extraction Strategies
When a user inputs a natural language prompt (e.g., *"Design a low-frequency pass network... Restrict the design to resistors and capacitors"*), feeding this raw string directly into the search engine fails because it gets confused by stop-words and semantic negations.

We tested two different extraction strategies to solve this:
1. **Hardcoded Parsing Logic**: We wrote a heuristic Python function utilizing regex and keyword matching to translate the human prompt into dense, space-separated keywords (e.g. mapping "no active" to "passive rc").
2. **LLM Routing Agent**: We built an extraction agent using Google's `gemini-flash` models. The agent was given a strict zero-shot system prompt to act as an extractor and translate the prompt into three core categorical keywords (Filter type, Component type, Complexity).

### C. Semantic Retrieval
The extracted keywords were then used to query MeiliSearch to retrieve the exact top-1 expert explainer document.

## 2. Dataset and Train-Test Split

- **The Dataset**: The evaluation dataset consists of 4,000 synthetically generated natural language circuit prompts paired with their ground-truth filter topologies.
- **Train-Test Split**: Because the experimental retrieval pipeline utilized a **zero-shot** instruction-tuned LLM and hardcoded heuristics for query extraction, no explicit model fine-tuning (and thus no formal "training" split) was required. 
- For evaluation, the dataset was loaded, randomly shuffled, and a subset was evaluated dynamically by `meili_evaluator.py` to ensure the pipeline generalized across various phrasing and prompt complexities.

## 3. Accuracy Achieved & Final Decision

We evaluated the retrieval accuracy by comparing the top MeiliSearch result to the expected ground-truth topology for each prompt.

- **Baseline (Plain MeiliSearch)**: ~10% Accuracy.
  Passing the raw prompt directly into MeiliSearch caused massive semantic confusion. For example, if a prompt said *"use no active components"*, the search engine would see the word *"active"* and incorrectly retrieve an active op-amp filter document.
  
- **Hardcoded Parsing Logic**: Significant Improvement (~51% Accuracy).
  By manually extracting key words from the prompt using regex heuristics and feeding those as query words to MeiliSearch, we saw a massive jump in accuracy. It correctly filtered out the noise that plagued the baseline.

- **LLM Agent Router**: ~20% Accuracy.
  We assumed that utilizing an LLM agent to semantically route the queries would push the accuracy to near 100%. However, due to API formatting issues, LLM hallucinations, and MeiliSearch's strict matching requirements, the accuracy catastrophically dropped back down to 20%.

**Decision**: Because the plain MeiliSearch baseline was unusable (~10%), the LLM Router introduced too much fragility/cost (~20%), and the Hardcoded Logic (~51%) still failed on too many edge cases, we decided to completely **drop the MeiliSearch approach**.
