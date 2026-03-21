---
name: flaiwheel
description: >
  Flaiwheel knowledge base workflow. Use this skill automatically at the START
  of every coding session to restore context, BEFORE writing or modifying any
  code to search for relevant docs and past decisions, and AFTER fixing bugs or
  making architectural decisions to document learnings. Trigger whenever the
  user starts working on a project, opens or edits a file, fixes a bug, makes
  an API change, or ends a session. Also trigger when the user says "document
  this", "save this decision", "what did we do last time", "knowledge base",
  or asks about past bugs or architecture.
---

# Flaiwheel Knowledge Base Workflow

Flaiwheel is a vector-indexed knowledge base accessible via MCP tools. Its
purpose is institutional memory: decisions, bugs, architecture, and session
context are captured and retrieved automatically so nothing is lost between
sessions.

## Session Start — always do this first

When a coding session begins, restore context before touching any code:

```
1. get_active_project()          → confirm correct project is bound
2. get_recent_sessions(limit=3)  → read what was done last time
3. set_project(name)             → if project is not yet bound
```

If there are open questions from the last session, surface them to the user
before proceeding.

## Before Writing or Changing Code

Search the knowledge base first — this prevents re-solving solved problems:

```
search_docs(query="<what you're about to implement>")
get_file_context(filename="<file you're editing>")
```

Also search bugfixes when debugging:

```
search_bugfixes(query="<description of the current problem>")
```

Use the results to inform your approach. If relevant architecture decisions or
past bugs exist, mention them to the user.

## After Fixing a Bug — mandatory

Call `write_bugfix_summary` immediately after every bug fix, without waiting
for the user to ask. This is the most important habit because bugs are often
forgotten once fixed, yet they recur.

Required fields:
- **title**: Short, searchable description ("Payment webhook fails on retry")
- **root_cause**: The actual technical cause, not the symptom
- **solution**: What code changed and why
- **lesson_learned**: What should be done differently next time
- **affected_files**: Comma-separated file paths
- **tags**: Categories for future search (e.g. "auth,race-condition,critical")

## After Architectural Decisions

When a significant design choice is made, call `write_architecture_doc`:

- **title**: What system or component was designed
- **overview**: High-level description
- **decisions**: What was chosen and why
- **trade_offs**: What was considered and rejected

## After API Changes

When an endpoint is created or changed, call `write_api_doc` with the endpoint
path, HTTP method, request/response schema, and an example.

## After Best Practices Are Established

When a coding standard or pattern is agreed upon, call `write_best_practice`:

- **context**: When/where this applies
- **rule**: The actual pattern to follow
- **rationale**: Why it matters, what it prevents

## Session End — always do this last

Before closing a session, call `save_session_summary`:

```
save_session_summary(
  summary="1-3 sentences of what was accomplished",
  decisions="key decisions made, comma-separated",
  open_questions="unresolved items or next steps",
  files_modified="files changed, comma-separated"
)
```

This ensures the next session (or a different AI) can pick up exactly where
this one left off.

## Quick Reference

| When | Tool |
|------|------|
| Session starts | `get_recent_sessions` + `get_active_project` |
| Before coding | `search_docs` + `get_file_context` |
| Debugging | `search_bugfixes` |
| Bug fixed | `write_bugfix_summary` ← most important |
| Design decision | `write_architecture_doc` |
| API change | `write_api_doc` |
| Pattern agreed | `write_best_practice` |
| Session ends | `save_session_summary` |

## Notes

- All write tools index immediately — no separate reindex needed
- `validate_doc` can be called before writing to check structure
- If the project is not yet registered, use `setup_project` first
- `reindex(force=True)` only needed after large manual changes to the repo
