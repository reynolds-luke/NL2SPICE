import os
import json
import meilisearch
from dotenv import load_dotenv
from google import genai

load_dotenv()
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
client_ms = meilisearch.Client("http://localhost:7700")
index = client_ms.index("circuit_explainers")

with open("/Users/yashswijain/Library/Mobile Documents/com~apple~CloudDocs/SP26 Yale/CPSC/NL2SPICE/RAG stuff/RAG_files.json", "r") as f:
    dataset = json.load(f)[:5]

for entry in dataset:
    prompt = entry["prompt"]
    gt = f"{entry['filter_type']}_{entry['topology']}"
    
    inst = """You are a RAG routing agent. Your job is to read a circuit design prompt and extract the core circuit requirements as a string of space-separated keywords.
    Do not output any other text, punctuation, or explanation.
    You must extract exactly three types of keywords:
    1. The filter type: output "lpf" (low-pass), "hpf" (high-pass), "bpf" (band-pass), or "notch" (band-stop).
    2. The component type: output "rc" if the design is strictly passive/resistors and capacitors. Output "buffered rc" if it uses op-amps or active components.
    3. The complexity: output "single" if it asks for the simplest design or fewest components. Output "multi" if it asks for steep rolloff, high-order, or multi-stage.
    Example output format:
    lpf rc single"""
    
    resp = client_ai.models.generate_content(model='gemini-2.5-flash', contents=f"{inst}\n\nPrompt: {prompt}", config=genai.types.GenerateContentConfig(temperature=0.0))
    extracted = resp.text.strip().lower().replace('`', '')
    res = index.search(extracted, {'limit': 1})
    hit = res['hits'][0]['id'] if res['hits'] else None
    
    print(f"GT: {gt} | LLM Extracted: '{extracted}' | Meili Hit: {hit}")
