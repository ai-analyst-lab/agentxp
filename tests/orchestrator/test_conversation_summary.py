"""Tests for the W2 conversation extensions — summary/commitments metadata
and the prior_turns_compressed shape per §10.8.1.

ConversationStore already accepts a free-form ``metadata`` dict on every
turn (§1.8.12). These tests pin the W2 contract: the field accepts the
``{"summary": str, "commitments": [str]}`` shape, ``read_since`` is usable
for assembling a compressed prior-turns block, and turn_ids are strictly
sortable (so conversation_ref through_turn_id works).
"""
from __future__ import annotations

from pathlib import Path

from openxp.orchestrator.conversation import ConversationStore


def test_conversation_turn_accepts_summary_metadata(tmp_path: Path):
    store = ConversationStore(tmp_path / "conversation.jsonl")
    turn_id = store.append(
        actor="user",
        agent_name=None,
        content="I want to test the new checkout button.",
        metadata={
            "summary": "user said they want to test the checkout button",
            "commitments": ["chose A=control"],
        },
    )
    turns = store.read_all()
    assert len(turns) == 1
    assert turns[0].turn_id == turn_id
    assert turns[0].metadata is not None
    assert turns[0].metadata["summary"].startswith("user said")
    assert turns[0].metadata["commitments"] == ["chose A=control"]


def test_conversation_ref_validator_with_through_turn_id(tmp_path: Path):
    store = ConversationStore(tmp_path / "conversation.jsonl")
    t1 = store.append(actor="user", agent_name=None, content="first")
    t2 = store.append(actor="agent", agent_name="profiler", content="second")
    t3 = store.append(actor="user", agent_name=None, content="third")

    # turn_ids must be strictly increasing in insertion order so a
    # conversation_ref(through_turn_id=t2) is well-defined.
    assert t1 < t2 < t3

    # read_since returns turns strictly after the given turn_id.
    after_t2 = store.read_since(t2)
    assert [t.turn_id for t in after_t2] == [t3]

    # read_all up through t2 — the assembly side of conversation_ref.
    all_turns = store.read_all()
    through_t2 = [t for t in all_turns if t.turn_id <= t2]
    assert [t.turn_id for t in through_t2] == [t1, t2]


def test_prior_turns_compressed_shape(tmp_path: Path):
    """The §10.8.1 prior_turns_compressed block is a list of dicts shaped
    like {ts, actor, summary, commitments[]} drawn from turn.metadata.
    This test pins the assembly recipe so consumers (consistency_judge,
    designer.drafter) see a stable schema.
    """
    store = ConversationStore(tmp_path / "conversation.jsonl")
    store.append(
        actor="user",
        agent_name=None,
        content="I want primary_metric=time_to_checkout_p95.",
        metadata={
            "summary": "user proposed primary_metric=time_to_checkout_p95",
            "commitments": ["primary_metric=time_to_checkout_p95"],
        },
    )
    store.append(
        actor="agent",
        agent_name="designer.drafter",
        content="Drafted brief with that metric.",
        metadata={
            "summary": "designer drafted brief using time_to_checkout_p95",
            "commitments": [],
        },
    )

    turns = store.read_all()
    compressed = [
        {
            "ts": t.ts.isoformat(),
            "actor": t.actor,
            "summary": (t.metadata or {}).get("summary", ""),
            "commitments": (t.metadata or {}).get("commitments", []),
        }
        for t in turns
    ]
    assert len(compressed) == 2
    assert compressed[0]["actor"] == "user"
    assert "time_to_checkout_p95" in compressed[0]["summary"]
    assert compressed[0]["commitments"] == ["primary_metric=time_to_checkout_p95"]
    assert compressed[1]["actor"] == "agent"
