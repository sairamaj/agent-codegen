# Codegen Agent — User Stories (CLI, OpenAI)

**Version:** 1.0  
**Parent spec:** [codegen_requirements.md](codegen_requirements.md)  
**Scope:** **CLI only** — no IDE plugin or web UI in this backlog.  
**LLM:** **OpenAI API** (Chat Completions / Responses API with tool calling — exact API surface chosen during implementation).  
**Implementation note:** Stories are ordered for a **phased delivery** aligned with requirements Phases 0–3. No implementation is implied by this document alone.

---

## 1. Assumptions and constraints

| Item | Decision |
|------|----------|
| Interface | Single **command-line** application (REPL and/or subcommands). |
| Model provider | **OpenAI**; model name(s) and API version configurable. |
| Secrets | `OPENAI_API_KEY` (or config); never printed to colored console in clear text. |
| Console UX | **Colorized TTY output** similar in spirit to **Claude Code** / modern CLI agents: role- and channel-distinct colors, readable tool blocks, clear errors. |
| Platform | Windows, macOS, Linux (paths and subprocess behavior per NFR-COMPAT in requirements). |
| Workspace context | **[AGENTS.md](../AGENTS.md)** at repo root — decisions and conventions for all agents working in this repo. |

---

## 2. Suggested agent framework

**This repo’s default** is recorded in **[AGENTS.md](../AGENTS.md)**: implement the **OpenAI SDK** with an **explicit** tool-calling loop (messages → `tool_calls` → execute tools → append results → repeat) so the code stays easy to read and learn. Stories below stay **framework-agnostic** but assume that loop shape, plus **streaming** and, in later phases, **persistence** (which you may implement by hand or adopt a library).

### 2.1 Default for this workspace: **OpenAI Python SDK + explicit loop**

| Criterion | Rationale |
|-----------|-----------|
| Learning | The agent mechanism is visible in project code, not hidden inside a graph runtime. |
| OpenAI | Direct use of `tools=` / function calling matches vendor docs and tutorials. |
| Control | Retries, truncation, and policy checks stay in ordinary functions you own. |

**Tradeoff:** Phase 2+ features (checkpointing, compaction, interrupt/resume) require **you** to design storage and state—or introduce a library only when a story justifies it.

### 2.2 Optional escalation: **OpenAI Agents SDK** (Python)

Less boilerplate for linear loops and handoffs; still OpenAI-centric. Use if the explicit loop is stable and you want a thin official abstraction without LangChain.

### 2.3 Optional escalation: **LangGraph** (Python)

| Criterion | Rationale |
|-----------|-----------|
| Agent loop | Graph for plan → tools → observe → repeat; strong fit for FR-AGENT and branching policy. |
| Phase 2+ | Persistence and interrupts map cleanly to FR-HITL and FR-SESS. |

**When to choose LangGraph:** You need checkpointed sessions and complex branching **and** accept more framework surface area than a hand-written loop.

### 2.4 Optional: **Vercel AI SDK** (TypeScript / Node)

Use if the CLI must be **Node**; pair with Zod for tool schemas. Persistence may remain custom compared to LangGraph.

### 2.5 Recommendation summary (this repo)

| Priority | Approach | Notes |
|----------|----------|--------|
| **1st** | **OpenAI SDK + explicit loop** | Matches [AGENTS.md](../AGENTS.md); best for learning and transparent codegen. |
| **2nd** | **OpenAI Agents SDK** | Small step up in abstraction when duplication hurts. |
| **3rd** | **LangGraph** | When Phase 2 state/persistence complexity warrants a graph library. |
| **4th** | **Vercel AI SDK** | TypeScript CLI. |

**Note:** The “loop” is still explicit logic in your codebase; the OpenAI client handles HTTP and parsing—not the orchestration story.

---

## 3. Color console (Claude-style) — product expectations

These expectations inform **cross-cutting stories** and acceptance criteria; exact ANSI/library choice is implementation detail.

| Element | Expected behavior |
|---------|-------------------|
| User input | Visually distinct from model output (e.g. bold or dedicated color). |
| Assistant narrative | Default foreground; streaming deltas without breaking line wrap. |
| Tool call headers | Distinct color/icon for **tool name** and **arguments summary** (truncate large args). |
| Tool stdout | Muted or neutral; **stderr** or warnings in **warning** color. |
| Errors | **Error** color; include exit codes for subprocess failures. |
| Plan vs execute | Banner or tag when mode switches (FR-HITL-1). |
| No TTY | If stdout is not a TTY, **disable color** automatically (or honor `NO_COLOR`). |
| Markdown / code | Optional: fenced code blocks use subtle background or syntax highlighting (e.g. Rich + Pygments) when dependencies allow. |

