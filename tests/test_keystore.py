"""Unit-Tests fuer den Keystore (Envelope-Verschluesselung der per-user DBs).

At rest darf weder das Server-Secret noch die Keystore-Datei allein den DEK preisgeben -
nur das Passwort des Users (KEK = Argon2id(password, salt)).
"""

from __future__ import annotations

import base64

import pytest

from app.db.keystore import KeyStore


@pytest.fixture()
def ks(tmp_path):
    return KeyStore(tmp_path / "keystore.db")


def test_create_unwrap_roundtrip(ks):
    dek = ks.create("u@example.com", "uid1", "pw")
    assert len(base64.urlsafe_b64decode(dek)) == 32
    assert ks.unwrap("u@example.com", "pw") == dek
    assert ks.unwrap("u@example.com", "falsch") is None
    assert ks.unwrap("unbekannt@example.com", "pw") is None


def test_wrapped_blob_at_rest_does_not_contain_dek(ks, tmp_path):
    """Die Keystore-Datei enthaelt den DEK weder im Klartext noch dekodierbar."""
    dek = ks.create("u@example.com", "uid1", "pw")
    raw = (tmp_path / "keystore.db").read_bytes()
    assert dek.encode() not in raw
    assert base64.urlsafe_b64decode(dek) not in raw


def test_rewrap_keeps_dek(ks):
    """Passwort-Wechsel re-wrappen: DEK bleibt gleich -> DB bleibt lesbar."""
    dek = ks.create("u@example.com", "uid1", "pw-alt")
    assert ks.rewrap("u@example.com", "pw-alt", "pw-neu") is True
    assert ks.unwrap("u@example.com", "pw-alt") is None
    assert ks.unwrap("u@example.com", "pw-neu") == dek
    assert ks.rewrap("u@example.com", "pw-alt", "x") is False  # altes Passwort unwrappt nicht mehr


def test_delete(ks):
    ks.create("u@example.com", "uid1", "pw")
    ks.delete("u@example.com")
    assert ks.get("u@example.com") is None
    assert ks.unwrap("u@example.com", "pw") is None
