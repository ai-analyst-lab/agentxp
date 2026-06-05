"""Sha256Hex behavioral tests — placeholder values + bad-length inputs are refused.

v0.1 cleanup W0.1 (audit B3) — replaces ad-hoc ``str + min/max_length=64``
constraints with a single pattern-validated type. These tests pin the refusal
behavior.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from agentxp.schemas._types import Sha256Hex


class _Witness(BaseModel):
    h: Sha256Hex


_VALID_HEX = "a" * 64                       # 64 lowercase hex chars
_VALID_HEX_MIXED = "0123456789abcdef" * 4  # 64 chars, real-looking digest


def test_accepts_64_lowercase_hex() -> None:
    """A real 64-char lowercase hex digest validates."""
    _Witness(h=_VALID_HEX)
    _Witness(h=_VALID_HEX_MIXED)


def test_rejects_placeholder_literal() -> None:
    """The original audit B3 finding: '<pending>' was accepted. Now refused."""
    with pytest.raises(ValidationError):
        _Witness(h="<pending>")


def test_rejects_empty_string() -> None:
    with pytest.raises(ValidationError):
        _Witness(h="")


def test_rejects_63_char_hex() -> None:
    """Off-by-one short → refused."""
    with pytest.raises(ValidationError):
        _Witness(h="a" * 63)


def test_rejects_65_char_hex() -> None:
    """Off-by-one long → refused."""
    with pytest.raises(ValidationError):
        _Witness(h="a" * 65)


def test_rejects_uppercase_hex() -> None:
    """Pattern requires lowercase a-f; uppercase rejected."""
    with pytest.raises(ValidationError):
        _Witness(h="A" * 64)


def test_rejects_non_hex_chars() -> None:
    """Any non-hex character (e.g. 'g') refused."""
    with pytest.raises(ValidationError):
        _Witness(h="g" * 64)


def test_rejects_whitespace() -> None:
    with pytest.raises(ValidationError):
        _Witness(h="  " + ("a" * 60) + "  ")
