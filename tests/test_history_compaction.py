"""History compaction (P2-05, FR-SESS-3)."""

from __future__ import annotations

from codegen.history_compaction import (
    compact_prior_messages,
    estimate_messages_chars,
    split_into_turns,
)


def _user(s: str) -> dict:
    return {"role": "user", "content": s}


def _asst(s: str) -> dict:
    return {"role": "assistant", "content": s}


def test_split_into_turns_two_users() -> None:
    msgs = [_user("a"), _asst("b"), _user("c"), _asst("d")]
    turns = split_into_turns(msgs)
    assert len(turns) == 2
    assert turns[0] == [_user("a"), _asst("b")]
    assert turns[1] == [_user("c"), _asst("d")]


def test_no_compaction_under_budget() -> None:
    msgs = [_user("hello"), _asst("hi")]
    out, did = compact_prior_messages(msgs, max_chars=100_000)
    assert did is False
    assert out == msgs


def test_compaction_preserves_first_and_recent_tail() -> None:
    """Oversized history: first turn + tail turns kept; middle turns replaced by notice."""
    block = "x" * 4000
    msgs: list[dict] = []
    for i in range(12):
        msgs.append(_user(f"task-{i} {block}"))
        msgs.append(_asst(f"reply-{i} {block}"))
    assert estimate_messages_chars(msgs) > 80_000

    out, did = compact_prior_messages(msgs, max_chars=25_000)
    assert did is True
    assert any(
        isinstance(m.get("content"), str) and "[History compaction]" in m["content"]
        for m in out
        if m.get("role") == "user"
    )
    assert out[0]["role"] == "user" and "task-0" in str(out[0].get("content"))
    assert any("task-11" in str(m.get("content")) for m in out if m.get("role") == "user")


def test_single_turn_truncates_first_user() -> None:
    long = "z" * 100_000
    msgs = [_user(long)]
    out, did = compact_prior_messages(msgs, max_chars=500)
    assert did is True
    assert len(out) == 1
    c = out[0].get("content")
    assert isinstance(c, str)
    assert len(c) <= 500 + 20  # small slack for JSON overhead vs message_chars