---

## 4. Story map (phases)

```mermaid
flowchart LR
  P0[Phase0_ReadOnly]
  P1[Phase1_Edit_and_Shell]
  P2[Phase2_Hardening]
  P3[Phase3_Extensibility]
  P0 --> P1
  P1 --> P2
  P2 --> P3
```

---

## 5. Phase 0 — Read-only agent

**Goal:** User can run a CLI against a workspace; OpenAI drives **read-only** tools; output is **streamed** and **colorized**. No writes, no mutating shell.

### Epic P0-E1: CLI bootstrap and configuration

| ID | Story | Acceptance criteria | Maps to |
|----|--------|----------------------|---------|
| P0-01 | **As a** developer, **I want** a `codegen` (or agreed name) CLI entry point with `--help`, **so that** I can discover commands and flags. | Help lists global options (workspace, config, verbosity); exit 0. | FR-TASK-1 |
| P0-02 | **As a** developer, **I want** to point the agent at a **workspace directory**, **so that** all tools resolve paths under that root. | Invalid/missing path yields colored error; workspace root logged once per run. | FR-CTX-1, FR-TASK-1 |
| P0-03 | **As a** developer, **I want** configuration via **env + config file** for model name, base URL (optional), and limits, **so that** I can run without hardcoding. | Documented keys; secrets not echoed; invalid config fails fast with clear message. | NFR-PRIV, §7.3 |
| P0-04 | **As a** developer, **I want** the CLI to load **project rules** from agreed paths when present, **so that** behavior matches team conventions. | If `AGENTS.md` (or configured path) exists, its content is injected into context; if absent, no error. | FR-RULE-1, FR-RULE-2 |

### Epic P0-E2: OpenAI and agent loop

| ID | Story | Acceptance criteria | Maps to |
|----|--------|----------------------|---------|
| P0-05 | **As a** developer, **I want** the agent to call **OpenAI** with **tool definitions** matching our filesystem tools, **so that** the model can gather context. | Single successful round-trip: model returns tool call → runtime executes → result sent back. | FR-TOOL-1, FR-AGENT-1 |
| P0-06 | **As a** developer, **I want** **max iterations** and **timeouts** per task, **so that** runaway loops cannot hang my session. | Loop stops at configured max with user-visible reason; documented defaults. | FR-AGENT-2 |
| P0-07 | **As a** developer, **I want** **streaming** assistant tokens to the console, **so that** I see progress like Claude Code. | Tokens appear incrementally; no full buffering until complete (except where API limits dictate). | FR-AGENT-4 |
| P0-08 | **As a** developer, **I want** tool failures to return **structured errors** to the model, **so that** it can recover or ask me. | Simulated bad path returns message in tool result channel; model receives it. | FR-AGENT-3 |

### Epic P0-E3: Read-only tools

| ID | Story | Acceptance criteria | Maps to |
|----|--------|----------------------|---------|
| P0-09 | **As a** developer, **I want** a **read_file** tool with line/byte limits, **so that** large files do not blow the context. | Limit enforced; truncation indicated in result. | FR-TOOL-2, FR-CTX-7 |
| P0-10 | **As a** developer, **I want** a **list_dir** tool with depth/entry caps, **so that** I can explore trees safely. | Caps enforced; large dirs do not dump unbounded output. | FR-TOOL-3, FR-CTX-2 |
| P0-11 | **As a** developer, **I want** a **grep/search** tool with regex and max matches, **so that** I can find symbols quickly. | Pattern, path scope, and truncation behave as documented; traversal blocked per policy. | FR-TOOL-4, FR-CTX-4 |
| P0-12 | **As a** developer, **I want** path traversal outside the workspace **rejected**, **so that** the agent cannot read arbitrary files. | `..` and symlink-escape cases covered by tests. | FR-CTX-1, NFR-SEC-1 |

### Epic P0-E4: Colored console UX

