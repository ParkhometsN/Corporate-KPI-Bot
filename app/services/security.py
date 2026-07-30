from datetime import datetime, timedelta, timezone
from hashlib import pbkdf2_hmac, sha256
import hmac
import secrets
from typing import Any

import jwt
from cryptography.fernet import Fernet

from app.config.settings import Settings


class PasswordService:
    _algorithm = "pbkdf2_sha256"
    _iterations = 390_000
    _salt_bytes = 16

    def hash_password(self, password: str) -> str:
        salt = secrets.token_hex(self._salt_bytes)
        digest = self._derive(password, salt, self._iterations)
        return f"{self._algorithm}${self._iterations}${salt}${digest}"

    def verify_password(self, password: str, hashed_password: str) -> bool:
        try:
            algorithm, iterations, salt, expected_digest = hashed_password.split("$", maxsplit=3)
        except ValueError:
            return False
        if algorithm != self._algorithm:
            return False
        digest = self._derive(password, salt, int(iterations))
        return hmac.compare_digest(digest, expected_digest)

    @staticmethod
    def _derive(password: str, salt: str, iterations: int) -> str:
        digest = pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            iterations,
        )
        return digest.hex()


class EncryptionService:
    def __init__(self, settings: Settings) -> None:
        self._fernet = Fernet(settings.encryption_key.encode())

    def encrypt(self, value: str | None) -> str | None:
        if value is None:
            return None
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, encrypted_value: str | None) -> str | None:
        if encrypted_value is None:
            return None
        return self._fernet.decrypt(encrypted_value.encode()).decode()


class JwtService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_access_token(self, subject: str, claims: dict[str, Any] | None = None) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": subject,
            "iat": now,
            "exp": now + timedelta(minutes=self._settings.jwt_expire_minutes),
        }
        if claims:
            payload.update(claims)
        return jwt.encode(
            payload,
            self._settings.jwt_secret_key,
            algorithm=self._settings.jwt_algorithm,
        )

    def decode_access_token(self, token: str) -> dict[str, Any]:
        return jwt.decode(
            token,
            self._settings.jwt_secret_key,
            algorithms=[self._settings.jwt_algorithm],
        )


class CodeHashService:
    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret_key.encode()

    def hash_code(self, code: str) -> str:
        normalized = code.strip().upper().encode()
        return hmac.new(self._secret, normalized, sha256).hexdigest()
