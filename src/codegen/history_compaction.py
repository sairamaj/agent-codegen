"""
History compaction near context limits (P2-05, FR-SESS-3).

Rules (deterministic; no extra model call):

1. **Measure** approximate size as UTF-8 length of ``json.dumps`` of each message dict
   (same shape as OpenAI chat messages).

2. **Turns** — A turn starts at each ``role=user`` message and runs until the next
   ``role=user`` (so assistant + tool messages stay attached to the user message
   that triggered them). This keeps ``tool_calls`` / ``tool`` pairs intact.

3. **If** total size is at or below ``max_chars``, return messages unchanged.

4. **Otherwise**:
   - Always keep the **first turn** (the original user task anchor). If that turn alone
     exceeds ``max_chars``, truncate only the first user message's text content with an
     ellipsis suffix so the rest of the pipeline can run.
   - From the **end**, take as many **complete** turns as fit in the remaining budget
     after reserving space for a compaction notice.
   - If any middle turns were dropped, insert a **synthetic** ``user`` message after
     the first turn describing how many turns were omitted; it repeats the start of the
     original task for traceability.

5. **Preserved vs dropped** — Critical constraints should live in the first user message
   or recent turns; middle turns are the only ones replaced by the notice.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from copy import deepcopy
from openai.types.chat import ChatCompletionMessageParam


def _message_json_chars(m: ChatCompletionMessageParam) -> int:
    """Approximate message size for budgeting (stable, JSON-shaped)."""
    return len(json.dumps(m, ensure_ascii=False))


def estimate_messages_chars(messages: Sequence[ChatCompletionMessageParam]) -> int:
    return sum(_message_json_chars(m) for m in messages)


def split_into_turns(messages: list[ChatCompletionMessageParam]) -> list[list[ChatCompletionMessageParam]]:
    """Split transcript (after system) into turns: each begins with role=user."""
    if not messages:
        return []
    turns: list[list[ChatCompletionMessageParam]] = []
    current: list[ChatCompletionMessageParam] = []
    for m in messages:
        role = m.get("role")
        if role == "user" and current:
            turns.append(current)
            current = []
        current.append(m)
    if current:
        turns.append(current)
    return turns


def _first_user_content(turn: list[ChatCompletionMessageParam]) -> str:
    for m in turn:
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c
            return str(c)
    return ""


def _truncate_first_user_in_place(
    turn: list[ChatCompletionMessageParam],
    max_content_chars: int,
) -> list[ChatCompletionMessageParam]:
    """Return a copy of turn with first user string content truncated if needed."""
    out = deepcopy(turn)
    for m in out:
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            c = m["content"]
            if not isinstance(c, str):
                break
            if max_content_chars <= 0:
                m["content"] = "…"
            elif len(c) > max_content_chars:
                m["content"] = c[: max_content_chars - 1] + "…"
            break
    return out


def _compaction_notice(*, omitted_turns: int, omitted_chars: int, task_preview: str) -> str:
    preview = task_preview.strip()
    if len(preview) > 2000:
        preview = preview[:1999] + "…"
    return (
        "[History compaction]\n"
        f"Omitted {omitted_turns} middle turn(s) (~{omitted_chars} characters) to stay "
        "within the configured context budget. The original task and the most recent "
        "messages are preserved.\n"
        f"Original task (anchor): {preview}"
    )


def _truncate_single_turn_to_fit(
    turn: list[ChatCompletionMessageParam],
    max_chars: int,
) -> list[ChatCompletionMessageParam]:
    """Binary search truncate first user content until the turn fits max_chars."""
    lo, hi = 0, max_chars
    best = _truncate_first_user_in_place(deepcopy(turn), 0)
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = _truncate_first_user_in_place(deepcopy(turn), mid)
        if estimate_messages_chars(candidate) <= max_chars:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def compact_prior_messages(
    messages: list[ChatCompletionMessageParam],
    *,
    max_chars: int,
) -> tuple[list[ChatCompletionMessageParam], bool]:
    """
    Return ``(possibly_compacted, did_compact)``.

    ``messages`` must not include the system prompt (only user/assistant/tool).
    """
    if not messages:
        return messages, False
    max_chars = max(512, max_chars)

    total = estimate_messages_chars(messages)
    if total <= max_chars:
        return messages, False

    turns = split_into_turns(messages)
    if not turns:
        return messages, False

    first_turn = deepcopy(turns[0])
    rest = turns[1:]

    # Single accumulated turn: only truncate first user content
    if not rest:
        return _truncate_single_turn_to_fit(first_turn, max_chars), True

    first_task = _first_user_content(first_turn)
    rlen = len(rest)

    step = max(1, max_chars // 128)
    for budget in range(max_chars, -1, -step):
        ft = _truncate_first_user_in_place(deepcopy(first_turn), budget)
        for k in range(rlen, -1, -1):
            tail = rest[-k:] if k else []
            omitted = rest if k == 0 else rest[:-k]
            omitted_chars = sum(estimate_messages_chars(t) for t in omitted)
            notice_msg = {
                "role": "user",
                "content": _compaction_notice(
                    omitted_turns=len(omitted),
                    omitted_chars=omitted_chars,
                    task_preview=_first_user_content(ft),
                ),
            }
            candidate = [
                *ft,
                notice_msg,
                *[m for t in tail for m in t],
            ]
            if estimate_messages_chars(candidate) <= max_chars:
                return candidate, True

    # Last resort: minimal notice only (drops first turn text — should be extremely rare)
    notice_msg = {
        "role": "user",
        "content": _compaction_notice(
            omitted_turns=rlen + 1,
            omitted_chars=total,
            task_preview="(truncated)",
        ),
    }
    return [notice_msg], True