| ID | Story | Acceptance criteria | Maps to |
|----|--------|----------------------|---------|
| P0-13 | **As a** developer, **I want** **color-coded** streams for user vs assistant vs tool vs errors, **so that** scans are easy. | At least four semantic styles; matches Section 3 expectations. | UX |
| P0-14 | **As a** developer, **I want** **no ANSI codes** when piping to a file or `NO_COLOR` is set, **so that** logs stay clean. | Piped stdout has no color by default; `NO_COLOR` respected. | UX, NFR-OBS |
| P0-15 | **As a** developer, **I want** tool invocations to print a **compact summary** of name and key args before output, **so that** I can follow the agent’s steps. | Args truncated over N chars; full secrets never printed. | FR-AGENT-4, NFR-SEC-2 |

### Epic P0-E5: Observability (minimal)

| ID | Story | Acceptance criteria | Maps to |
|----|--------|----------------------|---------|
| P0-16 | **As a** developer, **I want** optional **structured logs** to a file or stderr, **so that** I can debug tool traces. | JSON lines or equivalent with `trace_id` per invocation. | NFR-OBS-1, NFR-OBS-2 |

**Phase 0 milestone:** End-to-end: natural-language question → read-only tools → streamed colored answer → stop within limits.

---

## 6. Phase 1 — Editing agent

**Goal:** Apply patches, run **bounded** terminal commands, **plan vs execute** modes, policy gates, basic audit trail.

### Epic P1-E1: Patches and edits

| ID | Story | Acceptance criteria | Maps to |
|----|--------|----------------------|---------|
| P1-01 | **As a** developer, **I want** an **apply_patch** (or equivalent) tool, **so that** the agent can edit files deterministically. | Success/failure per file; workspace boundary enforced. | FR-TOOL-5, FR-EDIT-1–3 |
| P1-02 | **As a** developer, **I want** failed hunks to report **clear errors** and allow the model to re-read files, **so that** conflicts are recoverable. | Mismatch returns line-accurate message in tests. | FR-EDIT-4 |
| P1-03 | **As a** developer, **I want** documented behavior for **partial multi-file applies**, **so that** I know what happened if one file fails. | Documented + tested per FR-EDIT-5. | FR-EDIT-5 |

### Epic P1-E2: Terminal and policy

| ID | Story | Acceptance criteria | Maps to |
|----|--------|----------------------|---------|
| P1-04 | **As a** developer, **I want** a **run_terminal_cmd** tool with **cwd under workspace**, timeout, and captured output, **so that** I can run builds/tests. | Exit code and truncated stdout/stderr returned to model; timeout kills process. | FR-TOOL-6 |
| P1-05 | **As a** team lead, **I want** **allowlist/denylist** patterns for commands, **so that** risky invocations are blocked by default. | Denied command never executes; reason shown in color. | FR-TOOL-7, NFR-SEC-4 |
| P1-06 | **As a** developer, **I want** **plan mode** (no writes / no mutating commands) vs **execute mode**, **so that** I can preview reasoning safely. | In plan mode, patch and mutating shell are rejected at runtime. | FR-HITL-1 |
| P1-07 | **As a** developer, **I want** **approval prompts** in the TTY for sensitive operations when policy requires, **so that** I control destructive steps. | y/n (or similar) gates logged as approved/denied. | FR-HITL-2, FR-HITL-3 |

### Epic P1-E3: Session audit

| ID | Story | Acceptance criteria | Maps to |
|----|--------|----------------------|---------|
| P1-08 | **As a** developer, **I want** an **ordered trace** of tool calls and outcomes for a session, **so that** I can reproduce or file bugs. | Export or log file sufficient to replay tool sequence. | FR-SESS-4 |
| P1-09 | **As a** developer, **I want** **clarifying questions** when the task is ambiguous, **so that** I do not get silent wrong edits. | Story/demo: ambiguous prompt leads to question before large edits. | FR-TASK-3 |

**Phase 1 milestone:** Implement a small feature via CLI (multi-file patch + one allowed command) with plan/execute and colored output.

---

## 7. Phase 2 — Production hardening

**Goal:** Verification hooks, gitignore-aware search, persistence, compaction, optional web fetch.

### Epic P2-E1: Verification

| ID | Story | Acceptance criteria | Maps to |
|----|--------|----------------------|---------|
| P2-01 | **As a** developer, **I want** configurable **post-edit hooks** (formatter/linter/test), **so that** quality gates run automatically. | Hook output visible in console (color for stderr); policy for fail vs warn. | FR-VER-1–3 |

### Epic P2-E2: Context quality

