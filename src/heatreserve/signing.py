"""
Optional Ed25519 receipt signing.

When HEATRESERVE_RECEIPT_SIGNING_KEY_PATH is configured, receipts are
signed with the private key and verification can establish authenticity.

Without a signing key, receipts still have SHA-256 integrity (tamper detection)
but authenticity is not checked. This is clearly reported in verification output.

INVARIANT: unsigned Judge Mode receipts are never falsely called "digitally signed."
Verification output always explicitly states which checks were performed.

Key generation (run once, store securely, never commit):
  python -c "
  from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
  from cryptography.hazmat.primitives.serialization import (
      Encoding, PrivateFormat, NoEncryption
  )
  key = Ed25519PrivateKey.generate()
  pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
  print(pem.decode())
  " > receipt_signing_key.pem
"""
from __future__ import annotations

import logging
from pathlib import Path

LOGGER = logging.getLogger("heatreserve.signing")

_ALGORITHM = "Ed25519"


def _load_cryptography():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            PublicFormat,
            load_pem_private_key,
        )
        return (
            Ed25519PrivateKey, Ed25519PublicKey,
            load_pem_private_key, Encoding, PrivateFormat, PublicFormat, NoEncryption,
        )
    except ImportError:
        return None


def is_signing_available() -> bool:
    return _load_cryptography() is not None


def load_signing_key(key_path: Path):
    """Load Ed25519 private key from PEM file. Returns key object or None."""
    mods = _load_cryptography()
    if mods is None:
        LOGGER.warning("signing.unavailable: cryptography package not installed")
        return None
    _, _, load_pem_private_key, _, _, _, _ = mods
    try:
        pem_bytes = key_path.read_bytes()
        private_key = load_pem_private_key(pem_bytes, password=None)
        LOGGER.info("signing.key_loaded path=%s", key_path)
        return private_key
    except (OSError, ValueError, TypeError) as exc:
        LOGGER.error("signing.key_load_failed path=%s error=%s", key_path, exc)
        return None


def sign_canonical_digest(private_key, digest_hex: str, key_id: str) -> dict[str, str]:
    """
    Sign the receipt's canonical SHA-256 digest with Ed25519.
    Returns a dict with signature, key_id, algorithm to embed in the receipt.
    """
    mods = _load_cryptography()
    if mods is None or private_key is None:
        raise RuntimeError("Signing not available")
    try:
        signature_bytes = private_key.sign(bytes.fromhex(digest_hex))
        return {
            "signature": signature_bytes.hex(),
            "key_id": key_id,
            "algorithm": _ALGORITHM,
        }
    except Exception as exc:
        raise RuntimeError(f"Signing failed: {exc}") from exc


def verify_signature(
    public_key_bytes_hex: str | None,
    digest_hex: str,
    signature_info: dict[str, str],
) -> dict[str, bool | str]:
    """
    Verify an Ed25519 signature against a canonical digest.

    In Judge Mode without a configured signer:
      authenticity_checked = False  (not an error — just not configured)

    Returns explicit booleans for integrity vs authenticity.
    """
    if not signature_info or not signature_info.get("signature"):
        return {
            "authenticity_checked": False,
            "authenticity_valid": False,
            "reason": "no_signature_present",
        }

    mods = _load_cryptography()
    if mods is None:
        return {
            "authenticity_checked": False,
            "authenticity_valid": False,
            "reason": "cryptography_package_unavailable",
        }

    if not public_key_bytes_hex:
        return {
            "authenticity_checked": False,
            "authenticity_valid": False,
            "reason": "no_public_key_configured",
        }

    _, Ed25519PublicKey, _, Encoding, _, PublicFormat, _ = mods
    try:
        from cryptography.hazmat.primitives.serialization import load_der_public_key
        pub_key = load_der_public_key(bytes.fromhex(public_key_bytes_hex))
        sig_bytes = bytes.fromhex(signature_info["signature"])
        pub_key.verify(sig_bytes, bytes.fromhex(digest_hex))
        return {
            "authenticity_checked": True,
            "authenticity_valid": True,
            "key_id": signature_info.get("key_id", "unknown"),
            "algorithm": signature_info.get("algorithm", "unknown"),
        }
    except Exception as exc:
        return {
            "authenticity_checked": True,
            "authenticity_valid": False,
            "reason": str(exc),
        }


def get_public_key_hex(private_key) -> str | None:
    """Extract the public key as hex-encoded DER bytes from a private key."""
    mods = _load_cryptography()
    if mods is None or private_key is None:
        return None
    _, _, _, Encoding, _, PublicFormat, _ = mods
    try:
        pub = private_key.public_key()
        return pub.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo).hex()
    except Exception:
        return None
