"""Vault file encryption: Scrypt KDF + AES-256-GCM."""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from hostskeeper.vault.errors import InvalidPasswordError

MAGIC = b"HSVAULT1"
SALT_LEN = 16
NONCE_LEN = 12
KEY_LEN = 32
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


@dataclass(frozen=True)
class DerivedKey:
    key: bytes
    salt: bytes


def derive_key(password: str, salt: bytes | None = None) -> DerivedKey:
    if salt is None:
        salt = os.urandom(SALT_LEN)
    kdf = Scrypt(salt=salt, length=KEY_LEN, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    key = kdf.derive(password.encode("utf-8"))
    return DerivedKey(key=key, salt=salt)


def seal(plaintext: bytes, password: str) -> bytes:
    derived = derive_key(password)
    nonce = os.urandom(NONCE_LEN)
    ciphertext = AESGCM(derived.key).encrypt(nonce, plaintext, MAGIC)
    return MAGIC + derived.salt + nonce + ciphertext


def open_sealed(blob: bytes, password: str) -> bytes:
    if len(blob) < len(MAGIC) + SALT_LEN + NONCE_LEN + 16:
        raise InvalidPasswordError("vault file is truncated or corrupt")
    if blob[: len(MAGIC)] != MAGIC:
        raise InvalidPasswordError("not a HostsKeeper vault file")
    offset = len(MAGIC)
    salt = blob[offset : offset + SALT_LEN]
    offset += SALT_LEN
    nonce = blob[offset : offset + NONCE_LEN]
    offset += NONCE_LEN
    ciphertext = blob[offset:]
    derived = derive_key(password, salt=salt)
    try:
        return AESGCM(derived.key).decrypt(nonce, ciphertext, MAGIC)
    except InvalidTag as exc:
        raise InvalidPasswordError("invalid password or corrupt vault") from exc
