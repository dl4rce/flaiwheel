# MCP Docs Vektor – Code Teil 3: MCP Server & Git Watcher

## `src/mcp_docs_vector/server.py`

```python
# src/mcp_docs_vector/server.py
"""
MCP Server – stellt Tools für Cursor/Claude/Agents bereit.
Tools:
  - search_docs: Semantische Suche in der gesamten Doku
  - search_bugfixes: Suche nur in Bugfix-Summaries
  - search_by_type: Suche gefiltert nach Dokument-Typ
  - write_bugfix_summary: Bugfix dokumentieren + sofort indizieren
  - get_index_stats: Index-Statistiken
  - reindex: Manueller Re-Index
"""
from datetime import date
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from .config import Config
from .indexer import DocsIndexer

# Singleton – wird von web.py mitgenutzt
config = Config.load()
indexer = DocsIndexer(config)

# Initial indexing
print(f"🔍 Indexing {config.docs_path} ...")
result = indexer.index_all()
print(f"✅ {result}")

mcp = FastMCP(
    "mcp-docs-vector",
    instructions="""Semantische Suche über Projektdokumentation.
    
    WORKFLOW für den Agent:
    1. IMMER zuerst search_docs() bevor Code geändert wird
    2. search_bugfixes() um aus vergangenen Bugs zu lernen
    3. Lieber 2-3 gezielte Suchen als eine vage
    4. NACH jedem Bugfix: write_bugfix_summary() aufrufen
    5. Wenn ein Chunk nicht reicht → gezielt nachsuchen"""
)


@mcp.tool()
def search_docs(query: str, top_k: int = 5) -> str:
    """Semantische Suche über die GESAMTE Projektdokumentation.
    Gibt nur die relevantesten Chunks zurück (token-effizient!).
    
    Nutze dies IMMER bevor du Code schreibst oder änderst.
    
    Args:
        query: Was du wissen willst (natürliche Sprache, so spezifisch wie möglich)
        top_k: Anzahl Ergebnisse (default: 5, erhöhe bei breiten Fragen)
    
    Returns:
        Relevante Dokumentations-Chunks mit Quellenangabe und Relevanz-Score
    """
    results = indexer.search(query, top_k=top_k)
    
    if not results:
        return "❌ Keine relevanten Dokumente gefunden. Versuche eine andere/spezifischere Suchanfrage."
    
    output = []
    for r in results:
        output.append(
            f"📄 **{r['source']}** → _{r['heading']}_ "
            f"(Relevanz: {r['relevance']}%, Typ: {r['type']})\n\n"
            f"{r['text']}\n\n---"
        )
    return "\n".join(output)


@mcp.tool()
def search_bugfixes(query: str, top_k: int = 5) -> str:
    """Durchsucht NUR die Bugfix-Summaries nach ähnlichen vergangenen Problemen.
    Nutze dies um aus früheren Bugs zu lernen und Wiederholungen zu vermeiden.
    
    Args:
        query: Beschreibung des aktuellen Problems/Bugs
        top_k: Anzahl Ergebnisse (default: 5)
    
    Returns:
        Ähnliche Bugfix-Summaries mit Root Cause, Lösung und Lessons Learned
    """
    results = indexer.search(query, top_k=top_k, type_filter="bugfix")
    
    if not results:
        return ("Keine ähnlichen Bugfixes gefunden – dies könnte ein neues Problem sein. "
                "Vergiss nicht, nach dem Fix write_bugfix_summary() aufzurufen!")
    
    output = [f"🐛 Gefunden: {len(results)} ähnliche Bugfixes\n"]
    for r in results:
        output.append(
            f"### 🐛 {r['source']} (Relevanz: {r['relevance']}%)\n\n"
            f"{r['text']}\n\n---"
        )
    return "\n".join(output)


@mcp.tool()
def search_by_type(query: str, doc_type: str, top_k: int = 5) -> str:
    """Suche gefiltert nach Dokumenttyp.
    
    Args:
        query: Suchanfrage
        doc_type: Einer von: "docs", "bugfix", "best-practice", "api", 
                  "architecture", "changelog", "setup", "readme"
        top_k: Anzahl Ergebnisse
    """
    results = indexer.search(query, top_k=top_k, type_filter=doc_type)
    
    if not results:
        return f"Keine Ergebnisse vom Typ '{doc_type}' gefunden."
    
    output = []
    for r in results:
        output.append(
            f"📄 **{r['source']}** → _{r['heading']}_ ({r['relevance']}%)\n\n"
            f"{r['text']}\n\n---"
        )
    return "\n".join(output)


@mcp.tool()
def write_bugfix_summary(
    title: str,
    root_cause: str,
    solution: str,
    lesson_learned: str,
    affected_files: str = "",
    tags: str = ""
) -> str:
    """Schreibt eine Bugfix-Summary als .md Datei und indiziert sie SOFORT.
    
    MUSS nach jedem Bugfix aufgerufen werden! Diese Summaries werden bei
    zukünftigen Bugs gefunden und helfen, Fehler nicht zu wiederholen.
    
    Args:
        title: Kurzer, beschreibender Titel des Bugs
        root_cause: Was war die eigentliche Ursache? (technisch)
        solution: Wie wurde es gelöst? (Code-Änderungen beschreiben)
        lesson_learned: Was sollte in Zukunft anders gemacht werden?
        affected_files: Betroffene Dateien (komma-getrennt)
        tags: Kategorien (z.B. "payment,race-condition,critical")
    """
    # Slug erstellen
    slug = title.lower()
    for char in [" ", "/", "\\", ":", "'", '"', "?", "!"]:
        slug = slug.replace(char, "-")
    slug = slug[:60].strip("-")
    
    filename = f"bugfix-log/{date.today().isoformat()}-{slug}.md"
    filepath = Path(config.docs_path) / filename
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    content = f"""# 🐛 {title}

**Datum:** {date.today().isoformat()}  
**Tags:** {tags}  
**Betroffene Dateien:** {affected_files}

## Root Cause
{root_cause}

## Lösung
{solution}

## Lesson Learned
{lesson_learned}
"""
    
    filepath.write_text(content, encoding="utf-8")
    chunk_count = indexer.index_single(filename, content)
    
    return (
        f"✅ Bugfix-Summary gespeichert und indiziert!\n"
        f"   Datei: {filename}\n"
        f"   Chunks: {chunk_count}\n"
        f"   → Wird ab sofort bei ähnlichen Bugs gefunden."
    )


@mcp.tool()
def get_index_stats() -> str:
    """Zeigt Statistiken über den aktuellen Vektor-Index."""
    stats = indexer.stats
    
    type_dist = "\n".join(
        f"  - {t}: {c} Chunks" for t, c in stats["type_distribution"].items()
    ) or "  (leer)"
    
    return (
        f"📊 **Index-Statistiken**\n\n"
        f"- **Chunks gesamt:** {stats['total_chunks']}\n"
        f"- **Docs-Pfad:** {stats['docs_path']}\n"
        f"- **Embedding:** {stats['embedding_provider']} ({stats['embedding_model']})\n"
        f"- **Chunking:** {stats['chunk_strategy']}\n\n"
        f"**Typ-Verteilung:**\n{type_dist}"
    )


@mcp.tool()
def reindex() -> str:
    """Indiziert die gesamte Dokumentation neu.
    Nutze dies wenn sich viele Dateien geändert haben."""
    result = indexer.index_all()
    return (
        f"✅ Re-Index abgeschlossen!\n"
        f"   Files: {result['files_indexed']}\n"
        f"   Chunks: {result['chunks_created']}"
    )


def run_mcp():
    """Startet den MCP-Server (wird von entrypoint aufgerufen)."""
    if config.transport == "sse":
        mcp.run(transport="sse", port=config.sse_port)
    else:
        mcp.run(transport="stdio")
```

