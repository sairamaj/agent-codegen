"""apply_patch tool tests (P1-01, FR-TOOL-5)."""

from __future__ import annotations

import json
from pathlib import Path

from codegen.tools_readonly import execute_tool


def test_apply_patch_single_hunk(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello world\n", encoding="utf-8", newline="\n")
    raw = execute_tool(
        tmp_path,
        "apply_patch",
        json.dumps(
            {
                "files": [
                    {
                        "path": "a.txt",
                        "hunks": [{"old_text": "world", "new_text": "there"}],
                    }
                ]
            }
        ),
    )
    data = json.loads(raw)
    assert data["ok"] is True
    assert len(data["files"]) == 1
    assert data["files"][0]["ok"] is True
    assert data["files"][0]["sha256"]
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello there\n"


def test_apply_patch_per_file_failure(tmp_path: Path) -> None:
    (tmp_path / "ok.txt").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "bad.txt").write_text("line1\ncontent\nline3\n", encoding="utf-8")
    raw = execute_tool(
        tmp_path,
        "apply_patch",
        json.dumps(
            {
                "files": [
                    {
                        "path": "ok.txt",
                        "hunks": [{"old_text": "alpha", "new_text": "beta"}],
                    },
                    {
                        "path": "bad.txt",
                        "hunks": [{"old_text": "nope", "new_text": "x"}],
                    },
                ]
            }
        ),
    )
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["partial"] is True
    assert data["files"][0]["ok"] is True
    assert data["files"][1]["ok"] is False
    err = data["files"][1]["error"]
    assert err["code"] == "HUNK_MISMATCH"
    assert err["hunk_index"] == 0
    assert err["line_count"] == 3
    assert "read_file" in err["hint"]
    assert any("line1" in row["text"] for row in err["context_preview"])
    assert (tmp_path / "ok.txt").read_text(encoding="utf-8") == "beta\n"
    assert (tmp_path / "bad.txt").read_text(encoding="utf-8") == "line1\ncontent\nline3\n"


def test_apply_patch_path_outside_workspace(tmp_path: Path) -> None:
    raw = execute_tool(
        tmp_path,
        "apply_patch",
        json.dumps(
            {
                "files": [
                    {
                        "path": "../../outside.txt",
                        "hunks": [{"old_text": "", "new_text": "x"}],
                    }
                ]
            }
        ),
    )
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["files"][0]["error"]["code"] == "PATH_OUTSIDE_WORKSPACE"


def test_apply_patch_create_file(tmp_path: Path) -> None:
    raw = execute_tool(
        tmp_path,
        "apply_patch",
        json.dumps(
            {
                "files": [
                    {
                        "path": "new/nested.txt",
                        "hunks": [{"old_text": "", "new_text": "created\n"}],
                    }
                ]
            }
        ),
    )
    data = json.loads(raw)
    assert data["ok"] is True
    assert (tmp_path / "new" / "nested.txt").read_text(encoding="utf-8") == "created\n"


def test_apply_patch_crlf_preserved(tmp_path: Path) -> None:
    p = tmp_path / "crlf.txt"
    p.write_bytes(b"a\r\nb\r\n")
    raw = execute_tool(
        tmp_path,
        "apply_patch",
        json.dumps(
            {
                "files": [
                    {
                        "path": "crlf.txt",
                        "hunks": [{"old_text": "a", "new_text": "A"}],
                    }
                ]
            }
        ),
    )
    data = json.loads(raw)
    assert data["ok"] is True
    assert p.read_bytes() == b"A\r\nb\r\n"


