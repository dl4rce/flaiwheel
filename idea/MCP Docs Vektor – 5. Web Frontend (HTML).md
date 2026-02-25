# MCP Docs Vektor – Code Teil 5: Web Frontend

## `src/mcp_docs_vector/templates/index.html`

```html
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Docs Vector – Admin</title>
    <style>
        /* ── Reset & Base ──────────────────────────── */
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        :root {
            --bg: #0f1117;
            --bg-card: #1a1d27;
            --bg-input: #252833;
            --border: #2e3347;
            --text: #e4e4e7;
            --text-dim: #8b8fa3;
            --accent: #6366f1;
            --accent-hover: #818cf8;
            --success: #22c55e;
            --warning: #f59e0b;
            --danger: #ef4444;
            --radius: 12px;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            min-height: 100vh;
        }

        /* ── Layout ────────────────────────────────── */
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 24px;
        }

        header {
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 24px 0;
            border-bottom: 1px solid var(--border);
            margin-bottom: 32px;
        }

        header .logo {
            font-size: 32px;
            line-height: 1;
        }

        header h1 {
            font-size: 24px;
            font-weight: 700;
        }

        header .subtitle {
            color: var(--text-dim);
            font-size: 14px;
        }

        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
            margin-bottom: 24px;
        }

        .grid-full {
            grid-column: 1 / -1;
        }

        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
        }

        /* ── Cards ─────────────────────────────────── */
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 24px;
        }

        .card h2 {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .card h2 .icon { font-size: 20px; }

        /* ── Forms ─────────────────────────────────── */
        .form-group {
            margin-bottom: 16px;
        }

        .form-group label {
            display: block;
            font-size: 13px;
            font-weight: 500;
            color: var(--text-dim);
            margin-bottom: 6px;
        }

        .form-group input,
        .form-group select,
        .form-group textarea {
            width: 100%;
            padding: 10px 14px;
            background: var(--bg-input);
            border: 1px solid var(--border);
            border-radius: 8px;
            color: var(--text);
            font-size: 14px;
            font-family: inherit;
            transition: border-color 0.2s;
        }

        .form-group input:focus,
        .form-group select:focus,
        .form-group textarea:focus {
            outline: none;
            border-color: var(--accent);
        }

        .form-group .hint {
            font-size: 12px;
            color: var(--text-dim);
            margin-top: 4px;
        }

        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }

        /* ── Buttons ───────────────────────────────── */
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }

        .btn-primary {
            background: var(--accent);
            color: white;
        }
        .btn-primary:hover { background: var(--accent-hover); }

        .btn-success {
            background: var(--success);
            color: white;
        }

        .btn-danger {
            background: transparent;
            border: 1px solid var(--danger);
            color: var(--danger);
        }
        .btn-danger:hover {
            background: var(--danger);
            color: white;
        }

        .btn-ghost {
            background: var(--bg-input);
            color: var(--text);
            border: 1px solid var(--border);
        }
        .btn-ghost:hover { border-color: var(--accent); }

        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .btn-row {
            display: flex;
            gap: 8px;
            margin-top: 16px;
        }

        /* ── Stats ─────────────────────────────────── */
        .stat-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px;
        }

        .stat-item {
            background: var(--bg-input);
            border-radius: 8px;
            padding: 16px;
            text-align: center;
        }

        .stat-item .value {
            font-size: 28px;
            font-weight: 700;
            color: var(--accent);
        }

        .stat-item .label {
            font-size: 12px;
            color: var(--text-dim);
            margin-top: 4px;
        }

        /* ── Type Badges ───────────────────────────── */
        .type-dist {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 12px;
        }

        .badge {
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 500;
            background: var(--bg-input);
            border: 1px solid var(--border);
        }

        .badge.bugfix { border-color: var(--danger); color: var(--danger); }
        .badge.api { border-color: #3b82f6; color: #3b82f6; }
        .badge.architecture { border-color: var(--warning); color: var(--warning); }
        .badge.best-practice { border-color: var(--success); color: var(--success); }

        /* ── Search Results ─────────────────────────── */
        .search-result {
            background: var(--bg-input);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 12px;
        }

        .search-result .meta {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }

        .search-result .source {
            font-weight: 600;
            font-size: 14px;
            color: var(--accent);
        }

        .search-result .relevance {
            font-size: 13px;
            padding: 2px 10px;
            border-radius: 12px;
            background: var(--accent);
            color: white;
        }

        .search-result .heading {
            font-size: 12px;
            color: var(--text-dim);
            margin-bottom: 8px;
        }

        .search-result .text {
            font-size: 13px;
            color: var(--text);
            white-space: pre-wrap;
            max-height: 200px;
            overflow-y: auto;
            padding: 12px;
            background: var(--bg);
            border-radius: 6px;
            font-family: 'SF Mono', 'Fira Code', monospace;
            line-height: 1.5;
        }

        /* ── Model Cards ───────────────────────────── */
        .model-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .model-option {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px;
            background: var(--bg-input);
            border: 2px solid var(--border);
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .model-option:hover {
            border-color: var(--accent);
        }

        .model-option.selected {
            border-color: var(--accent);
            background: rgba(99, 102, 241, 0.1);
        }

        .model-option input[type="radio"] { display: none; }

        .model-option .model-info {
            flex: 1;
        }

        .model-option .model-name {
            font-weight: 600;
            font-size: 14px;
        }

        .model-option .model-meta {
            font-size: 12px;
            color: var(--text-dim);
            margin-top: 2px;
        }

        .model-option .model-badges {
            display: flex;
            gap: 6px;
        }

        .model-option .model-badges span {
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 10px;
            background: var(--bg-card);
        }

        /* ── Toast / Notifications ─────────────────── */
        .toast-container {
            position: fixed;
            top: 24px;
            right: 24px;
            z-index: 1000;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .toast {
            padding: 12px 20px;
            border-radius: 8px;
            font-size: 14px;
            animation: slideIn 0.3s ease;
            max-width: 400px;
        }

        .toast.success { background: var(--success); color: white; }
        .toast.error { background: var(--danger); color: white; }
        .toast.info { background: var(--accent); color: white; }

        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }

        /* ── Spinner ───────────────────────────────── */
        .spinner {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid rgba(255,255,255,0.3);
            border-top: 2px solid white;
            border-radius: 50%;
            animation: spin 0.6s linear infinite;
        }

        @keyframes spin { to { transform: rotate(360deg); } }

        /* ── Connection Config Card ────────────────── */
        .connection-info {
            background: var(--bg-input);
            border-radius: 8px;
            padding: 16px;
            margin-top: 12px;
        }

        .connection-info code {
            display: block;
            background: var(--bg);
            padding: 12px;
            border-radius: 6px;
            font-size: 13px;
            font-family: 'SF Mono', monospace;
            white-space: pre;
            overflow-x: auto;
            margin-top: 8px;
        }

        .tab-row {
            display: flex;
            gap: 4px;
            margin-bottom: 12px;
        }
        .tab-btn {
            padding: 6px 16px;
            border: none;
            background: transparent;
            color: var(--text-dim);
            cursor: pointer;
            border-radius: 6px;
            font-size: 13px;
        }
        .tab-btn.active {
            background: var(--accent);
            color: white;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <header>
            <span class="logo">🔍</span>
            <div>
                <h1>MCP Docs Vector</h1>
                <div class="subtitle">Vektor-indizierte Dokumentationssuche für AI-Agents</div>
            </div>
        </header>

        <!-- Stats -->
        <div class="card" style="margin-bottom: 24px;">
            <h2><span class="icon">📊</span> Index Status</h2>
            <div class="stat-grid" id="stats-grid">
                <div class="stat-item">
                    <div class="value" id="stat-chunks">–</div>
                    <div class="label">Chunks</div>
                </div>
                <div class="stat-item">
                    <div class="value" id="stat-provider">–</div>
                    <div class="label">Embedding</div>
                </div>
                <div class="stat-item">
                    <div class="value" id="stat-model">–</div>
                    <div class="label">Modell</div>
                </div>
                <div class="stat-item">
                    <div class="value" id="stat-strategy">–</div>
                    <div class="label">Chunking</div>
                </div>
            </div>
            <div class="type-dist" id="type-dist"></div>
            <div class="btn-row">
                <button class="btn btn-primary" onclick="triggerReindex()">
                    🔄 Re-Index
                </button>
                <button class="btn btn-ghost" onclick="triggerGitPull()">
                    📥 Git Pull + Reindex
                </button>
                <button class="btn btn-danger" onclick="clearIndex()">
                    🗑️ Index löschen
                </button>
            </div>
        </div>

        <div class="grid">
            <!-- Embedding Model -->
            <div class="card">
                <h2><span class="icon">🧠</span> Embedding Modell</h2>
                <div class="form-group">
                    <label>Provider</label>
                    <select id="cfg-provider" onchange="toggleProviderFields()">
                        <option value="local">🖥️ Lokal (kostenlos, privat)</option>
                        <option value="openai">☁️ OpenAI (bessere Qualität)</option>
                    </select>
                </div>

                <!-- Lokale Modelle -->
                <div id="local-models-section">
                    <label style="font-size:13px; color:var(--text-dim); margin-bottom:8px; display:block;">
                        Modell wählen
                    </label>
                    <div class="model-list" id="model-list"></div>
                </div>

                <!-- OpenAI Config -->
                <div id="openai-section" style="display:none;">
                    <div class="form-group">
                        <label>OpenAI API Key</label>
                        <input type="password" id="cfg-openai-key" placeholder="sk-...">
                    </div>
                    <div class="form-group">
                        <label>Modell</label>
                        <select id="cfg-openai-model">
                            <option value="text-embedding-3-small">text-embedding-3-small ($0.02/1M tok)</option>
                            <option value="text-embedding-3-large">text-embedding-3-large ($0.13/1M tok)</option>
                            <option value="text-embedding-ada-002">text-embedding-ada-002 (legacy)</option>
                        </select>
                    </div>
                </div>

                <button class="btn btn-primary" onclick="saveEmbeddingConfig()" style="margin-top:12px; width:100%;">
                    💾 Speichern & Neu-Indizieren
                </button>
            </div>

            <!-- Chunking & Docs -->
            <div class="card">
                <h2><span class="icon">✂️</span> Chunking & Dokumentation</h2>
                <div class="form-group">
                    <label>Docs-Pfad (im Container)</label>
                    <input type="text" id="cfg-docs-path" value="/docs">
                    <div class="hint">Volume-Mount oder Git-Clone Ziel</div>
                </div>
                <div class="form-group">
                    <label>Chunking-Strategie</label>
                    <select id="cfg-chunk-strategy">
                        <option value="heading">📑 Heading-basiert (empfohlen für Markdown)</option>
                        <option value="fixed">📏 Feste Größe mit Overlap</option>
                        <option value="hybrid">🔀 Hybrid (Heading + Unterteilen)</option>
                    </select>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Max. Chunk-Größe (Zeichen)</label>
                        <input type="number" id="cfg-chunk-max" value="2000">
                    </div>
                    <div class="form-group">
                        <label>Overlap (Zeichen)</label>
                        <input type="number" id="cfg-chunk-overlap" value="200">
                    </div>
                </div>

                <h2 style="margin-top:20px;"><span class="icon">📡</span> Git Sync</h2>
                <div class="form-group">
                    <label>Git Repo URL (optional)</label>
                    <input type="text" id="cfg-git-url" placeholder="https://github.com/user/docs.git">
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Branch</label>
                        <input type="text" id="cfg-git-branch" value="main">
                    </div>
                    <div class="form-group">
                        <label>Sync Intervall (Sek.)</label>
                        <input type="number" id="cfg-git-interval" value="300">
                        <div class="hint">0 = deaktiviert</div>
                    </div>
                </div>
                <div class="form-group">
                    <label>Git Token (für private Repos)</label>
                    <input type="password" id="cfg-git-token" placeholder="ghp_...">
                </div>
                <button class="btn btn-primary" onclick="saveGeneralConfig()" style="margin-top:8px; width:100%;">
                    💾 Speichern
                </button>
            </div>
        </div>

        <!-- Test-Suche -->
        <div class="card" style="margin-bottom: 24px;">
            <h2><span class="icon">🔎</span> Test-Suche</h2>
            <div style="display:flex; gap:8px;">
                <input type="text" id="search-query" placeholder="z.B. 'Payment retry logic' oder 'Race condition fix'"
                       style="flex:1; padding:12px 16px; background:var(--bg-input); border:1px solid var(--border);
                              border-radius:8px; color:var(--text); font-size:15px;"
                       onkeypress="if(event.key==='Enter') testSearch()">
                <select id="search-type" style="padding:12px; background:var(--bg-input); border:1px solid var(--border);
                              border-radius:8px; color:var(--text);">
                    <option value="">Alle Typen</option>
                    <option value="docs">📄 Docs</option>
                    <option value="bugfix">🐛 Bugfix</option>
                    <option value="best-practice">✅ Best Practice</option>
                    <option value="api">🔌 API</option>
                    <option value="architecture">🏗️ Architektur</option>
                </select>
                <button class="btn btn-primary" onclick="testSearch()">🔍 Suchen</button>
            </div>
            <div id="search-results" style="margin-top:16px;"></div>
        </div>

        <!-- Connection Config -->
        <div class="card">
            <h2><span class="icon">🔗</span> Client-Konfiguration</h2>
            <p style="color:var(--text-dim); font-size:14px; margin-bottom:12px;">
                Kopiere die passende Konfiguration in deinen Client:
            </p>
            <div class="tab-row">
                <button class="tab-btn active" onclick="showTab(this, 'tab-cursor')">Cursor</button>
                <button class="tab-btn" onclick="showTab(this, 'tab-claude')">Claude Desktop</button>
                <button class="tab-btn" onclick="showTab(this, 'tab-docker')">Docker (stdio)</button>
            </div>
            <div id="tab-cursor" class="connection-info">
                <strong>📁 .cursor/mcp.json</strong>
                <code id="config-cursor"></code>
            </div>
            <div id="tab-claude" class="connection-info" style="display:none;">
                <strong>📁 claude_desktop_config.json</strong>
                <code id="config-claude"></code>
            </div>
            <div id="tab-docker" class="connection-info" style="display:none;">
                <strong>📁 .cursor/mcp.json (Docker stdio)</strong>
                <code id="config-docker"></code>
            </div>
        </div>
    </div>

    <div class="toast-container" id="toasts"></div>

    <script>
    // ── State ──────────────────────────────────────
    let currentConfig = {};
    let selectedModel = 'all-MiniLM-L6-v2';

    // ── Init ───────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        loadConfig();
        loadStats();
        setInterval(loadStats, 30000); // Alle 30s Stats updaten
    });

    // ── API Calls ──────────────────────────────────
    async function api(method, path, body = null) {
        const opts = { method, headers: { 'Content-Type': 'application/json' } };
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(`/api${path}`, opts);
        return res.json();
    }

    async function loadConfig() {
        const data = await api('GET', '/config');
        currentConfig = data.config;
        
        // Felder befüllen
        document.getElementById('cfg-provider').value = currentConfig.embedding_provider;
        document.getElementById('cfg-docs-path').value = currentConfig.docs_path;
        document.getElementById('cfg-chunk-strategy').value = currentConfig.chunk_strategy;
        document.getElementById('cfg-chunk-max').value = currentConfig.chunk_max_chars;
        document.getElementById('cfg-chunk-overlap').value = currentConfig.chunk_overlap;
        document.getElementById('cfg-git-url').value = currentConfig.git_repo_url || '';
        document.getElementById('cfg-git-branch').value = currentConfig.git_branch;
        document.getElementById('cfg-git-interval').value = currentConfig.git_sync_interval;

        selectedModel = currentConfig.embedding_model;
        
        // Modell-Liste rendern
        renderModelList(data.available_models);
        toggleProviderFields();
        updateConnectionConfigs();
    }

    async function loadStats() {
        const stats = await api('GET', '/stats');
        
        document.getElementById('stat-chunks').textContent = stats.total_chunks.toLocaleString();
        document.getElementById('stat-provider').textContent = stats.embedding_provider;
        document.getElementById('stat-model').textContent = stats.embedding_model?.split('/').pop() || '–';
        document.getElementById('stat-strategy').textContent = stats.chunk_strategy;
        
        // Typ-Verteilung
        const dist = document.getElementById('type-dist');
        dist.innerHTML = Object.entries(stats.type_distribution || {})
            .map(([type, count]) => 
                `<span class="badge ${type}">${type}: ${count}</span>`
            ).join('');
    }

    // ── Model List Rendering ───────────────────────
    function renderModelList(models) {
        const list = document.getElementById('model-list');
        list.innerHTML = models.map(m => `
            <label class="model-option ${m.id === selectedModel ? 'selected' : ''}" 
                   onclick="selectModel('${m.id}', this)">
                <input type="radio" name="model" value="${m.id}" 
                       ${m.id === selectedModel ? 'checked' : ''}>
                <div class="model-info">
                    <div class="model-name">${m.name}</div>
                    <div class="model-meta">${m.desc}</div>
                </div>
                <div class="model-badges">
                    <span>${m.speed}</span>
                    <span>${m.ram}</span>
                    <span>${m.lang}</span>
                </div>
            </label>
        `).join('');
    }

    function selectModel(modelId, el) {
        selectedModel = modelId;
        document.querySelectorAll('.model-option').forEach(e => e.classList.remove('selected'));
        el.classList.add('selected');
    }

    function toggleProviderFields() {
        const provider = document.getElementById('cfg-provider').value;
        document.getElementById('local-models-section').style.display = 
            provider === 'local' ? 'block' : 'none';
        document.getElementById('openai-section').style.display = 
            provider === 'openai' ? 'block' : 'none';
    }

    // ── Save Config ────────────────────────────────
    async function saveEmbeddingConfig() {
        const provider = document.getElementById('cfg-provider').value;
        const body = { embedding_provider: provider };
        
        if (provider === 'local') {
            body.embedding_model = selectedModel;
        } else {
            body.openai_api_key = document.getElementById('cfg-openai-key').value;
            body.openai_embedding_model = document.getElementById('cfg-openai-model').value;
        }

        toast('info', '⏳ Speichere & indiziere neu...');
        const result = await api('POST', '/config', body);
        
        if (result.model_changed) {
            toast('success', `✅ Modell gewechselt! ${result.reindex_result?.chunks_created || 0} Chunks neu indiziert`);
        } else {
            toast('success', '✅ Gespeichert');
        }
        loadStats();
    }

    async function saveGeneralConfig() {
        const body = {
            docs_path: document.getElementById('cfg-docs-path').value,
            chunk_strategy: document.getElementById('cfg-chunk-strategy').value,
            chunk_max_chars: parseInt(document.getElementById('cfg-chunk-max').value),
            chunk_overlap: parseInt(document.getElementById('cfg-chunk-overlap').value),
            git_repo_url: document.getElementById('cfg-git-url').value,
            git_branch: document.getElementById('cfg-git-branch').value,
            git_sync_interval: parseInt(document.getElementById('cfg-git-interval').value),
            git_token: document.getElementById('cfg-git-token').value,
        };

        const result = await api('POST', '/config', body);
        toast('success', '✅ Konfiguration gespeichert');
        loadStats();
    }

    // ── Actions ────────────────────────────────────
    async function triggerReindex() {
        toast('info', '⏳ Re-Index läuft...');
        const result = await api('POST', '/reindex');
        toast('success', `✅ ${result.chunks_created} Chunks indiziert aus ${result.files_indexed} Dateien`);
        loadStats();
    }

    async function triggerGitPull() {
        toast('info', '⏳ Git Pull...');
        const result = await api('POST', '/git/pull');
        if (result.changes_detected) {
            toast('success', `✅ Neue Commits! ${result.reindex_result?.chunks_created || 0} Chunks reindiziert`);
        } else {
            toast('info', 'ℹ️ Keine Änderungen im Git-Repo');
        }
        loadStats();
    }

    async function clearIndex() {
        if (!confirm('Index wirklich komplett löschen?')) return;
        await api('POST', '/clear');
        toast('success', '🗑️ Index gelöscht');
        loadStats();
    }

    // ── Test Search ────────────────────────────────
    async function testSearch() {
        const query = document.getElementById('search-query').value;
        if (!query) return;

        const typeFilter = document.getElementById('search-type').value || null;
        const container = document.getElementById('search-results');
        container.innerHTML = '<div style="text-align:center; padding:20px;"><span class="spinner"></span> Suche...</div>';

        const data = await api('POST', '/search', { query, top_k: 5, type_filter: typeFilter });

        if (!data.results || data.results.length === 0) {
            container.innerHTML = '<p style="color:var(--text-dim); padding:16px;">Keine Ergebnisse gefunden.</p>';
            return;
        }

        container.innerHTML = data.results.map(r => `
            <div class="search-result">
                <div class="meta">
                    <span class="source">📄 ${r.source} → ${r.heading}</span>
                    <span class="relevance">${r.relevance}%</span>
                </div>
                <div class="heading">
                    <span class="badge ${r.type}">${r.type}</span>
                    ${r.char_count} Zeichen
                </div>
                <div class="text">${escapeHtml(r.text.substring(0, 500))}${r.text.length > 500 ? '...' : ''}</div>
            </div>
        `).join('');
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ── Connection Configs ─────────────────────────
    function updateConnectionConfigs() {
        const host = window.location.hostname;
        const ssePort = currentConfig.sse_port || 8081;

        document.getElementById('config-cursor').textContent = JSON.stringify({
            "mcpServers": {
                "project-docs": {
                    "url": `http://${host}:${ssePort}/sse`
                }
            }
        }, null, 2);

        document.getElementById('config-claude').textContent = JSON.stringify({
            "mcpServers": {
                "project-docs": {
                    "url": `http://${host}:${ssePort}/sse`
                }
            }
        }, null, 2);

        document.getElementById('config-docker').textContent = JSON.stringify({
            "mcpServers": {
                "project-docs": {
                    "command": "docker",
                    "args": [
                        "run", "-i", "--rm",
                        "-v", "${workspaceFolder}/docs:/docs:ro",
                        "-v", "mcp-vectorstore:/data",
                        "mcp-docs-vector:latest"
                    ]
                }
            }
        }, null, 2);
    }

    // ── Tabs ───────────────────────────────────────
    function showTab(btn, tabId) {
        btn.parentElement.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        
        ['tab-cursor', 'tab-claude', 'tab-docker'].forEach(id => {
            document.getElementById(id).style.display = id === tabId ? 'block' : 'none';
        });
    }

    // ── Toast Notifications ────────────────────────
    function toast(type, message) {
        const container = document.getElementById('toasts');
        const el = document.createElement('div');
        el.className = `toast ${type}`;
        el.textContent = message;
        container.appendChild(el);
        setTimeout(() => el.remove(), 4000);
    }
    </script>
</body>
</html>
```