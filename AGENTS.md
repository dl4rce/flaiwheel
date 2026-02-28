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
- Architecture decision → `write_architecture_doc()` **(MUST include Mermaid.js diagram)**
- API change → `write_api_doc()`
- New coding pattern → `write_best_practice()`
- Deployment/infra change → `write_setup_doc()`
- Tests written/modified → `write_test_case()` (Use Gherkin/BDD flow specs when applicable)

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