---

## `src/mcp_docs_vector/watcher.py`

```python
# src/mcp_docs_vector/watcher.py
"""
Git Watcher – periodischer Pull + Re-Index bei Änderungen.
Läuft als Background-Thread.
"""
import subprocess
import time
import threading
from pathlib import Path
from .config import Config
from .indexer import DocsIndexer


class GitWatcher:
    def __init__(self, config: Config, indexer: DocsIndexer):
        self.config = config
        self.indexer = indexer
        self._running = False
        self._thread = None
        self._last_commit = None
    
    def clone_if_needed(self) -> bool:
        """Klont das Repo falls /docs leer ist und eine Git-URL konfiguriert ist."""
        if not self.config.git_repo_url:
            return False
        
        docs = Path(self.config.docs_path)
        
        # Schon geklont?
        if (docs / ".git").exists():
            return False
        
        # Ist der Ordner leer genug zum Klonen?
        if docs.exists() and any(docs.iterdir()):
            print(f"⚠️ {docs} ist nicht leer, überspringe Git Clone")
            return False
        
        print(f"📥 Cloning {self.config.git_repo_url} → {docs}")
        
        clone_url = self.config.git_repo_url
        if self.config.git_token and "github.com" in clone_url:
            # Token in URL einfügen für private Repos
            clone_url = clone_url.replace(
                "https://", f"https://{self.config.git_token}@"
            )
        
        subprocess.run([
            "git", "clone",
            "--branch", self.config.git_branch,
            "--single-branch",
            "--depth", "1",
            clone_url,
            str(docs)
        ], check=True)
        
        # Wenn ein Subpath konfiguriert ist, müssen wir den docs_path anpassen
        if self.config.git_docs_subpath:
            actual_path = docs / self.config.git_docs_subpath
            if actual_path.exists():
                print(f"📂 Git Subpath: {actual_path}")
        
        return True
    
    def _get_current_commit(self) -> str:
        """Holt den aktuellen Commit-Hash."""
        docs = Path(self.config.docs_path)
        git_dir = docs
        
        # Falls docs kein Git-Root ist, suche .git nach oben
        while git_dir != git_dir.parent:
            if (git_dir / ".git").exists():
                break
            git_dir = git_dir.parent
        
        try:
            result = subprocess.run(
                ["git", "-C", str(git_dir), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout.strip()
        except Exception:
            return ""
    
    def pull_and_check(self) -> bool:
        """Pullt und gibt True zurück wenn sich etwas geändert hat."""
        docs = Path(self.config.docs_path)
        git_dir = docs
        
        while git_dir != git_dir.parent:
            if (git_dir / ".git").exists():
                break
            git_dir = git_dir.parent
        
        if not (git_dir / ".git").exists():
            return False
        
        old_commit = self._get_current_commit()
        
        try:
            subprocess.run(
                ["git", "-C", str(git_dir), "pull", "--ff-only"],
                capture_output=True, timeout=30, check=True
            )
        except subprocess.CalledProcessError as e:
            print(f"⚠️ Git pull failed: {e}")
            return False
        
        new_commit = self._get_current_commit()
        changed = old_commit != new_commit
        
        if changed:
            print(f"🔄 Neuer Commit: {old_commit[:8]} → {new_commit[:8]}")
        
        return changed
    
    def start(self):
        """Startet den Background-Sync-Thread."""
        if not self.config.git_repo_url:
            print("ℹ️ Kein Git-Repo konfiguriert, Watcher deaktiviert")
            return
        
        if self.config.git_sync_interval <= 0:
            print("ℹ️ Git sync interval = 0, Watcher deaktiviert")
            return
        
        # Erst mal clonen falls nötig
        self.clone_if_needed()
        
        self._running = True
        self._thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._thread.start()
        print(f"👀 Git Watcher gestartet (alle {self.config.git_sync_interval}s)")
    
    def stop(self):
        """Stoppt den Watcher."""
        self._running = False
    
    def _sync_loop(self):
        """Endlos-Loop: Pull → Check → Reindex."""
        while self._running:
            time.sleep(self.config.git_sync_interval)
            try:
                if self.pull_and_check():
                    print("🔄 Änderungen erkannt, reindexiere...")
                    result = self.indexer.index_all()
                    print(f"✅ Reindex: {result}")
                else:
                    pass  # Keine Änderungen, still sein
            except Exception as e:
                print(f"⚠️ Git Watcher Fehler: {e}")
```
