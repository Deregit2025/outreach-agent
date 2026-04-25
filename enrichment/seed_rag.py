"""
seed_rag.py — RAG retrieval over Tenacious seed documents.

Indexes all documents in data/tenacious_sales_data/seed/ using
sentence-transformers embeddings and ChromaDB vector store.

Documents indexed:
  - discovery_transcripts/*.md  (5 real call transcripts, one per segment)
  - case_studies.md             (3 redacted client outcomes)
  - style_guide.md              (tone markers, prohibited phrases)
  - pricing_sheet.md            (ACV ranges, engagement types)
  - email_sequences/*.md        (cold, warm, re-engagement templates)
  - sales_deck_notes.md         (pitch narrative)
  - baseline_numbers.md         (citable numbers)
  - icp_definition.md           (segment rules)

Usage:
  from enrichment.seed_rag import retrieve_relevant_passages, init_rag

  # Called once per process (lazy init also works)
  init_rag()

  # Per prospect
  passages = retrieve_relevant_passages(
      query="How do we handle a Series B startup with 5 open ML roles?",
      top_k=3,
      filter_source_type="discovery_transcripts",  # optional
  )
"""

from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = PROJECT_ROOT / "data" / "tenacious_sales_data" / "seed"
CHROMA_DIR = PROJECT_ROOT / "data" / "processed" / "chroma_seed_rag"

CHUNK_SIZE = 300      # tokens ≈ characters / 4; target ~300 words
CHUNK_OVERLAP = 60    # overlap between consecutive chunks

COLLECTION_NAME = "tenacious_seed"


