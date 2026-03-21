"""Build and query the research knowledge index using LanceDB + Gemini Embedding.

This script indexes ALL research artifacts into a single searchable vector database,
enabling semantic retrieval of knowledge, thinking patterns, experiments, and more.

Usage:
    # Build/rebuild the full index (re-embeds everything)
    uv run python scripts/build_knowledge_index.py build

    # Incremental update (only embeds NEW documents)
    uv run python scripts/build_knowledge_index.py update

    # Search (returns rich context, not just top-5)
    uv run python scripts/build_knowledge_index.py search "GLD inverted leverage regime"

    # Load session context (broad retrieval for session start)
    uv run python scripts/build_knowledge_index.py context "Iran crisis VaR validation"

    # Stats
    uv run python scripts/build_knowledge_index.py stats
"""
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import lancedb
from google import genai

# ── Config ────────────────────────────────────────────────────────────
STORAGE = Path(__file__).parent.parent / "storage"
LANCE_DIR = STORAGE / "knowledge_index"
EMBED_MODEL = "gemini-embedding-001"  # stable; switch to gemini-embedding-2-preview when GA
EMBED_DIM = 768
BATCH_SIZE = 20  # Gemini free tier friendly
TABLE_NAME = "research_memory"


# ── Embedding ─────────────────────────────────────────────────────────
def get_client():
    # Try multiple env var names, also load from .env file
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

    api_key = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GOOGLE_CLOUD_API_KEY")
    )
    if not api_key:
        print("ERROR: No Google/Gemini API key found in environment or .env file.")
        sys.exit(1)
    return genai.Client(api_key=api_key)