| ID | Story | Acceptance criteria | Maps to |
|----|--------|----------------------|---------|
| P2-02 | **As a** developer, **I want** **grep/list** to respect `.gitignore` when enabled, **so that** noise is reduced. | Config flag; fixtures prove ignored paths skipped. | FR-CTX-5 |
| P2-03 | **As a** developer, **I want** debug metadata showing **which files** informed context (when feasible), **so that** I trust answers. | Log or verbose mode lists paths/snippets count. | FR-CTX-8 |

### Epic P2-E3: Session persistence and compaction

| ID | Story | Acceptance criteria | Maps to |
|----|--------|----------------------|---------|
| P2-04 | **As a** developer, **I want** to **resume** a prior CLI session from disk, **so that** long tasks survive restarts. | Documented storage location; resume continues conversation. | FR-SESS-2 |
| P2-05 | **As a** developer, **I want** **history compaction** near context limits, **so that** older turns summarize without dropping critical constraints. | Documented rules; test with oversized history. | FR-SESS-3 |
| P2-06 | **As a** team lead, **I want** **hashed rule metadata** in logs, **so that** audits know which guidance applied. | Hash appears in structured log for session. | FR-RULE-3 |

### Epic P2-E4: Optional web

| ID | Story | Acceptance criteria | Maps to |
|----|--------|----------------------|---------|
| P2-07 | **As a** developer, **I want** an optional **web_fetch** tool with strict size/time limits, **so that** the agent can read public docs safely. | Network off by default or policy-gated; truncation explicit. | FR-TOOL-8 |

**Phase 2 milestone:** Golden tasks from requirements §9.1 runnable with hooks and resumable sessions.

---

## 8. Phase 3 — Extensibility

**Goal:** MCP, richer policy packs, optional multi-session/quotas for shared machines.

### Epic P3-E1: MCP

| ID | Story | Acceptance criteria | Maps to |
|----|--------|----------------------|---------|
| P3-01 | **As a** developer, **I want** to attach **MCP servers** via config, **so that** extra tools appear like first-party tools. | MCP tool calls obey same policy and audit rules. | FR-TOOL-9 |
| P3-02 | **As a** platform owner, **I want** MCP tool invocations **logged** like built-ins, **so that** compliance matches internal tools. | NFR-OBS satisfied for MCP. | NFR-OBS-2 |

### Epic P3-E2: Enterprise-style controls (CLI-relevant subset)

| ID | Story | Acceptance criteria | Maps to |
|----|--------|----------------------|---------|
| P3-03 | **As a** platform owner, **I want** **importable policy packs** (YAML/JSON) for deny/allow rules, **so that** teams share baseline security. | Load merge order documented; invalid pack fails startup. | Phase 3 roadmap |
| P3-04 | **As a** platform owner, **I want** optional **per-user quotas** (tokens or wall clock) on shared runners, **so that** cost is bounded. | Soft/hard limit behavior documented. | Phase 3 roadmap |

**Phase 3 milestone:** At least one MCP workflow (e.g. doc lookup) demonstrated from CLI with colors and policy.

---

## 9. Cross-cutting and testing stories

| ID | Story | Acceptance criteria | Maps to |
|----|--------|----------------------|---------|
| X-01 | **As a** maintainer, **I want** **contract tests** for every tool, **so that** regressions are caught early. | Happy + error paths per tool. | §9.2 |
| X-02 | **As a** maintainer, **I want** **patch fixtures** for CRLF/LF and conflict cases, **so that** edits are portable across OS. | Windows + Linux CI jobs or equivalent. | §9.2, NFR-COMPAT-3 |
| X-03 | **As a** maintainer, **I want** **policy tests** proving denied commands never run, **so that** security stories stay true. | Automated test with spy/subprocess mock. | §9.2 |

---

## 10. Suggested implementation order (for the coding agent)

1. **P0-01 → P0-03** (CLI skeleton, config, workspace).  
2. **P0-13 → P0-15** (color console early — avoids retrofitting).  
3. **P0-05 → P0-08** (OpenAI + loop + streaming).  
4. **P0-09 → P0-12** (read-only tools + security tests).  
5. **P0-16** (structured logging).  
6. Phase 1 in epic order; then Phase 2 and 3 as needed.

---

## Document control

| Version | Date | Notes |
|---------|------|--------|
| 1.0 | 2026-03-28 | Initial stories: CLI, OpenAI, phased, framework guidance, Claude-style console. |
| 1.1 | 2026-03-28 | Linked [AGENTS.md](../AGENTS.md); default framework = OpenAI SDK + explicit loop; LangGraph as optional escalation. |
