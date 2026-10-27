"""One-time download of the all-MiniLM-L6-v2 embedding model (~90 MB) into the local Hugging Face cache.
After this, the app runs fully offline. CPU only."""
import sys

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    sys.exit("sentence-transformers is not installed. Run: pip install -r requirements.txt")

model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
vec = model.encode(["model download check"], normalize_embeddings=True)
print("Model ready. Embedding dimension:", vec.shape[1])
