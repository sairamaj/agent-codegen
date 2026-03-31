# MCP (Model Context Protocol) with Codegen

This CLI can attach **stdio MCP servers** so tools from those servers appear alongside built-in tools (`read_file`, `grep`, `apply_patch`, …). Invocations use the same **structured logging** (`CODEGEN_STRUCTURED_LOG`) and **session audit** (`CODEGEN_SESSION_AUDIT`) as first-party tools (Phase 3, FR-TOOL-9).

## Configuration

Define one or more `[[mcp_servers]]` tables in `codegen.toml` or `.codegen.toml` in the workspace (or the file pointed to by `--config` / `CODEGEN_CONFIG`). At most **16** servers are allowed.

| Field | Required | Meaning |
|-------|----------|---------|
| `name` | yes | Stable id (unique in this file). Used in logs and in OpenAI function names. |
| `command` | yes | Executable to spawn (e.g. `npx`, `uvx`, path to a binary). |
| `args` | no | JSON array of arguments (TOML array of strings). |
| `env` | no | Extra environment variables for the server process (table of string keys/values). |
| `cwd` | no | Working directory for the server: absolute path, or relative to the **workspace** root. |

Example: **filesystem** MCP server (requires Node/npm so `npx` is available):

```toml
[[mcp_servers]]
name = "repo_fs"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "C:/path/to/allowed/root"]
# The last argument is the directory the MCP server may access (see upstream server docs).
```

Example: **memory** server (shared memory/notes style utilities):

```toml
[[mcp_servers]]
name = "memory"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-memory"]
```

After editing config, run `codegen info -w <workspace>` to confirm the workspace resolves and `mcp_servers` lists your server names.

## How tools look to the model

Each MCP tool is exposed as an OpenAI function whose name starts with `mcp__`, then your server `name`, then the MCP tool name, for example:

`mcp__repo_fs__read_file`

Descriptions are prefixed with `[MCP server: <name>]` so you can tell origin in logs and in the model’s tool list.

## Runtime behavior

- Servers are **started** when a `codegen run` begins (each invocation), and **stopped** when that run finishes.
- Transport is **stdio** only (spawned subprocess); SSE/HTTP MCP servers are not configured in TOML here.
- If MCP startup fails, the CLI logs a warning (`MCP server startup failed; continuing without MCP tools: …`) and continues the run using built-in tools only.
- **Plan vs execute:** MCP tools are available in both modes. Built-in `apply_patch` and `run_terminal_cmd` stay disabled in **plan** mode as before. Command **allow/deny/approval** policies apply to `run_terminal_cmd` only, not to MCP tools—treat MCP servers as trusted as you would shell access.

## Observability

With `CODEGEN_STRUCTURED_LOG` set, `tool.start` / `tool.complete` events include MCP tool names and sanitized args like any other tool. Session audit lines (`audit.tool`) record MCP calls in order with the same fields as built-in tools.

`codegen info` shows `mcp_servers` as a count and server names (API keys and other secrets are never printed).

## Troubleshooting

| Issue | What to check |
|-------|----------------|
| `npx` / `uvx` not found | Install Node or uv; use an absolute path to the executable in `command` if needed. |
| Server exits immediately | Run the same `command` + `args` in a terminal from `cwd`; fix until the MCP server stays up. |
| Windows path quirks | Prefer forward slashes or escaped backslashes in TOML; `cwd` may be relative to the workspace. |
| Too many tools | There is a cap on merged MCP tool definitions; reduce servers or disable tools on the server side if possible. |

## References

- [Model Context Protocol](https://modelcontextprotocol.io/)
- User stories: [codegen_stories.md](codegen_stories.md) — Epic P3-E1
