# Codegen

## What and why

**Codegen** is a small **CLI coding agent**: you describe a task in natural language, and an **OpenAI** model drives a **transparent tool loop** (read files, search, apply patches, run shell commands—depending on mode and configuration) inside a **fixed workspace root**. It is built as an **educational** project: the goal is to **see how agent-style tools, streaming, policy, and sessions fit together**, not to replace a full IDE.

- **What it does:** `codegen run "<task>"` sends your task to the model; the agent may call tools repeatedly until it finishes or hits limits.
- **Why it exists:** To learn how **message → tool calls → execution → repeat** works with the official SDK, clear modules, and phased features (read-only exploration vs edits, approvals, audit logs, etc.).

Details: [docs/codegen_requirements.md](docs/codegen_requirements.md), [docs/codegen_stories.md](docs/codegen_stories.md).

**Requirements:** Python **3.11+**. An **OpenAI API key** (`OPENAI_API_KEY`) is required for `run`.

---

## Examples

Replace paths and tasks with your own. Global options (`-w`, `-c`, `-v`) can appear **before** the subcommand **or** on `info` / `run` (see `codegen run --help`).

### Discover commands

```bash
codegen --help
codegen --version
codegen run --help
codegen info --help
```

### Inspect workspace and config (no API calls)

```bash
codegen info
codegen -w . info
codegen -w /path/to/project info
codegen -v info
```

### One-shot tasks (execute mode is default: patches + terminal allowed per policy)

```bash
codegen run "Summarize what src/ does in three bullet points."
codegen run "Find where the agent loop is implemented and list the file paths."
codegen run "Add a one-line docstring to the main CLI entry if it's missing."
codegen -w /path/to/repo run "List top-level files in the workspace."
```

### Plan-only (read-only tools: explore without edits or shell)

```bash
codegen run --mode plan "Map the module layout under src/ and suggest where tests should live."
codegen run --mode plan "What does the config module load from disk?"
```

### Choose workspace explicitly

```bash
codegen -w . run "Run the test suite and report pass/fail."
codegen run "Show README.md first 20 lines." -w .
```

### Interactive session (multiple turns; type `exit`, `quit`, or `:q` to leave)

```bash
codegen run -i
codegen run -i -w /path/to/project
codegen run --interactive --mode plan
```

### Auto-approve shell prompts (non-interactive environments)

```bash
codegen run --yes "Run pytest and show the last 30 lines of output."
```

### Session persistence (conversation + context stored for follow-up runs)

```bash
codegen run --session my-feature "Remember: we're adding CSV export."
codegen run --session my-feature "Continue: wire the CLI flag next."
```

### Verbosity

```bash
codegen -v run "Trace which tools run; keep the task small."
codegen -vv run "Even more detail for debugging."
```

### Web fetch (optional `web_fetch` tool)

**Off by default** so the agent does not open network connections unless you opt in. When enabled, the model can call **`web_fetch`** for bounded **HTTP GET** requests to **public** `http://` or `https://` URLs (size and timeout limits apply; localhost and private IPs are rejected).

**1. Enable** in the workspace **`codegen.toml`** or **`.codegen.toml`**:

```toml
web_fetch_enabled = true
# optional (defaults are usually enough):
# web_fetch_max_bytes = 262144
# web_fetch_timeout_seconds = 30
```

**Or** set the environment variable (e.g. in the shell or `.env`):

```bash
export CODEGEN_WEB_FETCH_ENABLED=true
# optional:
# export CODEGEN_WEB_FETCH_MAX_BYTES=524288
# export CODEGEN_WEB_FETCH_TIMEOUT_SECONDS=45
```

**2. Confirm** it is on:

```bash
codegen -w . info
```

You should see `web_fetch: on (...)` in the summary.

**3. Run** tasks that ask the agent to read public pages (it will use `web_fetch` when the task needs the web):

```bash
codegen run --mode plan "Fetch https://example.com and report the page title."
codegen run "Summarize the first screen of text from https://docs.python.org/3/tutorial/ for a beginner."
codegen run "What version string appears on the PyPI JSON for the 'httpx' project? Use https://pypi.org/pypi/httpx/json"
```

### Module invocation (same as the `codegen` script after install)

```bash
python -m codegen --help
python -m codegen -w . info
python -m codegen run "Quick smoke: print workspace root via a tool."
```

---

## How to run

### 1. Clone and enter the repo

```bash
cd /path/to/codegen
```

Windows (PowerShell):

```powershell
cd c:\path\to\codegen
```

### 2. Virtual environment (recommended)

```bash
python -m venv .venv
```

Activate:

| Shell | Command |
|-------|---------|
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows cmd | `.venv\Scripts\activate.bat` |
| macOS / Linux | `source .venv/bin/activate` |

### 3. Install

```bash
python -m pip install -e .
```

Development (includes pytest):

```bash
python -m pip install -e ".[dev]"
```

### 4. Configure API access

Set `OPENAI_API_KEY` in the environment, or use a `.env` file (see [.env.example](.env.example)) in the workspace or a parent directory. The CLI never prints the key.

Optional: `codegen.toml` or `.codegen.toml` in the workspace, or `--config /path/to.toml`. See `codegen info` after setup.

### 5. Run the agent

```bash
codegen -w /path/to/your/project info
codegen -w /path/to/your/project run "Your task here."
```

---

## Tests

After `python -m pip install -e ".[dev]"`:

```bash
python -m pytest
```

---

## Maintaining this README

When behavior or flags change, update **Examples** and **How to run** so newcomers can copy-paste successfully. Full FR/NFR and roadmap stay in `docs/codegen_requirements.md` and `docs/codegen_stories.md`.
