# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.md.

"""
Authentication for Web UI – HTTP Basic Auth.
On first start, generates initial credentials and prints to console.
Password is stored as salted SHA-256 in config.
"""
import hashlib
import hmac
import secrets
from .config import Config


class AuthManager:
    def __init__(self, config: Config):
        self.config = config
        self._generated_password: str | None = None
        if not config.auth_password_hash:
            self._init_credentials()

    def _init_credentials(self):
        password = secrets.token_urlsafe(12)
        self._generated_password = password
        self.config.auth_password_hash = self._hash_password(password)
        self.config.save()
        self._print_credentials(password)

    def reset_password(self) -> str:
        """Force-generate a new password. Returns the plaintext password."""
        password = secrets.token_urlsafe(12)
        self._generated_password = password
        self.config.auth_password_hash = self._hash_password(password)
        self.config.save()
        self._print_credentials(password)
        return password

    @staticmethod
    def _print_credentials(password: str):
        print()
        print("=" * 50)
        print("  ADMIN CREDENTIALS")
        print(f"  Username: admin")
        print(f"  Password: {password}")
        print("  Change via Web UI > Security")
        print("=" * 50)
        print()

        # Write to file so install script can reliably read it
        try:
            from pathlib import Path
            cred_file = Path("/data/.admin_password")
            cred_file.write_text(password)
        except Exception:
            pass

    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return f"{salt}:{h}"

    def verify(self, username: str, password: str) -> bool:
        if username != self.config.auth_username:
            return False
        stored = self.config.auth_password_hash
        if not stored or ":" not in stored:
            return False
        salt, expected_hash = stored.split(":", 1)
        actual_hash = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return hmac.compare_digest(actual_hash, expected_hash)

    def change_password(self, old_password: str, new_password: str) -> bool:
        if not self.verify(self.config.auth_username, old_password):
            return False
        self.config.auth_password_hash = self._hash_password(new_password)
        self.config.save()
        return True
