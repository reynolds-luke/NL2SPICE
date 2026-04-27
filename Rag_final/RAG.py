# Package Versions:
# --------------------------------------------------
# sentence_transformers     5.4.1
# transformers              5.6.2
# huggingface_hub           1.12.0
# torch                     2.9.0+cpu
# numpy                     2.4.1
# tqdm                      4.67.1
# pathlib                   built-in (Python 3.4+)

from sentence_transformers import SentenceTransformer
import torch
import numpy as np
from pathlib import Path

# Global storage for loaded document explanations
explainer_files = {}

# ============================================================================
# INITIALIZATION: Load RAG documentation from markdown files
# ============================================================================

# Get the directory where the current script/notebook is located
current_dir = Path(__file__).parent if '__file__' in globals() else Path.cwd()

# Look for RAG_docs folder in the same location
rag_docs_path = current_dir / "RAG_docs"

# Load all markdown files from RAG_docs directory
for file_path in rag_docs_path.glob("*.md"):
    name = file_path.stem  # Gets filename without extension
    with open(file_path, encoding='utf-8') as f:
        text = f.read()
        explainer_files[name] = text

# Load pre-trained sentence transformer models
# These models should be saved locally in folders named "best_query_model" and "best_doc_model"
query_model = SentenceTransformer("best_query_model")
doc_model   = SentenceTransformer("best_doc_model")


def run_custom(prompt, verbose=False):
    """
    Detect the most relevant topology/architecture from a user prompt and return
    the corresponding RAG system prompt.
    
    This function uses dual-encoder semantic search to match the user's query against
    a collection of pre-defined topology explanations, then constructs a complete
    system prompt by combining the base prompt with the detected topology's specific
    instructions.
    
    Parameters
    ----------
    prompt : str
        The user's input query describing their needs or use case.
        Example: "I need to search across multiple PDF documents for relevant passages"
    
    verbose : bool, optional (default=False)
        If True, displays a progress bar during document encoding.
        Useful for debugging or when processing large document collections.
    
    Returns
    -------
    dict
        A dictionary containing:
        - "detected_topology" : str
            The name of the detected topology/architecture (e.g., "multi_document_rag",
            "conversational_rag", "hybrid_search")
        
        - "full_RAG_system_prompt" : str
            The complete system prompt combining the base instructions with the
            topology-specific guidance. This can be directly used to configure your
            RAG system.
    
    Notes
    -----
    - Requires the following files in RAG_docs/:
        * base_prompt.md: Core instructions applicable to all topologies
        * One or more topology-specific .md files (e.g., multi_document_rag.md)
    
    - Models are set to evaluation mode and use no_grad() for efficient inference
    
    - Embeddings are L2-normalized before computing cosine similarity scores
    
    Example
    -------
    >>> result = run_custom("I want to build a chatbot that remembers conversation history")
    >>> print(result["detected_topology"])
    conversational_rag
    >>> print(result["full_RAG_system_prompt"][:100])
    You are a RAG system designed to...
    
    >>> # Use verbose mode to see encoding progress
    >>> result = run_custom("Search academic papers for citations", verbose=True)
    Batches: 100%|██████████| 1/1 [00:00<00:00, 12.34it/s]
    """
    # Set models to evaluation mode (disables dropout, etc.)
    query_model.eval()
    doc_model.eval()

    # Prepare document collection for embedding
    doc_names = list(explainer_files.keys())
    doc_texts = [explainer_files[k] for k in doc_names]

    # Encode all documents and normalize embeddings
    with torch.no_grad():
        docs_emb = doc_model.encode(doc_texts, show_progress_bar=verbose, convert_to_numpy=True)
        # L2 normalization for cosine similarity
        docs_emb = docs_emb / np.linalg.norm(docs_emb, axis=1, keepdims=True)

    # Encode query and compute similarity scores
    with torch.no_grad():
        query_emb = query_model.encode(prompt, convert_to_numpy=True)
        # L2 normalization
        query_emb = query_emb / np.linalg.norm(query_emb)

        # Compute cosine similarity (dot product of normalized vectors)
        scores = docs_emb @ query_emb
        
        # Find the document with highest similarity
        top_idx = np.argmax(scores)
        predicted_doc = doc_names[top_idx]

    # Construct the complete system prompt
    return {
        "detected_topology": predicted_doc,
        "full_RAG_system_prompt": explainer_files["base_prompt"] + explainer_files[predicted_doc]
    }