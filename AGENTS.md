# AI Agent Instructions

---

## Flaiwheel — Project Knowledge Base (MCP) — YOUR FIRST STOP

This project has a **semantic knowledge base** powered by Flaiwheel.
MCP endpoint: `http://localhost:8081/sse`

### Knowledge Repo

The knowledge base lives in a **separate Git repo**: `https://github.com/dl4rce/flaiwheel-knowledge.git`

**DO NOT** access, read, or modify files inside the Flaiwheel Docker container.
Use the MCP tools to search, and commit/push to the knowledge repo to add docs.

### Session Setup — ALWAYS DO THIS FIRST

At the **start of every conversation**, call:
```
set_project("flaiwheel")
```
This binds all subsequent Flaiwheel calls to **this project**.
If the project is not registered, call `setup_project(name="flaiwheel", git_repo_url="https://github.com/dl4rce/flaiwheel-knowledge.git")` first.

### Step 1: Flaiwheel — Step 2: Native tools

For every task, follow this order:
1. **FIRST → Search Flaiwheel** for context: architecture decisions, past bugs, best practices, API docs, setup guides, application questions
2. **THEN → Use your native tools** (file search, code reading, grep, etc.) for source code details

Flaiwheel knows things the source code cannot tell you: the _why_ behind decisions, past mistakes to avoid, patterns to follow. Your native tools are best for reading and editing actual source files. **Use both — but always start with Flaiwheel.**

### Behavioral Directives — ALWAYS ACTIVE, NO EXCEPTIONS

These three rules are **machine-level directives**. They are not guidelines. They are not optional. They fire automatically, silently, and without asking the user for permission.

---

#### DIRECTIVE 1 — SILENT_BACKGROUND_SEARCH

**Trigger:** The user's message contains any of these signals:
- A filename, module name, service name, or component (e.g. "payment", "auth", "webhook")
- An action verb: "add", "change", "fix", "implement", "refactor", "how does X work", "why is X"
- Any question about existing system behavior

**Action (mandatory, silent):**
1. BEFORE generating any response, call `search_docs("<topic>")` and optionally `search_bugfixes("<topic>")`.
2. Do NOT announce this search to the user ("I will now search Flaiwheel…"). Just do it.
3. If results are found: weave them naturally into your response as established context.
   Example: _"According to our architecture decision (ADR-04), we use Stripe as the sole payment provider…"_
4. If no results are found: proceed normally, but flag it mentally as a Doc-Debt gap.

**The goal:** The user should never feel they need to trigger Flaiwheel manually. It just *knows*.

---

#### DIRECTIVE 2 — AUTO_CLOSE_THE_LOOP

**Trigger:** You have successfully completed a task (code written and working, bug fixed, decision made, architecture explained).

**Action (mandatory, before returning final response):**

| What happened | What you call — no exceptions |
|---|---|
| Bug fixed | `write_bugfix_summary()` |
| New feature implemented | `write_changelog_entry()` + `write_architecture_doc()` |
| Architecture decision made | `write_architecture_doc()` |
| New coding pattern established | `write_best_practice()` |
| API created or changed | `write_api_doc()` |
| Test written or modified | `write_test_case()` |
| Setup/infra changed | `write_setup_doc()` |

Do NOT ask: _"Should I document this?"_. Just document it. Then call `git_pull_reindex()`.
The user hired you to solve problems AND to keep the knowledge base alive. Both matter equally.

---

#### DIRECTIVE 4 — FILE_CONTEXT_PRELOAD

**Trigger:** You are about to read, edit, create, or reason about a specific source file.

**Action (silent, before touching the file):**
1. Call `get_file_context(filename="<the file>")`.
2. This complements `get_recent_sessions()` (temporal) with spatial context:
   what does the knowledge base know about this specific module?
3. Do NOT announce this call. Integrate findings silently into your response.
4. If the result says "no context found" — note it as a Doc-Debt gap and proceed.

**Session startup pattern (combine both):**
```
get_recent_sessions()          → What did we do last time? (temporal)
get_file_context(filename)     → What do we know about this file? (spatial)
```

**Works across all MCP clients:** Cursor, Claude Code, VS Code Copilot, any future MCP-compatible tool.

---

#### DIRECTIVE 3 — REUSE_BEFORE_RECREATE

**Trigger:** You are about to write new code, a new pattern, or a new document.

**Action:**
1. FIRST call `search_docs("<what you're about to create>")`.
2. Evaluate the relevance of results:
   - **Relevance > 75%** → Reference and reuse the existing doc. Do not recreate it.
   - **Relevance 40–75%** → Extend the existing doc with the new knowledge. Call the matching `write_*()` tool to update it.
   - **Relevance < 40%** → Create new. Document it with `write_*()` immediately after.
3. Never silently duplicate knowledge that already exists in the knowledge base.

**The goal:** The knowledge base grows without redundancy. Every piece of knowledge lives exactly once.

---

### Mandatory workflow

