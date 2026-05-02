import os
import json
import meilisearch

# Configuration
EXPLAINER_DIR = "/Users/yashswijain/Library/Mobile Documents/com~apple~CloudDocs/SP26 Yale/CPSC/NL2SPICE/RAG stuff/filter_system_prompts"
MEILI_URL = "http://localhost:7700"

def main():
    print(f"Connecting to MeiliSearch at {MEILI_URL}...")
    try:
        client = meilisearch.Client(MEILI_URL)
        # Check health
        health = client.health()
        print(f"MeiliSearch health: {health}")
    except Exception as e:
        print(f"Failed to connect to MeiliSearch. Is it running? Error: {e}")
        return

    # Create or get index
    index_name = "circuit_explainers"
    print(f"Ensuring index '{index_name}' exists...")
    client.create_index(index_name, {'primaryKey': 'id'})
    
    # Wait for task completion (create_index is async)
    # For a fresh index, it's very fast, but let's be safe.
    index = client.index(index_name)

    documents = []
    
    # Read all markdown files
    for filename in os.listdir(EXPLAINER_DIR):
        if not filename.endswith(".md"):
            continue
        if filename == "base_prompt.md":
            continue # Skip the base prompt, it's just formatting rules
            
        filepath = os.path.join(EXPLAINER_DIR, filename)
        
        # Parse filter_type and topology from filename (e.g. lpf_rc_single.md)
        name_no_ext = filename[:-3]
        parts = name_no_ext.split("_", 1)
        if len(parts) == 2:
            filter_type = parts[0]
            topology = parts[1]
        else:
            filter_type = "unknown"
            topology = name_no_ext
            
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            
        doc = {
            "id": name_no_ext,
            "filter_type": filter_type,
            "topology": topology,
            "content": content
        }
        documents.append(doc)
        
    print(f"Found {len(documents)} explainer documents. Indexing...")
    
    # Send documents to MeiliSearch
    task = index.add_documents(documents)
    
    # We could wait for the task, but for 18 documents it's near instant
    print(f"Documents submitted! Task UID: {task.task_uid}")
    print("Indexing complete.")

if __name__ == "__main__":
    main()
