"""Session persistence (P2-04, FR-SESS-2)."""

from __future__ import annotations

from pathlib import Path

from openai.types.chat import ChatCompletionMessageParam

from codegen.session_persist import (
    load_session,
    resolve_session_storage_path,
    save_session,
)


def test_resolve_session_name_under_workspace(tmp_path: Path) -> None:
    p = resolve_session_storage_path(
        workspace=tmp_path,
        session_arg="myjob",
        config_path=None,
    )
    assert p is not None
    assert p == (tmp_path / ".codegen" / "sessions" / "myjob.json").resolve()


def test_resolve_explicit_path(tmp_path: Path) -> None:
    target = tmp_path / "s" / "sess.json"
    p = resolve_session_storage_path(
        workspace=tmp_path,
        session_arg=str(target),
        config_path=None,
    )
    assert p == target.resolve()


def test_save_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "sess.json"
    msgs: list[ChatCompletionMessageParam] = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]
    save_session(path, session_id="sid-1", workspace=tmp_path, messages=msgs)
    loaded = load_session(path)
    assert loaded is not None
    assert loaded.session_id == "sid-1"
    assert loaded.workspace == str(tmp_path.resolve())
    assert len(loaded.messages) == 2
    assert loaded.messages[0]["role"] == "user"


def test_load_missing_returns_none(tmp_path: Path) -> None:
    assert load_session(tmp_path / "nope.json") is None
