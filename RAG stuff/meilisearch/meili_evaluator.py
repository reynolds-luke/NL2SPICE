import os
import json
import meilisearch
import time
import random
from tqdm import tqdm
from dotenv import load_dotenv
from google import genai

# Load environment variables
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    print("WARNING: GEMINI_API_KEY not found in .env file.")

# Initialize Gemini Client
client_ai = genai.Client(api_key=API_KEY)

import meilisearch
from tqdm import tqdm

MEILI_URL = "http://localhost:7700"
DATASET_PATH = "/Users/yashswijain/Library/Mobile Documents/com~apple~CloudDocs/SP26 Yale/CPSC/NL2SPICE/RAG stuff/RAG_files.json"

def main():
    print(f"Connecting to MeiliSearch at {MEILI_URL}...")
    try:
        client = meilisearch.Client(MEILI_URL)
        index = client.index("circuit_explainers")
        # Check if we can access the index
        stats = index.get_stats()
        print(f"Index stats: {stats}")
    except Exception as e:
        print(f"Failed to connect to MeiliSearch or access index. Error: {e}")
        return

    print(f"Loading dataset from {DATASET_PATH}...")
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        dataset = json.load(f)
        
    print(f"Loaded {len(dataset)} prompts. Beginning baseline evaluation...")
    
    correct_retrievals = 0
    total_evaluated = 0
    
    # Limit to 10 for a quick API test
    MAX_EVAL = 10
    
    # Shuffle to get a random mix of circuit types instead of just the first ones in the file!
    random.shuffle(dataset)
    dataset_to_eval = dataset[:MAX_EVAL]
    
    def simulate_extraction_agent(prompt: str) -> str:
        """Uses Gemini to extract the exact topology category."""
        system_instruction = """
        You are a RAG routing agent. Your job is to read a circuit design prompt and extract the core circuit requirements as a string of space-separated keywords.
        Do not output any other text, punctuation, or explanation.
        
        You must extract exactly three types of keywords:
        1. The filter type: output "lpf" (low-pass), "hpf" (high-pass), "bpf" (band-pass), or "notch" (band-stop).
        2. The component type: output "rc" if the design is strictly passive/resistors and capacitors. Output "buffered rc" if it uses op-amps or active components.
        3. The complexity: output "single" if it asks for the simplest design or fewest components. Output "multi" if it asks for steep rolloff, high-order, or multi-stage.
        
        Example output format:
        lpf rc single
        """
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = client_ai.models.generate_content(
                    model='gemini-flash-latest',
                    contents=f"{system_instruction}\n\nPrompt: {prompt}",
                    config=genai.types.GenerateContentConfig(
                        temperature=0.0,
                    ),
                )
                # Clean up response to ensure it exactly matches one of our IDs
                extracted = response.text.strip().lower()
                # If the model added backticks, strip them
                extracted = extracted.replace('`', '')
                return extracted
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower() or "exhausted" in str(e).lower() or "503" in str(e) or "unavailable" in str(e).lower():
                    if attempt < max_retries - 1:
                        print(f"Rate limited. Waiting 10 seconds before retry {attempt + 1}...")
                        time.sleep(10)
                        continue
                print(f"API Failed: {e}")
                return prompt.lower()
        return prompt.lower()

    for entry in tqdm(dataset_to_eval):
        raw_prompt = entry["prompt"]
        filter_type = entry["filter_type"]
        topology = entry["topology"]
        
        # 1. Transform prompt using our simulated agent
        search_query = simulate_extraction_agent(raw_prompt)
        
        # Add sleep to prevent Google AI Studio 429 Rate Limit (15 Req / Min)
        time.sleep(4.1)
        
        expected_hit = f"{entry['filter_type'].lower()}_{entry['topology'].lower()}"
        
        # Query MeiliSearch using the extracted keywords
        search_results = index.search(search_query, {
            'limit': 1
        })
        
        hits = search_results.get("hits", [])
        
        if hits:
            top_hit_id = hits[0]["id"]
            if top_hit_id == expected_hit:
                correct_retrievals += 1
            else:
                print(f"Mismatch -> GT: {expected_hit} | Meili Hit: {top_hit_id} | Query: {search_query}")
        else:
            print(f"No Hits -> GT: {expected_hit} | Query: {search_query}")
                
        total_evaluated += 1

    accuracy = (correct_retrievals / total_evaluated) * 100
    print("\n" + "="*50)
    print("BASELINE EVALUATION RESULTS")
    print("="*50)
    print(f"Total Evaluated: {total_evaluated}")
    print(f"Correct Retrievals: {correct_retrievals}")
    print(f"Baseline Accuracy: {accuracy:.2f}%")
    print("="*50)

if __name__ == "__main__":
    main()
