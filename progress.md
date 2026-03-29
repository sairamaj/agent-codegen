# Codegen implementation progress

Living log of what is implemented in this repo versus [docs/codegen_stories.md](docs/codegen_stories.md). **Append a new dated section** whenever you complete stories or epics.

---

## 2026-03-29 — Epic P1-E1: Patches and edits

**Stories**

| Story | Status | Notes |
|-------|--------|--------|
| P1-01 | Done | **`apply_patch`** tool: structured `files[]` with `hunks` (`old_text` / `new_text`), workspace checks via `resolve_under_workspace`, per-file JSON results with `sha256` / errors; wired in `tools_readonly.execute_tool`; CLI system prompt mentions it. Module: `codegen.tools_patch`. |
| P1-02 | Done | **`HUNK_MISMATCH`** / **`AMBIGUOUS_MATCH`**: `hunk_index`, `line_count`, line/column hints, `context_preview`, `read_file` hints; multiline “first line matches” → `first_line_found_at`. Empty `old_text` rejected on existing files. |
| P1-03 | Done | **Partial multi-file** documented in [docs/codegen_requirements.md](docs/codegen_requirements.md) §4.5.1 and [AGENTS.md](AGENTS.md); not atomic across files; failures do not skip later files; `partial` / `ok` semantics; tests in `test_tools_patch.py`. |

**Code / tests**

- `codegen.tools_patch`, `codegen.tools_readonly` (tool def + dispatch), `tests/test_tools_patch.py`.
- **UX / connectivity (same window):** clearer OpenAI connection/timeout messages; `codegen.http_env` validates `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY` must use a full URL; `OPENAI_BASE_URL` must include `http://` or `https://` when set (`codegen.config`).

---

## 2026-03-29 — Epic P0-E4: Colored console UX

**Stories**

| Story | Status | Notes |
|-------|--------|--------|
| P0-13 | Done | Four semantic styles in `CODEGEN_THEME`: **user** (bold cyan), **assistant** (green), **tool** (magenta), **error** (bold red); **warn** / **muted** for limits and labels. User task echoed once at start of `run` (`user` + preview). |
| P0-14 | Done | Colors off when stdout is not a TTY or `NO_COLOR` is set; `make_console(file=...)` forces plain output (tests / capture). |
| P0-15 | Done | Before each tool run: `› name` + redacted, truncated arg summary (`redact_tool_args_display`: `sk-…`, `Bearer …`, JSON `api_key` / `token` / `password` / `secret` / `authorization`). |

**Code / tests**

- `codegen.console`: theme, `redact_secrets_in_text`, `format_user_task_preview`, `TOOL_ARGS_DISPLAY_MAX_LEN`.
- `codegen.agent_loop`: user header line; tool lines use redacted summaries.
- `tests/test_console.py`, extended `tests/test_agent_loop.py`.

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

## 2026-03-29 — Epic P0-E5: Observability (minimal)

**Stories**

| Story | Status | Notes |
|-------|--------|--------|
| P0-16 | Done | Optional **JSON lines** to **stderr** or a **file** (`structured_log` in TOML / `CODEGEN_STRUCTURED_LOG`). Each line includes **`trace_id`** and **`session_id`** (same UUID for a single `run`). Events: `run.start`, `model.iteration`, `tool.start` (sanitized args), `tool.complete` (duration_ms, outcome / error_code), `run.end`. |

**Code / tests**

- `codegen.observability`: `StructuredLogger`, `open_structured_logger`, `normalize_structured_log_destination`, `sanitize_args_for_log`, `tool_result_outcome`.
- `codegen.config`: `structured_log`; `redacted_summary` shows `stderr` or `file:<basename>`.
- `codegen.agent_loop`: optional `structured_logger` on `run_agent_task`.
- `codegen.cli` `run`: opens sink; `info` shows `structured_log`.
- `tests/test_observability.py`.

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
