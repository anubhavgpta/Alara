"""Secret storage via the system keyring.

All secrets are stored under the "alara" service. Key names are logged at
DEBUG level; secret values are never logged.
"""

import logging

import keyring

logger = logging.getLogger(__name__)

_SERVICE = "alara"


def set_secret(key: str, value: str) -> None:
    """Store a secret in the system keyring."""
    logger.debug("Setting secret: %s", key)
    keyring.set_password(_SERVICE, key, value)


# Alias used by Composio setup code.
store_secret = set_secret


def get_secret(key: str) -> str | None:
    """Retrieve a secret from the system keyring. Returns None if not found."""
    logger.debug("Getting secret: %s", key)
    return keyring.get_password(_SERVICE, key)


def delete_secret(key: str) -> None:
    """Delete a secret from the system keyring."""
    logger.debug("Deleting secret: %s", key)
    try:
        keyring.delete_password(_SERVICE, key)
    except keyring.errors.PasswordDeleteError:
        logger.debug("Secret not found for deletion: %s", key)