1. **FIRST: Search Flaiwheel** — `search_docs("what you're working on")`, `search_bugfixes("the problem")`, `search_by_type("query", "architecture")` BEFORE touching code
2. **THEN: Use native tools** to read/edit source code with the knowledge you found
3. **Document knowledge using structured write tools** (they enforce structure, auto-push, auto-index):
   - `write_bugfix_summary()` — after every bugfix (**mandatory**)
   - `write_architecture_doc()`, `write_api_doc()`, `write_best_practice()`, `write_setup_doc()`, `write_changelog_entry()`
   - For freeform docs: `validate_doc(content, category)` before committing
4. **Before writing/modifying tests:**
   - `search_tests("what you're testing")` — check existing test cases and coverage FIRST
   - After writing tests: `write_test_case()` — document scenario, steps, expected result, status, tags
5. **AFTER committing new/updated docs to the knowledge repo:** call `git_pull_reindex()`
6. **Periodically:** `check_knowledge_quality()` and fix issues
7. **"This is the Way"** — for messy repos, the user says this phrase (or "42"):
   - **New project:** scan local project for docs → `classify_documents(files=JSON)` → review plan → `write_*` tools → `reindex()`
   - **Existing knowledge repo:** `analyze_knowledge_repo()` → review plan → `execute_cleanup(actions)` → `reindex()`

**Important:** Files with critical quality issues are skipped during indexing. Flaiwheel NEVER deletes or modifies user files.

### Documentation Triggers

**MANDATORY:** After fixing ANY bug → `write_bugfix_summary()` (no exceptions)

**RECOMMENDED:**
- Architecture decision → `write_architecture_doc()`
- API change → `write_api_doc()`
- New coding pattern → `write_best_practice()`
- Deployment/infra change → `write_setup_doc()`
- Tests written/modified → `write_test_case()`

**SESSION CONTINUITY:**
- At START of session → `get_recent_sessions()` (see what was done before)
- At END of session → `save_session_summary()` (preserve context for next time)

### What the knowledge base contains

| Category | Search with | What you'll find |
|----------|-------------|-----------------|
| `architecture` | `search_by_type("q", "architecture")` | System design, trade-offs, decisions |
| `api` | `search_by_type("q", "api")` | Endpoints, contracts, schemas |
| `bugfix` | `search_bugfixes("q")` | Root causes, solutions, lessons learned |
| `best-practice` | `search_by_type("q", "best-practice")` | Coding standards, patterns |
| `setup` | `search_by_type("q", "setup")` | Deployment, infrastructure, CI/CD |
| `changelog` | `search_by_type("q", "changelog")` | Release notes, breaking changes |
| `test` | `search_tests("q")` | Test cases, scenarios, regression patterns |
| _everything_ | `search_docs("q")` | Semantic search across all docs |

### Updating Flaiwheel

To update Flaiwheel, tell the user to run this in their project directory:
```bash
curl -sSL https://raw.githubusercontent.com/dl4rce/flaiwheel/main/scripts/install.sh | bash
```
You can also call `check_update()` to check if a newer version is available.

### All tools

All tools accept an optional `project` parameter as explicit override.

| Tool | Purpose |
|------|---------|
| `set_project(name)` | **Bind session to a project** (call first!) |
| `setup_project(name, git_repo_url, ...)` | Register + index a new project (auto-binds) |
| `get_active_project()` | Show which project is currently bound |
| `list_projects()` | List all registered projects with stats |
| `search_docs(query, top_k)` | Semantic search across all documentation |
| `search_bugfixes(query, top_k)` | Search bugfix summaries only |
| `search_by_type(query, doc_type, top_k)` | Filter by type |
| `write_bugfix_summary(...)` | Document a bugfix (auto-pushed + reindexed) |
| `write_architecture_doc(...)` | Document architecture decisions |
| `write_api_doc(...)` | Document API endpoints |
| `write_best_practice(...)` | Document coding standards |
| `write_setup_doc(...)` | Document setup/deployment |
| `write_changelog_entry(...)` | Document release notes |
| `write_test_case(...)` | Document test cases (auto-pushed + reindexed) |
| `search_tests(query, top_k)` | Search test cases for coverage and patterns |
| `validate_doc(content, category)` | Validate markdown before committing |
| `git_pull_reindex()` | Pull latest from knowledge repo + re-index |
| `get_index_stats()` | Index statistics |
| `reindex()` | Re-index all documentation |
| `check_knowledge_quality()` | Validate knowledge base |
| `check_update()` | Check for newer Flaiwheel version |
| `analyze_knowledge_repo()` | Analyse knowledge repo structure and quality |
| `execute_cleanup(actions)` | Execute approved cleanup actions (never deletes files) |
| `classify_documents(files)` | **"This is the Way"** — classify project docs for knowledge migration |
| `save_session_summary(...)` | Save session context for continuity (call at end of session) |
| `get_recent_sessions(limit)` | Retrieve recent session summaries (call at start of session) |
