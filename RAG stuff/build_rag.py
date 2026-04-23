"""
Build RAG_files.json: pairs each prompt from the checkpoint files with the
content of its corresponding filter_system_prompts explainer document.
"""
import json, os

CHECKPOINT_DIR = r"C:\Users\Luk27182\Desktop\NL2SPICE\New_Datagen\output"
EXPLAINER_DIR  = r"C:\Users\Luk27182\Desktop\NL2SPICE\filter_system_prompts"
OUTPUT_PATH    = r"C:\Users\Luk27182\Desktop\NL2SPICE\New_Datagen\output\RAG_files.json"

# Map checkpoint file name prefix → filter type string used in .md filenames
FILTER_MAP = {
    "checkpoint_lpf.json":   "lpf",
    "checkpoint_hpf.json":   "hpf",
    "checkpoint_bpf.json":   "bpf",
    "checkpoint_notch.json": "notch",
}

# Cache explainer content so each .md file is read only once
_explainer_cache = {}

def load_explainer(filter_type, topology):
    key = f"{filter_type}_{topology}"
    if key not in _explainer_cache:
        path = os.path.join(EXPLAINER_DIR, f"{key}.md")
        with open(path, encoding="utf-8") as f:
            _explainer_cache[key] = f.read()
    return _explainer_cache[key]

rows = []
for fname, filter_type in FILTER_MAP.items():
    path = os.path.join(CHECKPOINT_DIR, fname)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    topologies_seen = set()
    for entry in data:
        topology = entry["topology"]
        topologies_seen.add(topology)
        rows.append({
            "prompt":           entry["prompt"],
            "filter_type":      filter_type,
            "topology":         topology,
            "explainer_file":   f"{filter_type}_{topology}.md",
            "explainer_content": load_explainer(filter_type, topology),
        })

    print(f"{fname}: {len(data)} rows, topologies={sorted(topologies_seen)}")

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(rows, f, indent=2, ensure_ascii=False)

print(f"\nWrote {len(rows)} rows to {OUTPUT_PATH}")
