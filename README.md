# Codegen

CLI coding agent for workspace-scoped tasks (OpenAI, read-only tools first, then edits and policy in later phases). See [docs/codegen_requirements.md](docs/codegen_requirements.md) and [docs/codegen_stories.md](docs/codegen_stories.md).

**Requirements:** Python **3.11+**

---

## How to run (step by step)

Follow these steps whenever you set up a new machine or clone the repo.

### 1. Go to the repo root

```bash
cd /path/to/codegen
```

On Windows (PowerShell):

```powershell
cd c:\sai\dev\ai\agent\codegen
```

### 2. (Recommended) Use a virtual environment

```bash
python -m venv .venv
```

Activate it:

- **Windows (PowerShell):** `.venv\Scripts\Activate.ps1`
- **Windows (cmd):** `.venv\Scripts\activate.bat`
- **macOS / Linux:** `source .venv/bin/activate`

### 3. Install the package

Install in editable mode so code changes apply immediately:

```bash
python -m pip install -e .
```

For development (includes pytest):

```bash
python -m pip install -e ".[dev]"
```

### 4. Run the CLI

You can use either form:

| Method | Example |
|--------|---------|
| Installed script | `codegen --help` |
| Module | `python -m codegen --help` |

**Important:** Put **global options before the subcommand**. For example:

```bash
codegen -w /path/to/your/project info
```

not `codegen info -w /path/to/your/project`.

### 5. Useful commands (current phase)

| Step | Command | What it does |
|------|---------|----------------|
| See all options | `codegen --help` | Lists globals (`--workspace`, `--config`, `--verbose`) and subcommands. |
| Print version | `codegen --version` | Prints the package version. |
| Check workspace + config | `codegen -w . info` | Resolves workspace, loads config (from TOML/env), shows redacted settings and whether project rules (`AGENTS.md`) loaded. |

If you omit the subcommand, the CLI prints the same help as `--help` and exits successfully.

---

## Configuration (optional)

1. Optionally add **`codegen.toml`** or **`.codegen.toml`** in the **workspace** directory, or pass **`--config /path/to/file.toml`**.
2. Set secrets via environment (never commit keys). The CLI does **not** print `OPENAI_API_KEY`.

**TOML keys (all optional):** `model`, `base_url`, `max_iterations`, `max_wall_clock_seconds`, `agents_md`

**Environment variables:** `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `CODEGEN_CONFIG`, `CODEGEN_MAX_ITERATIONS`, `CODEGEN_MAX_WALL_CLOCK_SECONDS`, `CODEGEN_AGENTS_MD`

---

## Run tests

After `python -m pip install -e ".[dev]"`:

```bash
python -m pytest
```

To run tests without installing the package as editable, ensure dependencies are installed and use the same interpreter; CLI subprocess tests expect `typer` (and siblings) on that interpreter.

---

## Maintaining this README

When you complete a new story or phase, **update this file** with:

1. Any new **install** or **dependency** steps.
2. New **commands** or subcommands and a one-line description.
3. New **configuration** keys or environment variables.

That keeps “how to run” accurate for the next step of the roadmap.
"# agent-codegen" 
