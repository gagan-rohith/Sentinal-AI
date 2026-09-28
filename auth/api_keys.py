"""API key authentication.

Keys are configured as SHA-256 hashes so plaintext keys never live in config:

    API_KEYS=viewer:<sha256>,operator:<sha256>,admin:<sha256>

Generate a key and its config entry with:

    python -m auth.api_keys admin
"""

import hashlib
import secrets
import sys

from auth.permissions import Principal
from core.enums import Role

KEY_PREFIX = "sk_sentinel_"


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def parse_key_config(config: str) -> dict[str, Role]:
    """Parse 'role:hash,role:hash' into {hash: role}."""
    keys: dict[str, Role] = {}
    roles = ", ".join(r.value for r in Role)
    for position, entry in enumerate(
        filter(None, (part.strip() for part in config.split(","))), start=1
    ):
        # Error messages never include the entry itself: it may be a pasted secret.
        if entry.startswith(KEY_PREFIX):
            raise ValueError(
                f"API_KEYS entry {position} is a plaintext key; use the 'config:' line "
                "printed by python -m auth.api_keys, not the 'key:' line"
            )
        role, sep, digest = entry.partition(":")
        if not sep or len(digest) != 64 or role not in {r.value for r in Role}:
            raise ValueError(
                f"API_KEYS entry {position} is not in the form role:sha256 "
                f"(role one of {roles}, then 64 hex characters)"
            )
        keys[digest.lower()] = Role(role)
    return keys


class ApiKeyAuthenticator:
    def __init__(self, hashed_keys: dict[str, Role]) -> None:
        self._keys = hashed_keys

    def authenticate(self, raw_key: str) -> Principal | None:
        digest = hash_key(raw_key)
        role = self._keys.get(digest)
        if role is None:
            return None
        return Principal(subject=f"apikey:{digest[:8]}", role=role, auth_method="api_key")


def main() -> None:
    role = Role(sys.argv[1]) if len(sys.argv) > 1 else Role.OPERATOR
    key = generate_key()
    print(f"key:    {key}")
    print(f"config: {role.value}:{hash_key(key)}")


if __name__ == "__main__":
    main()
