"""apply_patch tool — structured edits under workspace (P1-01, FR-TOOL-5, FR-EDIT-1–3, P1-02, P1-03).

Format: JSON with ``files`` array. Each file has ``path`` (workspace-relative) and ``hunks``
``[{ "old_text": "...", "new_text": "..." }]``. Each hunk replaces ``old_text`` with ``new_text``
exactly once (substring match). For **new files**, the file must not exist and the only hunk must
have ``old_text`` empty and ``new_text`` as the full file body.

**Partial multi-file apply** (FR-EDIT-5, P1-03): Not atomic across files. The ``files`` list is
processed **in order**; a failure on one entry **does not** stop later entries. Each file is read,
hunks applied **in memory**, then **one write**; if hunks fail, that file is unchanged on disk.
The JSON result includes ``files`` in input order with per-file ``ok``; top-level ``ok`` is true
only if all succeed. If any failed, ``partial`` is true when some succeeded and some failed, false
when all failed, and omitted when all succeeded. See ``docs/codegen_requirements.md`` §4.5.1.

**Hunk errors (P1-02, FR-EDIT-4)**: On ``HUNK_MISMATCH`` or ``AMBIGUOUS_MATCH``, errors include
``hunk_index``, ``line_count``, 1-based ``line``/``column`` where applicable, a short
``context_preview``, and a ``hint`` to call ``read_file`` on the same path before retrying.

**Newlines / encoding**: Read/write UTF-8. Files are opened with ``newline=""`` so ``\\r\\n`` in
existing files is preserved in the string and written back unchanged.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from codegen.workspace_paths import PathOutsideWorkspaceError, resolve_under_workspace

# Guardrail: total size of old_text + new_text across the patch (characters).
_MAX_PATCH_PAYLOAD_CHARS = 2_000_000
_MAX_FILES = 100
_MAX_HUNKS_PER_FILE = 500
_MAX_PREVIEW_LINES = 16
_MAX_LINE_TEXT = 240
_MAX_OCCURRENCES_LIST = 8


def _tool_error(code: str, message: str) -> str:
    return json.dumps({"ok": False, "error": {"code": code, "message": message}}, ensure_ascii=False)


def _count_payload_chars(files_spec: list[dict[str, Any]]) -> int:
    n = 0
    for f in files_spec:
        hunks = f.get("hunks") or []
        for h in hunks:
            if not isinstance(h, dict):
                continue
            ot = h.get("old_text", "")
            nt = h.get("new_text", "")
            if isinstance(ot, str):
                n += len(ot)
            if isinstance(nt, str):
                n += len(nt)
    return n


def _offset_to_line_col(content: str, offset: int) -> tuple[int, int]:
    """1-based line and column for a character offset in ``content``."""
    if offset < 0:
        offset = 0
    if offset > len(content):
        offset = len(content)
    head = content[:offset]
    line_no = head.count("\n") + 1
    last_nl = head.rfind("\n")
    col = offset - (last_nl + 1) + 1
    return line_no, col


def _substring_start_offsets(content: str, sub: str) -> list[int]:
    if not sub:
        return []
    out: list[int] = []
    start = 0
    while True:
        i = content.find(sub, start)
        if i < 0:
            break
        out.append(i)
        start = i + 1
    return out


def _line_numbered_preview(content: str, center_line: int | None, *, radius: int = 4) -> list[dict[str, Any]]:
    """Lines as ``{ "line": n, "text": "..." }`` (1-based line numbers), bounded."""
    lines = content.splitlines()
    if not lines and content:
        lines = [content]
    n = len(lines)
    if n == 0:
        return []
    if center_line is None or center_line < 1:
        lo, hi = 1, min(n, _MAX_PREVIEW_LINES)
    else:
        lo = max(1, center_line - radius)
        hi = min(n, center_line + radius)
        span = hi - lo + 1
        if span < _MAX_PREVIEW_LINES:
            hi = min(n, lo + _MAX_PREVIEW_LINES - 1)
    out: list[dict[str, Any]] = []
    for i in range(lo - 1, min(hi, n)):
        text = lines[i]
        if len(text) > _MAX_LINE_TEXT:
            text = text[: _MAX_LINE_TEXT - 1] + "…"
        out.append({"line": i + 1, "text": text})
    return out


def _hunk_mismatch_detail(path: str, hunk_index: int, content: str, old_t: str) -> dict[str, Any]:
    line_count = len(content.splitlines())
    first_line = old_t.split("\n", 1)[0]
    detail: dict[str, Any] = {
        "code": "HUNK_MISMATCH",
        "path": path,
        "hunk_index": hunk_index,
        "line_count": line_count,
        "hint": (
            f"Call read_file with path {path!r} to copy the exact current text, then fix "
            "old_text (whitespace and newlines must match exactly)."
        ),
    }
    if first_line and first_line in content and old_t not in content:
        idx = content.find(first_line)
        line, col = _offset_to_line_col(content, idx)
        detail["first_line_found_at"] = {"line": line, "column": col}
        detail["message"] = (
            f"{path}: hunk {hunk_index} full old_text is not a contiguous substring; the first line "
            f"of old_text appears at line {line}, column {col}, but the following lines do not match. "
            "Re-read the file and align the patch."
        )
        detail["context_preview"] = _line_numbered_preview(content, line)
    else:
        detail["message"] = (
            f"{path}: hunk {hunk_index} old_text not found (no exact contiguous match). "
            f"File has {line_count} line(s). Use read_file on this path and retry."
        )
        detail["context_preview"] = _line_numbered_preview(content, None)
    return detail


def _ambiguous_detail(path: str, hunk_index: int, content: str, old_t: str, count: int) -> dict[str, Any]:
    offsets = _substring_start_offsets(content, old_t)[:_MAX_OCCURRENCES_LIST]
    occurrences = []
    for off in offsets:
        line, col = _offset_to_line_col(content, off)
        occurrences.append({"line": line, "column": col})
    line_nums = [o["line"] for o in occurrences]
    preview_line = line_nums[0] if line_nums else None
    return {
        "code": "AMBIGUOUS_MATCH",
        "path": path,
        "hunk_index": hunk_index,
        "occurrence_count": count,
        "occurrences": occurrences,
        "message": (
            f"{path}: hunk {hunk_index} old_text matches {count} times at lines "
            f"{', '.join(str(x) for x in line_nums)}; include more context so the match is unique."
        ),
        "hint": (
            f"Call read_file with path {path!r} to see surrounding lines, then expand old_text."
        ),
        "context_preview": _line_numbered_preview(content, preview_line),
    }


def _apply_hunks_to_content(
    path: str,
    content: str,
    hunks: list[dict[str, Any]],
    *,
    creating: bool,
) -> tuple[str | None, dict[str, Any] | None]:
    """Return (new_content, None) or (None, error_dict)."""
    if creating:
        if len(hunks) != 1:
            return None, {
                "code": "INVALID_ARGUMENT",
                "message": (
                    f"New file {path!r} requires exactly one hunk with "
                    "old_text \"\" and new_text as full content."
                ),
            }
        h0 = hunks[0]
        if not isinstance(h0, dict):
            return None, {"code": "INVALID_ARGUMENT", "message": "Hunk must be an object."}
        old_t = h0.get("old_text", "")
        if old_t != "":
            return None, {
                "code": "INVALID_ARGUMENT",
                "message": f"New file {path!r} must use empty old_text in the single hunk.",
            }
        new_t = h0.get("new_text", "")
        if not isinstance(new_t, str):
            return None, {"code": "INVALID_ARGUMENT", "message": "new_text must be a string."}
        return new_t, None

    current = content
    for i, h in enumerate(hunks):
        if not isinstance(h, dict):
            return None, {
                "code": "INVALID_ARGUMENT",
                "message": f"{path}: hunk {i} must be an object.",
            }
        old_t = h.get("old_text", "")
        new_t = h.get("new_text", "")
        if not isinstance(old_t, str) or not isinstance(new_t, str):
            return None, {
                "code": "INVALID_ARGUMENT",
                "message": f"{path}: hunk {i} old_text and new_text must be strings.",
            }
        if old_t == "":
            return None, {
                "code": "INVALID_ARGUMENT",
                "message": (
                    f"{path}: hunk {i} empty old_text is only valid when creating a new file."
                ),
            }
        count = current.count(old_t)
        if count == 0:
            return None, _hunk_mismatch_detail(path, i, current, old_t)
        if count > 1:
            return None, _ambiguous_detail(path, i, current, old_t, count)
        current = current.replace(old_t, new_t, 1)
    return current, None


def apply_patch(workspace: Path, args: dict[str, Any]) -> str:
    """Apply structured patch; returns JSON string for the model."""
    raw_files = args.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        return _tool_error("INVALID_ARGUMENT", "apply_patch requires non-empty files array")
    if len(raw_files) > _MAX_FILES:
        return _tool_error("INVALID_ARGUMENT", f"Too many files (max {_MAX_FILES})")

    files_spec: list[dict[str, Any]] = []
    for i, entry in enumerate(raw_files):
        if not isinstance(entry, dict):
            return _tool_error("INVALID_ARGUMENT", f"files[{i}] must be an object")
        files_spec.append(entry)

    payload_chars = _count_payload_chars(files_spec)
    if payload_chars > _MAX_PATCH_PAYLOAD_CHARS:
        return _tool_error(
            "INVALID_ARGUMENT",
            f"Patch payload too large ({payload_chars} chars; max {_MAX_PATCH_PAYLOAD_CHARS}).",
        )

    results: list[dict[str, Any]] = []
    any_failed = False

    for entry in files_spec:
        rel = entry.get("path")
        if not isinstance(rel, str) or not rel.strip():
            any_failed = True
            results.append(
                {
                    "path": rel if isinstance(rel, str) else "",
                    "ok": False,
                    "error": {"code": "INVALID_ARGUMENT", "message": "Each file needs non-empty path"},
                }
            )
            continue

        hunks = entry.get("hunks")
        if not isinstance(hunks, list) or not hunks:
            any_failed = True
            results.append(
                {
                    "path": rel,
                    "ok": False,
                    "error": {"code": "INVALID_ARGUMENT", "message": "Each file needs non-empty hunks"},
                }
            )
            continue
        if len(hunks) > _MAX_HUNKS_PER_FILE:
            any_failed = True
            results.append(
                {
                    "path": rel,
                    "ok": False,
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": f"Too many hunks (max {_MAX_HUNKS_PER_FILE})",
                    },
                }
            )
            continue

        try:
            target = resolve_under_workspace(workspace, rel)
        except PathOutsideWorkspaceError as e:
            any_failed = True
            results.append(
                {
                    "path": rel,
                    "ok": False,
                    "error": {"code": "PATH_OUTSIDE_WORKSPACE", "message": str(e)},
                }
            )
            continue

        creating = not target.exists()
        if target.exists() and not target.is_file():
            any_failed = True
            results.append(
                {
                    "path": rel,
                    "ok": False,
                    "error": {"code": "NOT_A_FILE", "message": f"Path is not a file: {rel}"},
                }
            )
            continue

        if creating:
            content = ""
        else:
            try:
                with open(target, "r", encoding="utf-8", newline="") as f:
                    content = f.read()
            except OSError as e:
                any_failed = True
                results.append(
                    {
                        "path": rel,
                        "ok": False,
                        "error": {"code": "IO_ERROR", "message": f"Cannot read file: {e}"},
                    }
                )
                continue
            except UnicodeDecodeError:
                any_failed = True
                results.append(
                    {
                        "path": rel,
                        "ok": False,
                        "error": {"code": "ENCODING", "message": "File is not valid UTF-8."},
                    }
                )
                continue

        new_content, err = _apply_hunks_to_content(rel, content, hunks, creating=creating)
        if err is not None:
            any_failed = True
            results.append({"path": rel, "ok": False, "error": err})
            continue

        assert new_content is not None
        parent = target.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8", newline="") as f:
                f.write(new_content)
        except OSError as e:
            any_failed = True
            results.append(
                {
                    "path": rel,
                    "ok": False,
                    "error": {"code": "IO_ERROR", "message": f"Cannot write file: {e}"},
                }
            )
            continue

        digest = hashlib.sha256(new_content.encode("utf-8")).hexdigest()
        results.append(
            {
                "path": rel,
                "ok": True,
                "bytes_written": len(new_content.encode("utf-8")),
                "sha256": digest,
            }
        )

    out_obj: dict[str, Any] = {
        "ok": not any_failed,
        "files": results,
    }
    if any_failed:
        out_obj["partial"] = any(r.get("ok") for r in results if isinstance(r, dict))
    return json.dumps(out_obj, ensure_ascii=False)


APPLY_PATCH_TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "apply_patch",
        "description": (
            "Apply structured edits under the workspace. Each file has a path and hunks; "
            "each hunk replaces old_text with new_text exactly once (exact substring). "
            "To create a new file, the path must not exist and you must supply one hunk with "
            "empty old_text and new_text as the full file content. Parent directories are "
            "created as needed. Multi-file: not atomic across files; entries run in "
            "array order and failures do not stop later entries; see top-level ok, partial, "
            "and per-file results. On mismatch, errors include line hints and context_preview; "
            "call read_file on the same path to refresh old_text before retry."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "description": "Ordered list of file patch operations.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Workspace-relative file path (use /).",
                            },
                            "hunks": {
                                "type": "array",
                                "description": "Sequential search/replace hunks for this file.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "old_text": {
                                            "type": "string",
                                            "description": "Exact text to find (empty only when creating a new file).",
                                        },
                                        "new_text": {
                                            "type": "string",
                                            "description": "Replacement text, or full file body for new files.",
                                        },
                                    },
                                    "required": ["old_text", "new_text"],
                                },
                            },
                        },
                        "required": ["path", "hunks"],
                    },
                },
            },
            "required": ["files"],
        },
    },
}