def test_apply_patch_ambiguous_match(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text("foo foo\n", encoding="utf-8")
    raw = execute_tool(
        tmp_path,
        "apply_patch",
        json.dumps(
            {
                "files": [
                    {
                        "path": "x.txt",
                        "hunks": [{"old_text": "foo", "new_text": "bar"}],
                    }
                ]
            }
        ),
    )
    data = json.loads(raw)
    assert data["ok"] is False
    err = data["files"][0]["error"]
    assert err["code"] == "AMBIGUOUS_MATCH"
    assert err["occurrence_count"] == 2
    assert err["occurrences"][0]["line"] == 1
    assert err["occurrences"][1]["line"] == 1
    assert err["occurrences"][0]["column"] == 1
    assert err["occurrences"][1]["column"] == 5


def test_hunk_mismatch_multiline_first_line_matches(tmp_path: Path) -> None:
    (tmp_path / "m.txt").write_text("aaa\nbbb\nccc\n", encoding="utf-8")
    raw = execute_tool(
        tmp_path,
        "apply_patch",
        json.dumps(
            {
                "files": [
                    {
                        "path": "m.txt",
                        "hunks": [{"old_text": "aaa\nbbb\nWRONG", "new_text": "x"}],
                    }
                ]
            }
        ),
    )
    data = json.loads(raw)
    err = data["files"][0]["error"]
    assert err["code"] == "HUNK_MISMATCH"
    assert err["first_line_found_at"]["line"] == 1
    assert err["first_line_found_at"]["column"] == 1


def test_empty_old_text_rejected_on_existing_file(tmp_path: Path) -> None:
    (tmp_path / "e.txt").write_text("x\n", encoding="utf-8")
    raw = execute_tool(
        tmp_path,
        "apply_patch",
        json.dumps(
            {
                "files": [
                    {
                        "path": "e.txt",
                        "hunks": [{"old_text": "", "new_text": "y"}],
                    }
                ]
            }
        ),
    )
    data = json.loads(raw)
    assert data["files"][0]["error"]["code"] == "INVALID_ARGUMENT"


def test_apply_patch_sequential_hunks(tmp_path: Path) -> None:
    (tmp_path / "s.txt").write_text("one two three\n", encoding="utf-8")
    raw = execute_tool(
        tmp_path,
        "apply_patch",
        json.dumps(
            {
                "files": [
                    {
                        "path": "s.txt",
                        "hunks": [
                            {"old_text": "one", "new_text": "1"},
                            {"old_text": "two", "new_text": "2"},
                        ],
                    }
                ]
            }
        ),
    )
    data = json.loads(raw)
    assert data["ok"] is True
    assert (tmp_path / "s.txt").read_text(encoding="utf-8") == "1 2 three\n"


def test_partial_multifile_continues_after_failure(tmp_path: Path) -> None:
    """P1-03 / FR-EDIT-5: failure on file 2 does not skip file 3; results follow input order."""
    (tmp_path / "a.txt").write_text("A\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("B\n", encoding="utf-8")
    (tmp_path / "c.txt").write_text("C\n", encoding="utf-8")
    raw = execute_tool(
        tmp_path,
        "apply_patch",
        json.dumps(
            {
                "files": [
                    {"path": "a.txt", "hunks": [{"old_text": "A", "new_text": "AA"}]},
                    {"path": "b.txt", "hunks": [{"old_text": "nomatch", "new_text": "x"}]},
                    {"path": "c.txt", "hunks": [{"old_text": "C", "new_text": "CC"}]},
                ]
            }
        ),
    )
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["partial"] is True
    assert [f["path"] for f in data["files"]] == ["a.txt", "b.txt", "c.txt"]
    assert data["files"][0]["ok"] is True
    assert data["files"][1]["ok"] is False
    assert data["files"][1]["error"]["code"] == "HUNK_MISMATCH"
    assert data["files"][2]["ok"] is True
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "AA\n"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "B\n"
    assert (tmp_path / "c.txt").read_text(encoding="utf-8") == "CC\n"


def test_partial_multifile_all_fail_partial_false(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text("1\n", encoding="utf-8")
    (tmp_path / "y.txt").write_text("2\n", encoding="utf-8")
    raw = execute_tool(
        tmp_path,
        "apply_patch",
        json.dumps(
            {
                "files": [
                    {"path": "x.txt", "hunks": [{"old_text": "bad", "new_text": "z"}]},
                    {"path": "y.txt", "hunks": [{"old_text": "bad", "new_text": "z"}]},
                ]
            }
        ),
    )
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["partial"] is False


def test_partial_multifile_all_success_omits_partial_key(tmp_path: Path) -> None:
    (tmp_path / "p.txt").write_text("p\n", encoding="utf-8")
    (tmp_path / "q.txt").write_text("q\n", encoding="utf-8")
    raw = execute_tool(
        tmp_path,
        "apply_patch",
        json.dumps(
            {
                "files": [
                    {"path": "p.txt", "hunks": [{"old_text": "p", "new_text": "P"}]},
                    {"path": "q.txt", "hunks": [{"old_text": "q", "new_text": "Q"}]},
                ]
            }
        ),
    )
    data = json.loads(raw)
    assert data["ok"] is True
    assert "partial" not in data
