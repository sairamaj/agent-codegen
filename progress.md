# Codegen implementation progress

Living log of what is implemented in this repo versus [docs/codegen_stories.md](docs/codegen_stories.md). **Append a new dated section** whenever you complete stories or epics.

---

## 2026-03-29 — Epic P0-E2: OpenAI and agent loop

**Stories**

| Story | Status | Notes |
|-------|--------|--------|
| P0-05 | Done | OpenAI Chat Completions + `tools=` using `read_file`, `list_dir`, `grep`; explicit loop until final reply or limits. |
| P0-06 | Done | `max_iterations` (default 25) and `max_wall_clock_seconds` (default 600) from config; clear stop messages when exceeded. |
| P0-07 | Done | Assistant text streamed to the console (incremental deltas). |
| P0-08 | Done | Tool results are JSON; failures use `{"ok": false, "error": {"code", "message"}}` (e.g. bad path → `PATH_OUTSIDE_WORKSPACE`). |

**Code / UX**

- New: `codegen run "<task>"` — requires `OPENAI_API_KEY`; uses workspace from `-w` / cwd; injects `AGENTS.md` when present (via existing bootstrap).
- New modules: `codegen.agent_loop`, `codegen.tools_readonly`, `codegen.workspace_paths`.
- Dependency: `openai` (Python SDK).
- HTTP timeout per request: `min(120, max(30, max_wall_clock_seconds))` seconds.

**Tests**

- Unit tests for path boundary, tools, and mocked agent loop (`tests/test_workspace_paths.py`, `tests/test_tools_readonly.py`, `tests/test_agent_loop.py`).

---

## Earlier — Epic P0-E1: CLI bootstrap and configuration

**Stories**

| Story | Status | Notes |
|-------|--------|--------|
| P0-01 | Done | `codegen` Typer app, `--help`, `--version`. |
| P0-02 | Done | `--workspace` / `-w`; `codegen.workspace.resolve_workspace`. |
| P0-03 | Done | TOML + env config; `codegen.config.load_config`; secrets redacted in `codegen info`. |
| P0-04 | Done | Project rules from `AGENTS.md` (configurable); loaded in bootstrap / shown in `codegen info`. |

---

## Not started yet (Phase 0 remainder)

- **P0-E4** — Colored console UX (four semantic styles, compact tool summaries, etc.).
- **P0-E5** — Structured logging / trace IDs (P0-16).

---

## 2026-03-29 — CLI: workspace on `run` / `info`

Subcommands **`run`** and **`info`** accept **`--workspace` / `-w`** and **`--config` / `-c`** after the subcommand name (in addition to global `codegen -w DIR run …`). So `codegen run "task" -w ..\kb` works.

---

## 2026-03-29 — Epic P0-E3: Read-only tools

**Stories**

| Story | Status | Notes |
|-------|--------|--------|
| P0-09 | Done | `read_file`: line slice (`offset`/`limit`, default 500 lines), byte cap (`max_bytes`, default 256 KiB) with `truncated` / `truncated_bytes`, `file_size_bytes`, `bytes_read`; reads only up to `max_bytes` from disk. |
| P0-10 | Done | `list_dir`: `depth` and `max_entries` (defaults 1 and 200); `truncated` when cap hit. |
| P0-11 | Done | `grep`: Python regex, scoped path, `max_matches` (default 50), `truncated`; traversal skips paths whose resolved target leaves the workspace. |
| P0-12 | Done | `resolve_under_workspace` unchanged; `resolved_path_is_under_workspace` for traversal; `list_dir` / `grep` do not follow symlink escapes; tests for `..`, absolute outside, symlink-to-outside (grep/list/read). |

**Code**

- `codegen.workspace_paths`: `resolved_path_is_under_workspace`.
- `codegen.tools_readonly`: byte-limited reads, symlink-safe `list_dir` recurse and `grep` file scan.

**Tests**

- Extended `tests/test_tools_readonly.py` and `tests/test_workspace_paths.py` (caps, regex error, symlink cases; symlink tests skip when OS cannot create links).

---

## How to update this file

After implementing stories, add a `## YYYY-MM-DD — …` section with a short table and file pointers so the next session can see what landed without scanning the tree.