class RAGPassage(TypedDict):
    passage: str
    source: str           # file name relative to SEED_DIR
    source_type: str      # "transcript" | "case_study" | "email_template" | "reference"
    relevance_score: float


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping word-level chunks."""
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += chunk_size - overlap
    return chunks


def _classify_source_type(path: Path) -> str:
    name = path.name.lower()
    parts = [p.lower() for p in path.parts]
    if "discovery_transcripts" in parts:
        return "transcript"
    if "case_studies" in name:
        return "case_study"
    if "email_sequences" in parts or "email" in name:
        return "email_template"
    return "reference"


def _collect_seed_documents() -> list[tuple[Path, str]]:
    """Collect all seed markdown files with their text content."""
    docs: list[tuple[Path, str]] = []
    if not SEED_DIR.exists():
        logger.warning("Seed directory not found: %s", SEED_DIR)
        return docs
    for md_path in sorted(SEED_DIR.rglob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8").strip()
            if text:
                docs.append((md_path, text))
        except Exception as exc:
            logger.warning("Could not read %s: %s", md_path, exc)
    return docs


def _corpus_hash(docs: list[tuple[Path, str]]) -> str:
    """Hash of all document contents — used to detect when re-index is needed."""
    h = hashlib.md5()
    for path, text in docs:
        h.update(str(path).encode())
        h.update(text[:200].encode())
    return h.hexdigest()[:12]


@lru_cache(maxsize=1)
def _get_collection():
    """Initialize or load ChromaDB collection. Cached per process."""
    try:
        import chromadb  # type: ignore
        from sentence_transformers import SentenceTransformer  # type: ignore
        from chromadb.utils.embedding_functions import EmbeddingFunction  # type: ignore
    except ImportError as e:
        raise ImportError(
            f"RAG requires chromadb and sentence-transformers: {e}"
        ) from e

    # Use all-MiniLM-L6-v2 — fast (0.5s/batch), 384-dim, strong semantic search
    model = SentenceTransformer("all-MiniLM-L6-v2")

    class _LocalEmbedder(EmbeddingFunction):
        def __call__(self, input: list[str]) -> list[list[float]]:
            return model.encode(input, normalize_embeddings=True).tolist()

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=_LocalEmbedder(),
        metadata={"hnsw:space": "cosine"},
    )
    return collection, model


def init_rag(force_reindex: bool = False) -> int:
    """
    Index all seed documents into ChromaDB.

    Skips re-indexing if the corpus hash stored in the collection metadata
    matches the current documents (incremental refresh).

    Returns the number of chunks indexed.
    """
    docs = _collect_seed_documents()
    if not docs:
        logger.warning("No seed documents found — RAG index is empty")
        return 0

    corpus_hash = _corpus_hash(docs)

    try:
        collection, _ = _get_collection()
    except ImportError as exc:
        logger.warning("RAG unavailable: %s", exc)
        return 0

    # Check if already indexed with the same hash
    existing_meta = collection.metadata or {}
    if not force_reindex and existing_meta.get("corpus_hash") == corpus_hash:
        count = collection.count()
        logger.info("RAG index up-to-date (%d chunks, hash=%s)", count, corpus_hash)
        return count

    # Build chunks and upsert
    ids: list[str] = []
    texts: list[str] = []
    metadatas: list[dict] = []

    for path, text in docs:
        rel_path = str(path.relative_to(SEED_DIR))
        source_type = _classify_source_type(path)
        for i, chunk in enumerate(_chunk_text(text)):
            chunk_id = f"{rel_path}::{i}"
            ids.append(chunk_id)
            texts.append(chunk)
            metadatas.append({
                "source": rel_path,
                "source_type": source_type,
                "chunk_index": i,
            })

    if not texts:
        return 0

    # Upsert in batches of 100 to avoid memory pressure
    BATCH = 100
    for start in range(0, len(texts), BATCH):
        collection.upsert(
            ids=ids[start : start + BATCH],
            documents=texts[start : start + BATCH],
            metadatas=metadatas[start : start + BATCH],
        )

    # Store corpus hash so future runs skip re-indexing
    try:
        import chromadb  # type: ignore
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine", "corpus_hash": corpus_hash},
        )
    except Exception:
        pass

    logger.info("RAG index built: %d chunks from %d documents", len(texts), len(docs))
    return len(texts)


def retrieve_relevant_passages(
    query: str,
    top_k: int = 3,
    filter_source_type: str | None = None,
) -> list[RAGPassage]:
    """
    Retrieve the top-k most relevant passages for a query.

    Args:
        query:             Natural language query (prospect context or question)
        top_k:             Number of passages to return
        filter_source_type: Optional filter: "transcript" | "case_study" |
                            "email_template" | "reference"

    Returns:
        List of RAGPassage dicts sorted by relevance (highest first)
    """
    if not query.strip():
        return []

    try:
        collection, _ = _get_collection()
    except (ImportError, Exception) as exc:
        logger.warning("RAG retrieval unavailable: %s", exc)
        return []

    # Lazy init if collection is empty
    if collection.count() == 0:
        init_rag()

    if collection.count() == 0:
        return []

    where_filter = {"source_type": filter_source_type} if filter_source_type else None

    try:
        results = collection.query(
            query_texts=[query],
            n_results=min(top_k, collection.count()),
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        logger.warning("RAG query failed: %s", exc)
        return []

    passages: list[RAGPassage] = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]

    for doc, meta, dist in zip(docs, metas, dists):
        # ChromaDB cosine distance: 0 = identical, 2 = opposite
        relevance = round(1.0 - dist / 2.0, 4)
        passages.append(RAGPassage(
            passage=doc,
            source=meta.get("source", "unknown"),
            source_type=meta.get("source_type", "reference"),
            relevance_score=relevance,
        ))

    return passages


def build_prospect_query(
    segment: int,
    company_name: str,
    ai_maturity_score: int,
    tfidf_terms: list[str] | None = None,
    topic_label: str | None = None,
) -> str:
    """
    Build a RAG query dynamically from prospect signals.
    More specific queries produce more relevant retrievals.
    """
    segment_context = {
        1: "Series A or Series B startup scaling engineering team",
        2: "mid-market platform restructuring after layoff",
        3: "company with new CTO or VP Engineering appointed",
        4: "company with specialized AI/ML capability gap",
        0: "company with unclear buying signal",
    }
    ctx = segment_context.get(segment, "technology company")

    parts = [f"How should we approach a {ctx}?"]
    if company_name:
        parts.append(f"Company: {company_name}.")
    if ai_maturity_score >= 2:
        parts.append("Company has strong AI/ML signals.")
    elif ai_maturity_score == 1:
        parts.append("Company is building early AI capability.")
    if tfidf_terms:
        parts.append(f"Key technology terms: {', '.join(tfidf_terms[:5])}.")
    if topic_label:
        parts.append(f"Industry theme: {topic_label}.")

    return " ".join(parts)
