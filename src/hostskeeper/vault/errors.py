"""Vault-specific errors."""


class VaultError(Exception):
    """Base vault error."""


class InvalidPasswordError(VaultError):
    """Password does not decrypt the vault."""


class VaultLockedError(VaultError):
    """Operation requires an unlocked vault."""


class VaultExistsError(VaultError):
    """Vault file already exists."""


class NotFoundError(VaultError):
    """Entity id/name not found."""


class ValidationError(VaultError):
    """Invalid entity or relationship."""
