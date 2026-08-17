"""Tests for Ed25519 receipt signing (optional authenticity layer)."""
from __future__ import annotations

import pytest

from heatreserve.signing import (
    get_public_key_hex,
    is_signing_available,
    sign_canonical_digest,
    verify_signature,
)


DIGEST_HEX = "a" * 64  # 32 bytes, arbitrary


@pytest.mark.skipif(not is_signing_available(), reason="cryptography package not installed")
class TestEd25519Signing:
    def _generate_key(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        return Ed25519PrivateKey.generate()

    def test_sign_and_verify_roundtrip(self):
        key = self._generate_key()
        pub_hex = get_public_key_hex(key)
        sig_info = sign_canonical_digest(key, DIGEST_HEX, "test-key-1")
        result = verify_signature(pub_hex, DIGEST_HEX, sig_info)
        assert result["authenticity_checked"] is True
        assert result["authenticity_valid"] is True

    def test_wrong_digest_fails_verification(self):
        key = self._generate_key()
        pub_hex = get_public_key_hex(key)
        sig_info = sign_canonical_digest(key, DIGEST_HEX, "key-1")
        wrong_digest = "b" * 64
        result = verify_signature(pub_hex, wrong_digest, sig_info)
        assert result["authenticity_checked"] is True
        assert result["authenticity_valid"] is False

    def test_missing_signature_not_checked(self):
        result = verify_signature(None, DIGEST_HEX, {})
        assert result["authenticity_checked"] is False
        assert result["authenticity_valid"] is False

    def test_no_public_key_not_checked(self):
        key = self._generate_key()
        sig_info = sign_canonical_digest(key, DIGEST_HEX, "key-1")
        result = verify_signature(None, DIGEST_HEX, sig_info)
        assert result["authenticity_checked"] is False

    def test_tampered_signature_fails(self):
        key = self._generate_key()
        pub_hex = get_public_key_hex(key)
        sig_info = sign_canonical_digest(key, DIGEST_HEX, "key-1")
        # Flip a bit in the signature
        tampered = dict(sig_info)
        sig_bytes = bytes.fromhex(tampered["signature"])
        tampered["signature"] = bytes([sig_bytes[0] ^ 1]) + sig_bytes[1:]
        tampered["signature"] = tampered["signature"].hex()
        result = verify_signature(pub_hex, DIGEST_HEX, tampered)
        assert result["authenticity_valid"] is False


class TestSigningUnavailable:
    def test_unsigned_receipt_not_checked(self):
        result = verify_signature(None, DIGEST_HEX, {})
        assert result["authenticity_checked"] is False
        assert result["authenticity_valid"] is False
