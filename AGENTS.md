# Codegen workspace — agent context

This file is **project ground truth** for humans and coding agents. Keep it updated when scope or technical decisions change.

## What this project is

- **Codegen** is a **CLI coding agent**: natural-language tasks against a **workspace directory**, using **tools** (read, search, edit, shell, …) in a **multi-step loop**, similar in *capabilities* to Cursor’s agent—not a full IDE.
- **Deliverables are phased** (read-only → edits → hardening → extensibility). Implementation follows the stories backlog, not ad-hoc scope creep.

## Authoritative documents

| Document | Role |
|----------|------|
| [docs/codegen_requirements.md](docs/codegen_requirements.md) | Requirements: FR/NFR IDs, architecture, phases, acceptance criteria. |
| [docs/codegen_stories.md](docs/codegen_stories.md) | User stories and epic order; maps stories to requirements. |

When adding features, **trace changes** to requirement IDs where possible. When adding or changing stories, **keep phase labels and acceptance criteria** aligned with `codegen_requirements.md`.

## Fixed product decisions (this workspace)

| Topic | Decision |
|-------|----------|
| **Interface** | **CLI only** (no IDE plugin or web UI in current scope). |
| **LLM** | **OpenAI** (API key via env/config; never log or print secrets). |
| **Console UX** | **Colorized TTY** output in the spirit of Claude Code / modern CLI agents; respect `NO_COLOR` and non-TTY (no ANSI). |
| **Learning goal** | Prefer **transparent code** over heavy frameworks: implement the agent loop with the **OpenAI SDK** and an **explicit** message ↔ tool-call ↔ execute ↔ repeat cycle. **Do not** introduce LangGraph/LangChain as the default stack unless the user explicitly asks or a story requires it (e.g. advanced persistence later). |
| **Platform** | Windows, macOS, and Linux must remain workable (paths, subprocess, line endings per requirements). |

## Implementation stance (for agents writing code)

1. **Agent loop** — The core behavior is: build messages → model returns text and/or `tool_calls` → run registered tools → append tool results → repeat until done or limits. This should remain **readable** in one place (or a small module set), not scattered across framework magic.
2. **Tools** — Each tool: clear schema (OpenAI function format), workspace-root boundary checks, truncation for large output, structured errors back to the model.
3. **Safety** — Plan vs execute modes, command policy, and approvals are **required** by Phase 1 stories; do not skip because the CLI is “just local.”
4. **Observability** — Structured logs / trace IDs support debugging; align with NFR-OBS in requirements.

## Phases (short)

- **Phase 0** — Read-only tools + OpenAI loop + streaming + colored console + config.
- **Phase 1** — Patches, bounded terminal, policy, plan/execute, approvals, audit trace.
- **Phase 2** — Verification hooks, `.gitignore`-aware search, session persistence/compaction, optional `web_fetch`.
- **Phase 3** — MCP, policy packs, optional quotas.

Details and story IDs: `docs/codegen_stories.md`.

## Conventions for story and doc work

- New stories: include **As a / I want / so that**, **acceptance criteria**, **phase**, and **maps to** (FR/NFR or section) like existing stories.
- Prefer **small, vertical slices** per story (one epic at a time when implementing).
- Do not edit historical requirement versions without adding a row to **Document control** in `codegen_requirements.md` if meaning changes.

## Repository layout (expected as code lands)

- `docs/` — Requirements and stories (specs).
- `src/codegen/` — Python package: CLI (`codegen.cli`), config, workspace resolution, project rules bootstrap.
- `pyproject.toml` — Package metadata; console script **`codegen`** (also `python -m codegen`).

---

*Last updated: 2026-03-28 — P0-E1 CLI bootstrap; `src/codegen` layout.*
