# MCP Docs Vektor – Self-Contained Docker mit Web-UI

## 🎯 Was ist das?

Ein **self-contained Docker-Container** der:
- Deine `.md` Projektdokumentation **semantisch indiziert** (Vektor-Embeddings)
- Einen **MCP-Server** bereitstellt (für Cursor, Claude Desktop, etc.)
- Ein **Web-Frontend** hat zum Konfigurieren (Ports, Embedding-Modelle, Git-Repo, etc.)
- **Lokal läuft** – kein API-Key nötig (lokale Embedding-Modelle)
- Per **Git auto-synced** und reindexiert
- **Bugfix-Summaries** schreibt und sofort indiziert → Lerneffekt über Zeit

---

## 📊 Lokale Embedding-Modelle – Vergleich (Stand 2025)

| Modell | Parameter | Dim | Speed (ms/1K tok) | Hit-Rate | RAM | Sprache | Empfehlung |
|---|---|---|---|---|---|---|---|
| `all-MiniLM-L6-v2` | 22M | 384 | **14.7** | 78.1% | ~90MB | EN | ⚡ Schnellstes, gut für große Repos |
| `all-MiniLM-L12-v2` | 33M | 384 | 18.5 | 80.2% | ~130MB | EN | Guter Kompromiss |
| `all-mpnet-base-v2` | 110M | 768 | 28.3 | 82.8% | ~420MB | EN | Sentence-Transformers Standard |
| `bge-base-en-v1.5` | 110M | 768 | 22.5 | 84.7% | ~420MB | EN | 🎯 Bestes Preis-Leistung EN |
| `bge-m3` (BAAI) | 568M | 1024 | 55.0 | 85.5% | ~2.2GB | **Multi** | 🌍 Bestes multilingual |
| `nomic-embed-text-v1` | 137M | 768 | 41.9 | **86.2%** | ~520MB | EN | 🏆 Beste Qualität lokal |
| `nomic-embed-text-v1.5` | 137M | 768 | 42.0 | **87.0%** | ~520MB | EN | 🏆🏆 Top Pick |
| `e5-small-v2` | 118M | 384 | 20.2 | 83.5% | ~450MB | EN | Überraschend gut für die Größe |
| `multilingual-e5-base` | 278M | 768 | 35.0 | 82.0% | ~1.1GB | **Multi** | Gut für DE/EN mixed |
| `multilingual-e5-large` | 560M | 1024 | 60.0 | 84.5% | ~2.1GB | **Multi** | Bestes multilingual E5 |

### Empfehlung je nach Situation:

- **Doku nur Englisch, großes Repo:** `all-MiniLM-L6-v2` (schnell + klein)
- **Doku Englisch, beste Qualität:** `nomic-embed-text-v1.5` 🏆
- **Doku Deutsch/Englisch gemischt:** `bge-m3` oder `multilingual-e5-large` 🌍
- **Wenig RAM (< 500MB):** `all-MiniLM-L6-v2` oder `e5-small-v2`
- **Maximale Qualität, RAM egal:** `nomic-embed-text-v1.5`

### Vergleich mit OpenAI (Referenz):

| | Lokal (nomic-embed) | OpenAI text-embedding-3-small |
|---|---|---|
| Kosten | **$0** | $0.02 / 1M Tokens |
| Latenz | ~42ms/1K tok | ~100ms + Netzwerk |
| Qualität | 87% Hit-Rate | ~89% Hit-Rate |
| Privatsphäre | **Alles lokal** | Daten gehen zu OpenAI |
| Offline | **Ja** | Nein |

→ **Fazit: Lokale Modelle sind gut genug!** Der Unterschied zu OpenAI ist marginal (2-3%), dafür kostenlos und privat.

---

## 🏗️ Architektur-Diagramm

```
┌──────────────────────────────────────────────────────────────┐
│  Docker Container                                            │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Web-UI (FastAPI + HTML/JS)          Port 8080         │  │
│  │  • Embedding-Modell auswählen                          │  │
│  │  • Git-Repo URL + Branch konfigurieren                 │  │
│  │  • Index-Status & Stats anzeigen                       │  │
│  │  • Manuell Reindex triggern                            │  │
│  │  • Suche testen                                        │  │
│  └────────────────────┬───────────────────────────────────┘  │
│                       │                                      │
│  ┌────────────────────▼───────────────────────────────────┐  │
│  │  MCP Server (FastMCP)                                  │  │
│  │  • stdio Transport (Cursor/Claude)                     │  │
│  │  • SSE Transport  (Netzwerk)         Port 8081         │  │
│  │  Tools: search_docs, search_bugfixes,                  │  │
│  │         write_bugfix_summary, reindex                  │  │
│  └────────────────────┬───────────────────────────────────┘  │
│                       │                                      │
│  ┌────────────────────▼───────────────────────────────────┐  │
│  │  Indexer + Vektor-DB                                   │  │
│  │  • ChromaDB (embedded, persistent)                     │  │
│  │  • Sentence-Transformers (lokal) oder OpenAI           │  │
│  │  • Markdown Chunking (by Heading)                      │  │
│  └────────────────────┬───────────────────────────────────┘  │
│                       │                                      │
│  ┌────────────────────▼───────────────────────────────────┐  │
│  │  /docs (Volume)          /data (Volume)                │  │
│  │  Deine .md Files         Vektor-Index (persistent)     │  │
│  │  (mount oder git clone)                                │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Git Watcher (Background Thread)                       │  │
│  │  • Periodisch git pull                                 │  │
│  │  • Bei Änderungen → auto reindex                       │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## 📦 Projekt-Struktur

```
mcp-docs-vector/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── README.md
├── .env.example
│
├── src/
│   └── mcp_docs_vector/
│       ├── __init__.py
│       ├── config.py           # Konfiguration via ENV + Web-UI
│       ├── indexer.py          # Markdown Chunking + Embedding
│       ├── server.py           # MCP Server + Tools
│       ├── watcher.py          # Git auto-pull + reindex
│       ├── web.py              # FastAPI Web-UI Backend
│       └── templates/
│           └── index.html      # Web-Frontend (Single Page)
│
├── scripts/
│   ├── entrypoint.sh
│   └── reindex.sh
│
├── examples/
│   ├── cursor-mcp.json
│   ├── claude-desktop.json
│   └── sample-docs/
│       ├── architecture.md
│       └── bugfix-log/
│           └── example-fix.md
│
└── tests/
    └── test_indexer.py
```
