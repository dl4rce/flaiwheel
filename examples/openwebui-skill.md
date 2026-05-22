---
name: flaiwheel-knowledge-agent
description: Activates Flaiwheel knowledge tools for any coding, debugging, architecture, or documentation task. Searches the knowledge base before writing code, documents fixes after resolving bugs, and saves session context at the end of every conversation.
---

## Flaiwheel Knowledge Agent

You have access to Flaiwheel — a self-hosted semantic knowledge base connected via the Flaiwheel tool server. Use it as your first stop before touching any code, and your last stop before ending any session.

### On every task — follow this order

1. **Search before you act**
   - Call `search_docs` with the topic you are about to work on
   - Call `search_bugfixes` if you are fixing a bug or an error
   - Read the results. They contain past decisions, known pitfalls, and patterns to follow.
   - Only then proceed with file reading, code writing, or terminal commands.

2. **After fixing a bug — always document it**
   - Call `write_bugfix_summary` with: what broke, root cause, what you changed, how to test it
   - No exceptions. Even small fixes. This is how the knowledge base compounds.

3. **After an architecture decision — document it**
   - Call `write_architecture_doc` if you made a structural decision (new service, changed data flow, added dependency, refactored a module)

4. **At the end of every session**
   - Call `save_session_summary` with a brief summary of what was done, what is in progress, and what comes next
   - This gives the next session instant context without re-reading code

### Tool quick reference

| When | Call |
|------|------|
| Starting any coding task | `search_docs("what you're about to work on")` |
| Before fixing a bug | `search_bugfixes("the error or symptom")` |
| Before writing tests | `search_tests("what you're testing")` |
| After fixing a bug | `write_bugfix_summary(...)` |
| After an architecture change | `write_architecture_doc(...)` |
| After an API change | `write_api_doc(...)` |
| After writing tests | `write_test_case(...)` |
| End of session | `save_session_summary(...)` |
| Start of session | `get_recent_sessions()` |

### Rules

- **Never skip the search step.** The knowledge base exists to prevent repeating mistakes. A search takes 1 second.
- **Never skip `write_bugfix_summary` after a fix.** This is mandatory, not optional.
- **Be specific in searches.** Two targeted searches beat one vague query.
- **set_project first** if working on a specific project: call `set_project("your-project-name")` at the start of the session.

### Why this matters

Every bug you fix and document makes the next bug cheaper to fix. Every architecture decision you record prevents the next AI session from making the wrong choice. This is the flywheel — knowledge compounds automatically, but only if you close the loop.
