"""Build and query the research knowledge index using LanceDB + OpenAI/Gemini Embedding.

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

# ── Config ────────────────────────────────────────────────────────────
STORAGE = Path(__file__).parent.parent / "storage"
LANCE_DIR = STORAGE / "knowledge_index"

# Embedding provider: "openai" (default, cheap + stable) or "gemini"
EMBED_PROVIDER = os.environ.get("EMBED_PROVIDER", "openai")
EMBED_DIM = 768  # both providers output 768 when configured
BATCH_SIZE = 100 if EMBED_PROVIDER == "openai" else 20
TABLE_NAME = "research_memory"

# Provider-specific config
_OPENAI_MODEL = "text-embedding-3-small"  # $0.02/1M tokens
_GEMINI_MODEL = "gemini-embedding-001"    # $0.15/1M tokens


# ── Embedding ─────────────────────────────────────────────────────────
def _load_env():
    """Load API keys from .env and .env.local files."""
    for env_name in [".env.local", ".env"]:
        env_path = Path(__file__).parent.parent / env_name
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())


def get_client():
    _load_env()
    if EMBED_PROVIDER == "openai":
        import openai
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("ERROR: OPENAI_API_KEY not found. Set it in .env.local or environment.")
            sys.exit(1)
        return openai.OpenAI(api_key=api_key)
    else:
        from google import genai
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
    """Embed a batch of texts. Works with both OpenAI and Gemini clients."""
    # OpenAI has 8192 token limit per input; truncate by token count
    if EMBED_PROVIDER == "openai":
        try:
            import tiktoken
            enc = tiktoken.encoding_for_model(_OPENAI_MODEL)
            truncated = []
            for t in texts:
                tokens = enc.encode(t)
                if len(tokens) > 8000:
                    truncated.append(enc.decode(tokens[:8000]))
                else:
                    truncated.append(t)
            texts = truncated
        except ImportError:
            # Fallback: aggressive char truncation for CJK safety
            texts = [t[:6000] if len(t) > 6000 else t for t in texts]
    vectors = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        if EMBED_PROVIDER == "openai":
            resp = client.embeddings.create(
                input=batch,
                model=_OPENAI_MODEL,
                dimensions=EMBED_DIM,
            )
            for item in resp.data:
                vectors.append(item.embedding)
        else:
            result = client.models.embed_content(
                model=_GEMINI_MODEL,
                contents=batch,
                config={"output_dimensionality": EMBED_DIM},
            )
            for emb in result.embeddings:
                vectors.append(emb.values)
        if i + BATCH_SIZE < len(texts):
            time.sleep(0.5)
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


def load_storage_experiments() -> list[dict]:
    """Load storage/experiments/*.json (early experiment results not in memory/experiments.json)."""
    exp_dir = STORAGE / "experiments"
    if not exp_dir.exists():
        return []
    docs = []
    for f in sorted(exp_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            # Different formats: some are dicts with 'title', some are raw results
            if isinstance(data, dict):
                title = data.get("title", data.get("experiment_id", f.stem))
                content = data.get("content", data.get("summary", data.get("description", "")))
                tags = data.get("tags", [])
                text = f"[storage_experiment] {title}. {content}. Tags: {', '.join(tags) if isinstance(tags, list) else tags}"
                docs.append({
                    "source": "experiment",
                    "category": "storage_experiment",
                    "text": text[:20000],
                    "timestamp": data.get("created_at", data.get("timestamp", "")),
                    "confidence": 0,
                    "evidence": f.stem,
                })
        except (json.JSONDecodeError, Exception):
            pass
    return docs


def load_strategy_data() -> list[dict]:
    """Load strategy metrics and backtest summaries."""
    docs = []
    for fname in ["strategy_metrics.json", "risk_forecast.json"]:
        path = STORAGE / fname
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                text = f"[{fname}] {json.dumps(data, ensure_ascii=False)}"
                docs.append({
                    "source": "strategy",
                    "category": fname.replace(".json", ""),
                    "text": text[:20000],
                    "timestamp": "",
                    "confidence": 0,
                    "evidence": fname,
                })
        except Exception:
            pass
    return docs


def load_research_archive() -> list[dict]:
    """Load archived completed research phases from docs/research_archive/."""
    archive_dir = Path(__file__).resolve().parent.parent / "docs" / "research_archive"
    if not archive_dir.exists():
        return []
    docs = []
    for f in sorted(archive_dir.glob("*.md")):
        text = f.read_text()
        # Split into chunks of ~2000 chars for better retrieval
        chunks = [text[i:i+2000] for i in range(0, len(text), 1800)]
        for j, chunk in enumerate(chunks):
            docs.append({
                "source": "archive",
                "category": "completed_research",
                "text": f"[research_archive/{f.name}#chunk{j}] {chunk}",
                "timestamp": "",
                "confidence": 0,
                "evidence": f.name,
            })
    return docs


def load_experiences() -> list[dict]:
    """Load experiment_experiences.json (Exxx lessons learned)."""
    path = STORAGE / "memory" / "experiment_experiences.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    entries = data if isinstance(data, list) else data.get("experiences", data.get("entries", []))
    docs = []
    for e in entries:
        eid = e.get("id", "")
        text = (
            f"[experience] {eid}: {e.get('title', '')}. "
            f"{e.get('lesson', e.get('content', ''))} "
            f"Related experiments: {e.get('related_experiments', '')}. "
            f"Tags: {', '.join(e.get('tags', []))}"
        )
        docs.append({
            "source": "experience",
            "category": "lesson",
            "text": text[:20000],
            "timestamp": e.get("created_at", ""),
            "confidence": 0,
            "evidence": eid,
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
    model_name = _OPENAI_MODEL if EMBED_PROVIDER == "openai" else _GEMINI_MODEL
    print(f"Generating embeddings with {model_name} (dim={EMBED_DIM}, provider={EMBED_PROVIDER})...")
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


def _load_all_docs(only_sources: set[str] | None = None) -> list[dict]:
    """Load documents from sources. If only_sources is set, skip others."""
    all_docs = []
    loaders = [
        ("knowledge", load_knowledge),
        ("thinking", load_thinking),
        ("experiments", load_experiments),
        ("storage_experiments", load_storage_experiments),
        ("experiences", load_experiences),
        ("questions", load_questions),
        ("research_log", load_research_log),
        ("feed", load_feed),
        ("references", load_references),
        ("paper", load_paper),
        ("notifications", load_notifications),
        ("research_program", load_research_program),
        ("strategy_data", load_strategy_data),
        ("research_archive", load_research_archive),
    ]
    for name, loader in loaders:
        if only_sources is not None and name not in only_sources:
            continue
        docs = loader()
        print(f"  {name}: {len(docs)} docs")
        all_docs.extend(docs)
    if only_sources is not None:
        skipped = len(loaders) - (len(only_sources) if only_sources else 0)
        print(f"  (skipped {skipped} unchanged sources)")
    return all_docs


def update_index(changed_sources: set[str] | None = None):
    """Incremental update: only embed and add NEW documents.

    If changed_sources is provided, only load and check those sources.
    Stale detection is also scoped to changed sources only.
    """
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

    # Scope existing hashes to changed sources only (if specified)
    if changed_sources is not None and "source" in existing_df.columns:
        # Map loader names to source values in the index
        # Some loaders produce docs with different source names
        source_values = set()
        source_mapping = {
            "knowledge": {"knowledge"},
            "thinking": {"thinking"},
            "experiments": {"experiment"},
            "storage_experiments": {"experiment"},
            "experiences": {"experience"},
            "questions": {"question"},
            "research_log": {"research_log"},
            "feed": {"feed"},
            "references": {"reference"},
            "paper": {"paper"},
            "notifications": {"notification"},
            "research_program": {"research_program"},
            "strategy_data": {"strategy"},
            "research_archive": {"archive"},
        }
        for src in changed_sources:
            source_values.update(source_mapping.get(src, {src}))
        scoped_df = existing_df[existing_df["source"].isin(source_values)]
        existing_hashes = set(scoped_df["doc_hash"].tolist())
        print(f"  Existing index: {len(existing_df)} total, {len(existing_hashes)} in changed sources")
    else:
        existing_hashes = set(existing_df["doc_hash"].tolist())
        print(f"  Existing index: {len(existing_hashes)} documents")

    # Load current documents (only changed sources if specified)
    print("Loading current documents...")
    all_docs = _load_all_docs(only_sources=changed_sources)
    print(f"  Loaded docs: {len(all_docs)}")

    # Compute current hashes for loaded docs
    current_hashes = {}
    for doc in all_docs:
        h = compute_doc_hash(doc["text"])
        current_hashes[h] = doc

    # Delete stale rows (docs that were edited/removed — old hash no longer exists)
    # Only check within the scope of changed sources
    stale_hashes = existing_hashes - set(current_hashes.keys())
    if stale_hashes:
        print(f"\n  Removing {len(stale_hashes)} stale entries (edited/deleted docs)...")
        # LanceDB delete uses SQL-like filter; delete in batches to avoid overly long expressions
        stale_list = list(stale_hashes)
        for i in range(0, len(stale_list), 50):
            batch = stale_list[i : i + 50]
            filter_expr = "doc_hash IN (" + ", ".join(f"'{h}'" for h in batch) + ")"
            table.delete(filter_expr)
        print(f"  Removed {len(stale_hashes)} stale entries")

    # Find new documents by comparing hashes
    new_docs = []
    for h, doc in current_hashes.items():
        if h not in existing_hashes:
            doc["_hash"] = h
            new_docs.append(doc)

    if not new_docs and not stale_hashes:
        print("\nNo new documents found. Index is up to date.")
        return

    if not new_docs:
        total = len(existing_hashes) - len(stale_hashes)
        print(f"\nIndex cleaned: -{len(stale_hashes)} stale entries (total: {total})")
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
    total = len(existing_hashes) - len(stale_hashes) + len(new_data)
    print(f"Index updated: +{len(new_data)} new, -{len(stale_hashes)} stale (total: {total})")


# ── Search ────────────────────────────────────────────────────────────
def search(query: str, n: int = 10, source_filter: str = None):
    """Semantic search across all research memory."""
    client = get_client()
    db = lancedb.connect(str(LANCE_DIR))
    table = db.open_table(TABLE_NAME)

    # Embed query
    query_vec = embed_texts(client, [query])[0]

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

    query_vec = embed_texts(client, [topic])[0]

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
        # Detect changes in memory files + other indexed sources
        memory_dir = Path(__file__).resolve().parent.parent / "storage" / "memory"
        state_file = memory_dir.parent / ".knowledge_index_state.json"
        current = {}
        # Core memory files
        watch_files = list(sorted(memory_dir.glob("*.json")))
        # Additional indexed sources outside memory/
        watch_files.append(memory_dir.parent / "reports" / "feed.json")
        watch_files.append(Path(__file__).resolve().parent.parent / "research_program.md")
        ref_dir = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "autonomous-research" / "references"
        if ref_dir.exists():
            watch_files.extend(sorted(ref_dir.glob("*.md")))
        paper_complete = Path(__file__).resolve().parent.parent / "paper_complete.md"
        if paper_complete.exists():
            watch_files.append(paper_complete)
        for f in watch_files:
            if f.exists():
                current[str(f.name)] = f.stat().st_mtime
        prev = {}
        if state_file.exists():
            prev = json.loads(state_file.read_text())
        if current != prev:
            changed = [k for k in current if current.get(k) != prev.get(k)]
            print(f"Changes detected in: {', '.join(changed)}")
            # Map changed file names to loader source names
            file_to_source = {
                "knowledge.json": "knowledge",
                "thinking_journal.json": "thinking",
                "experiments.json": "storage_experiments",
                "experiment_experiences.json": "experiences",
                "open_questions.json": "questions",
                "research_log.json": "research_log",
                "feed.json": "feed",
                "research_program.md": "research_program",
                "notifications.json": "notifications",
            }
            changed_sources = set()
            for fname in changed:
                if fname in file_to_source:
                    changed_sources.add(file_to_source[fname])
                elif fname.endswith(".md"):
                    # Reference files or paper files
                    changed_sources.add("references")
                    changed_sources.add("paper")
                else:
                    # Unknown file changed — fall back to full scan
                    changed_sources = None
                    break
            if changed_sources is not None:
                print(f"Targeted sources: {', '.join(sorted(changed_sources))}")
            else:
                print("Unknown changed file — full scan")
            update_index(changed_sources=changed_sources)
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