def embed_texts(client, texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts using Gemini Embedding API."""
    vectors = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        result = client.models.embed_content(
            model=EMBED_MODEL,
            contents=batch,
            config={"output_dimensionality": EMBED_DIM},
        )
        for emb in result.embeddings:
            vectors.append(emb.values)
        if i + BATCH_SIZE < len(texts):
            time.sleep(1)  # respect rate limits
    return vectors


def compute_doc_hash(text: str) -> str:
    """Compute SHA256 hash of document text for deduplication."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Document Loaders ──────────────────────────────────────────────────
def load_knowledge() -> list[dict]:
    """Load knowledge.json entries."""
    path = STORAGE / "memory" / "knowledge.json"
    if not path.exists():
        return []
    entries = json.loads(path.read_text())
    docs = []
    for e in entries:
        text = f"[{e.get('category', '')}] {e.get('content', '')}"
        docs.append({
            "source": "knowledge",
            "category": e.get("category", ""),
            "text": text,
            "timestamp": e.get("timestamp", ""),
            "confidence": e.get("confidence", 0),
            "evidence": json.dumps(e.get("evidence", [])),
        })
    return docs


def load_thinking() -> list[dict]:
    """Load thinking_journal.json entries."""
    path = STORAGE / "memory" / "thinking_journal.json"
    if not path.exists():
        return []
    entries = json.loads(path.read_text())
    docs = []
    for e in entries:
        content = e.get("thought", "") or e.get("content", "")
        if not content or len(content) < 20:
            continue  # skip empty entries
        docs.append({
            "source": "thinking",
            "category": "thinking",
            "text": content[:2000],  # truncate very long entries
            "timestamp": e.get("timestamp", ""),
            "confidence": 0,
            "evidence": "",
        })
    return docs


def load_experiments() -> list[dict]:
    """Load experiments.json entries."""
    path = STORAGE / "memory" / "experiments.json"
    if not path.exists():
        return []
    entries = json.loads(path.read_text())
    docs = []
    for e in entries:
        config = e.get("config", {})
        metrics = e.get("metrics", {})
        text = (
            f"Experiment {e.get('experiment_id', '')}: "
            f"{e.get('model_name', '')} on {e.get('asset', '')} "
            f"w={config.get('window', '')} dist={config.get('dist', '')} "
            f"OOS {config.get('oos_start', '')}-{config.get('oos_end', '')} "
            f"QLIKE={metrics.get('qlike', '')} "
            f"VaR1%={metrics.get('var_1pct_rate', '')} "
            f"Notes: {e.get('notes', '')}"
        )
        docs.append({
            "source": "experiment",
            "category": e.get("model_name", ""),
            "text": text,
            "timestamp": e.get("timestamp", ""),
            "confidence": 0,
            "evidence": e.get("experiment_id", ""),
        })
    return docs


def load_questions() -> list[dict]:
    """Load open_questions.json."""
    path = STORAGE / "memory" / "open_questions.json"
    if not path.exists():
        return []
    entries = json.loads(path.read_text())
    docs = []
    for e in entries:
        docs.append({
            "source": "question",
            "category": str(e.get("priority", "medium")),
            "text": f"[{e.get('priority', 'medium')}] {e.get('question', '')}",
            "timestamp": e.get("timestamp", ""),
            "confidence": 0.0,
            "evidence": "",
        })
    return docs


def load_research_log() -> list[dict]:
    """Load research_log.json."""
    path = STORAGE / "memory" / "research_log.json"
    if not path.exists():
        return []
    entries = json.loads(path.read_text())
    docs = []
    for e in entries:
        text = (
            f"[{e.get('phase', '')}] {e.get('action', '')}: "
            f"{e.get('observation', '')} → {e.get('decision', '')}"
        )
        docs.append({
            "source": "research_log",
            "category": e.get("phase", ""),
            "text": text,
            "timestamp": e.get("timestamp", ""),
            "confidence": 0,
            "evidence": "",
        })
    return docs


def load_feed() -> list[dict]:
    """Load reports/feed.json."""
    path = STORAGE / "reports" / "feed.json"
    if not path.exists():
        return []
    entries = json.loads(path.read_text())
    docs = []
    for e in entries:
        text = f"{e.get('title', '')}: {e.get('description', '')}"
        docs.append({
            "source": "feed",
            "category": e.get("type", ""),
            "text": text[:2000],
            "timestamp": e.get("timestamp", e.get("published_at", "")),
            "confidence": 0,
            "evidence": e.get("id", ""),
        })
    return docs


def load_references() -> list[dict]:
    """Load references/*.md files, split into chunks."""
    ref_dir = Path(__file__).parent.parent / ".claude" / "skills" / "autonomous-research" / "references"
    if not ref_dir.exists():
        return []
    docs = []
    for md_file in ref_dir.glob("*.md"):
        content = md_file.read_text()
        sections = content.split("\n## ")
        for i, section in enumerate(sections):
            if len(section.strip()) < 30:
                continue
            docs.append({
                "source": "reference",
                "category": md_file.stem,
                "text": f"[{md_file.stem}] {section[:2000]}",
                "timestamp": "",
                "confidence": 0,
                "evidence": f"{md_file.name}#section-{i}",
            })
    return docs


def load_paper() -> list[dict]:
    """Load paper_complete.md, split into sections."""
    paper_path = Path(__file__).parent.parent / "paper_complete.md"
    if not paper_path.exists():
        return []
    content = paper_path.read_text()
    docs = []
    sections = content.split("\n# ")
    for i, section in enumerate(sections):
        if len(section.strip()) < 50:
            continue
        header = section.split("\n")[0].strip("# ")
        # Further split long sections by ##
        subsections = section.split("\n## ")
        for j, sub in enumerate(subsections):
            if len(sub.strip()) < 50:
                continue
            sub_header = sub.split("\n")[0].strip("# ")
            docs.append({
                "source": "paper",
                "category": header[:50],
                "text": f"[Paper §{header}/{sub_header}] {sub[:2000]}",
                "timestamp": "",
                "confidence": 0,
                "evidence": f"paper_complete.md#section-{i}-{j}",
            })
    return docs


def load_notifications() -> list[dict]:
    """Load notification history if exists."""
    notif_dir = STORAGE / "notifications"
    if not notif_dir.exists():
        return []
    docs = []
    for f in notif_dir.glob("*.json"):
        try:
            entries = json.loads(f.read_text())
            if isinstance(entries, list):
                for e in entries:
                    docs.append({
                        "source": "notification",
                        "category": e.get("level", "info"),
                        "text": f"{e.get('subject', '')}: {e.get('body', '')}",
                        "timestamp": e.get("timestamp", ""),
                        "confidence": 0,
                        "evidence": f.name,
                    })
        except Exception:
            pass
    return docs


def load_research_program() -> list[dict]:
    """Load research_program.md as indexed chunks."""
    rp_path = Path(__file__).parent.parent / "research_program.md"
    if not rp_path.exists():
        return []
    content = rp_path.read_text()
    docs = []
    sections = content.split("\n#### ")
    for i, section in enumerate(sections):
        if len(section.strip()) < 30:
            continue
        header = section.split("\n")[0].strip("# ")
        docs.append({
            "source": "research_program",
            "category": header[:50],
            "text": f"[research_program] {section[:2000]}",
            "timestamp": "",
            "confidence": 0,
            "evidence": f"research_program.md#section-{i}",
        })
    return docs


# ── Index Building ────────────────────────────────────────────────────
def build_index():
    """Build the full LanceDB index from all sources."""
    print("Loading documents...")
    all_docs = _load_all_docs()

    print(f"\nTotal: {len(all_docs)} documents to index")

    # Generate embeddings
    print(f"Generating embeddings with {EMBED_MODEL} (dim={EMBED_DIM})...")
    client = get_client()
    texts = [d["text"] for d in all_docs]
    vectors = embed_texts(client, texts)
    print(f"  Generated {len(vectors)} embeddings")

    # Build LanceDB table
    print(f"Building LanceDB index at {LANCE_DIR}...")
    db = lancedb.connect(str(LANCE_DIR))

    # Prepare data with vectors and doc hashes
    data = []
    for doc, vec in zip(all_docs, vectors):
        data.append({
            "vector": vec,
            "source": doc["source"],
            "category": doc["category"],
            "text": doc["text"],
            "timestamp": doc["timestamp"],
            "confidence": doc["confidence"],
            "evidence": doc["evidence"],
            "doc_hash": compute_doc_hash(doc["text"]),
        })

    # Drop and recreate
    if TABLE_NAME in db.table_names():
        db.drop_table(TABLE_NAME)
    table = db.create_table(TABLE_NAME, data)
    print(f"✓ Index built: {len(data)} entries in '{TABLE_NAME}'")
    print(f"  Storage: {LANCE_DIR}")


def _load_all_docs() -> list[dict]:
    """Load all documents from all sources (shared by build and update)."""
    all_docs = []
    loaders = [
        ("knowledge", load_knowledge),
        ("thinking", load_thinking),
        ("experiments", load_experiments),
        ("questions", load_questions),
        ("research_log", load_research_log),
        ("feed", load_feed),
        ("references", load_references),
        ("paper", load_paper),
        ("notifications", load_notifications),
        ("research_program", load_research_program),
    ]
    for name, loader in loaders:
        docs = loader()
        print(f"  {name}: {len(docs)} docs")
        all_docs.extend(docs)
    return all_docs


def update_index():
    """Incremental update: only embed and add NEW documents."""
    db = lancedb.connect(str(LANCE_DIR))

    # Check if table exists
    if TABLE_NAME not in db.table_names():
        print("No existing index found. Running full build instead...")
        build_index()
        return

    table = db.open_table(TABLE_NAME)

    # Load existing hashes from the table
    print("Loading existing index...")
    existing_df = table.to_pandas()

    if "doc_hash" not in existing_df.columns:
        print("Existing index has no doc_hash column (built before incremental support).")
        print("Running full rebuild to add doc_hash column...")
        build_index()
        return

    existing_hashes = set(existing_df["doc_hash"].tolist())
    print(f"  Existing index: {len(existing_hashes)} documents")

    # Load all current documents
    print("Loading current documents...")
    all_docs = _load_all_docs()
    print(f"  Total current docs: {len(all_docs)}")

    # Find new documents by comparing hashes
    new_docs = []
    for doc in all_docs:
        h = compute_doc_hash(doc["text"])
        if h not in existing_hashes:
            doc["_hash"] = h
            new_docs.append(doc)

    if not new_docs:
        print("\nNo new documents found. Index is up to date.")
        return

    print(f"\n  New documents to index: {len(new_docs)}")

    # Embed only the new documents
    t0 = time.time()
    print(f"Generating embeddings for {len(new_docs)} new docs...")
    client = get_client()
    texts = [d["text"] for d in new_docs]
    vectors = embed_texts(client, texts)
    print(f"  Generated {len(vectors)} embeddings in {time.time() - t0:.1f}s")

    # Prepare new rows
    new_data = []
    for doc, vec in zip(new_docs, vectors):
        new_data.append({
            "vector": vec,
            "source": doc["source"],
            "category": doc["category"],
            "text": doc["text"],
            "timestamp": doc["timestamp"],
            "confidence": doc["confidence"],
            "evidence": doc["evidence"],
            "doc_hash": doc["_hash"],
        })

    # Add to existing table
    table.add(new_data)
    total = len(existing_hashes) + len(new_data)
    print(f"Index updated: +{len(new_data)} new entries (total: {total})")


# ── Search ────────────────────────────────────────────────────────────
def search(query: str, n: int = 10, source_filter: str = None):
    """Semantic search across all research memory."""
    client = get_client()
    db = lancedb.connect(str(LANCE_DIR))
    table = db.open_table(TABLE_NAME)

    # Embed query
    result = client.models.embed_content(
        model=EMBED_MODEL,
        contents=query,
        config={"output_dimensionality": EMBED_DIM},
    )
    query_vec = result.embeddings[0].values

    # Search
    results = table.search(query_vec).limit(n)
    if source_filter:
        results = results.where(f"source = '{source_filter}'")
    results = results.to_pandas()

    print(f"\n=== Search: '{query}' (top {n}) ===\n")
    for _, row in results.iterrows():
        dist = row.get("_distance", 0)
        print(f"[{row['source']}/{row['category']}] (dist={dist:.3f})")
        print(f"  {row['text'][:200]}")
        if row["timestamp"]:
            print(f"  ts: {row['timestamp'][:19]}")
        print()


def load_context(topic: str, n_per_source: int = 8):
    """Reconstruct researcher memory for a session.

    This is NOT a search — it's a full memory reconstruction.
    For a given research topic, it loads:
    1. Relevant knowledge (what I know)
    2. Past thinking patterns (how I've reasoned about similar problems)
    3. Mistakes and lessons (what went wrong before)
    4. Open questions (what I should be investigating)
    5. User guidance (how the user wants me to work)
    6. Paper context (what I've already written)
    7. Experiment history (what I've tried)
    8. Research program (where I am in the overall plan)
    """
    client = get_client()
    db = lancedb.connect(str(LANCE_DIR))
    table = db.open_table(TABLE_NAME)

    result = client.models.embed_content(
        model=EMBED_MODEL,
        contents=topic,
        config={"output_dimensionality": EMBED_DIM},
    )
    query_vec = result.embeddings[0].values

    # Memory reconstruction layers — each with a specific purpose
    layers = [
        ("knowledge",       n_per_source * 2, "📚 WHAT I KNOW"),
        ("thinking",        n_per_source,     "🧠 HOW I'VE REASONED"),
        ("experiment",      n_per_source,     "🔬 WHAT I'VE TRIED"),
        ("question",        n_per_source,     "❓ WHAT I SHOULD EXPLORE"),
        ("research_log",    n_per_source,     "📝 DECISIONS I'VE MADE"),
        ("paper",           n_per_source,     "📄 WHAT I'VE WRITTEN"),
        ("reference",       n_per_source // 2,"📖 METHODOLOGY GUIDES"),
        ("feed",            n_per_source // 2,"📢 WHAT I'VE PUBLISHED"),
        ("research_program",n_per_source // 2,"🗺️ WHERE I AM"),
    ]

    print(f"\n{'='*60}")
    print(f"  MEMORY RECONSTRUCTION: '{topic}'")
    print(f"{'='*60}\n")

    total = 0
    context_text = []

    for src, limit, label in layers:
        try:
            results = (
                table.search(query_vec)
                .where(f"source = '{src}'")
                .limit(limit)
                .to_pandas()
            )
            if len(results) > 0:
                print(f"{label} ({len(results)} entries)")
                for _, row in results.iterrows():
                    text = row['text'][:300]
                    dist = row.get('_distance', 0)
                    relevance = "★" if dist < 0.3 else "☆" if dist < 0.5 else "·"
                    print(f"  {relevance} [{row['category']}] {text}")
                    context_text.append(text)
                print()
                total += len(results)
        except Exception:
            pass

    print(f"{'='*60}")
    print(f"  Total memory loaded: {total} entries")
    print(f"  Researcher is ready to work on: '{topic}'")
    print(f"{'='*60}")

    # Also save context to a temp file for easy loading
    ctx_path = STORAGE / "session_context.txt"
    ctx_path.write_text("\n\n---\n\n".join(context_text))
    print(f"\n  Context saved to: {ctx_path}")


def reconstruct_full(n_per_source: int = 10):
    """Full memory dump — load everything for comprehensive session."""
    client = get_client()
    db = lancedb.connect(str(LANCE_DIR))
    table = db.open_table(TABLE_NAME)

    # Get research_program current state for context
    rp_path = Path(__file__).parent.parent / "research_program.md"
    if rp_path.exists():
        rp_text = rp_path.read_text()
        # Find current phase from "- [ ]" items
        open_items = [l.strip() for l in rp_text.split("\n") if l.strip().startswith("- [ ]")]
        print(f"=== CURRENT OPEN ITEMS ({len(open_items)}) ===")
        for item in open_items[:10]:
            print(f"  {item}")

        # Use first open item as context query
        if open_items:
            topic = open_items[0].replace("- [ ]", "").strip()
            print(f"\n→ Auto-reconstructing memory around: '{topic[:80]}'")
            load_context(topic, n_per_source)
        else:
            print("No open items found. Research may be fully converged.")
    else:
        print("research_program.md not found.")


def stats():
    """Show index statistics."""
    db = lancedb.connect(str(LANCE_DIR))
    if TABLE_NAME not in db.table_names():
        print("Index not built yet. Run: uv run python scripts/build_knowledge_index.py build")
        return
    table = db.open_table(TABLE_NAME)
    df = table.to_pandas()
    print(f"=== Knowledge Index Stats ===")
    print(f"  Total entries: {len(df)}")
    print(f"  Sources:")
    for src, count in df["source"].value_counts().items():
        print(f"    {src}: {count}")
    print(f"  Storage: {LANCE_DIR}")


# ── CLI ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "auto":
        # Detect changes in memory files, only rebuild if changed
        memory_dir = Path(__file__).resolve().parent.parent / "storage" / "memory"
        state_file = memory_dir.parent / ".knowledge_index_state.json"
        current = {}
        for f in sorted(memory_dir.glob("*.json")):
            current[f.name] = f.stat().st_mtime
        prev = {}
        if state_file.exists():
            prev = json.loads(state_file.read_text())
        if current != prev:
            changed = [k for k in current if current.get(k) != prev.get(k)]
            print(f"Changes detected in: {', '.join(changed)}")
            update_index()
            state_file.write_text(json.dumps(current))
        else:
            print("No changes detected. Skipping index rebuild.")
    elif cmd == "build":
        build_index()
    elif cmd == "update":
        update_index()
    elif cmd == "search" and len(sys.argv) >= 3:
        query = " ".join(sys.argv[2:])
        n = int(sys.argv[-1]) if sys.argv[-1].isdigit() else 10
        search(query, n=n)
    elif cmd == "context" and len(sys.argv) >= 3:
        topic = " ".join(sys.argv[2:])
        load_context(topic)
    elif cmd == "reconstruct":
        # Auto-detect current research focus and load full context
        reconstruct_full()
    elif cmd == "stats":
        stats()
    else:
        print(__doc__)
        print("\nCommands:")
        print("  build                    Build/rebuild the full index (re-embeds everything)")
        print("  update                   Incremental update (only embeds NEW documents)")
        print("  search <query>           Semantic search across all memory")
        print("  context <topic>          Full memory reconstruction for a topic")
        print("  reconstruct              Auto-detect current focus and reconstruct")
        print("  stats                    Show index statistics")
