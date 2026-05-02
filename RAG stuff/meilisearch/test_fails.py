import json
import meilisearch

def simulate_extraction_agent(prompt: str) -> str:
    p = prompt.lower()
    keywords = []
    
    if "low-pass" in p or "low pass" in p: keywords.append("lpf")
    elif "high-pass" in p or "high pass" in p: keywords.append("hpf")
    elif "band-pass" in p or "band pass" in p: keywords.append("bpf")
    elif "band-stop" in p or "notch" in p: keywords.append("notch")
        
    if "no active" in p or "passive" in p:
        keywords.append("rc")
    elif "active" in p or "op-amp" in p or "buffer" in p:
        keywords.append("buffered rc")
        
    if "single" in p or "simple" in p:
        keywords.append("single")
    elif "multi" in p or "steep" in p or "high-order" in p:
        keywords.append("multi")
        
    return " ".join(keywords) if keywords else prompt

client = meilisearch.Client("http://localhost:7700")
index = client.index("circuit_explainers")

with open("/Users/yashswijain/Library/Mobile Documents/com~apple~CloudDocs/SP26 Yale/CPSC/NL2SPICE/RAG stuff/RAG_files.json", "r") as f:
    dataset = json.load(f)[:1000]

fails = 0
for entry in dataset:
    prompt = entry["prompt"]
    gt = f"{entry['filter_type']}_{entry['topology']}"
    
    query = simulate_extraction_agent(prompt)
    res = index.search(query, {'limit': 1})
    hit = res['hits'][0]['id'] if res['hits'] else None
    
    if hit != gt:
        print(f"GT: {gt} | Hit: {hit}")
        print(f"Prompt: {prompt}")
        print(f"Query: {query}")
        print("-" * 40)
        fails += 1
        if fails >= 5: break
