"""Криптография паролей.

Две независимые формы одного пароля — это осознанное решение, а не
дублирование:

1. `password_enc` — Fernet (AES-128-CBC + HMAC-SHA256), обратимо.
   Subsonic-авторизация требует вычислить md5(password + salt), то есть
   серверу нужен сам пароль в открытом виде. Хэш здесь не подходит
   принципиально: из bcrypt/PBKDF2 пароль не восстановить.

2. `password_hash` — PBKDF2-HMAC-SHA256 с солью, необратимо.
   Используется для веб-логина и как индикатор «пароль не менялся»,
   чтобы не расшифровывать Fernet без необходимости.

Ключ Fernet берётся из env MTR_SECRET_KEY (произвольная строка, из неё
выводится 32-байтный ключ через HKDF) либо из файла MTR_SECRET_KEY_FILE.
При первом запуске файл создаётся автоматически с правами 0600.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger(__name__)

# Параметры PBKDF2. 600k итераций — рекомендация OWASP для SHA-256.
PBKDF2_ITERATIONS = 600_000
PBKDF2_SALT_BYTES = 16
PBKDF2_PREFIX = "pbkdf2_sha256"

_HKDF_INFO = b"mtr-music-server/fernet-key/v1"


class CryptoError(RuntimeError):
    """Ошибка шифрования/расшифровки или конфигурации ключа."""


def _derive_fernet_key(secret: str) -> bytes:
    """Выводит валидный Fernet-ключ из произвольной строки.

    Fernet требует 32 байта в base64. HKDF-SHA256 даёт предсказуемый
    результат для любой длины входной строки — так парольная фраза
    «мой-секрет-2026» превращается в корректный ключ.
    """
    if not secret:
        raise CryptoError("пустой секрет недопустим")
    raw = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_HKDF_INFO,
    ).derive(secret.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def load_or_create_secret(env_secret: str | None, key_file: Path) -> str:
    """Возвращает секрет для вывода ключа.

    Приоритет: env-переменная -> файл -> генерация нового файла.
    Новый файл создаётся атомарно и с правами 0600.
    """
    if env_secret:
        logger.info("ключ шифрования взят из переменной окружения")
        return env_secret

    key_file = Path(key_file)
    if key_file.exists():
        try:
            value = key_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise CryptoError(f"не удалось прочитать {key_file}: {exc}") from exc
        if not value:
            raise CryptoError(f"файл ключа {key_file} пуст")
        logger.info("ключ шифрования прочитан из %s", key_file)
        return value

    # Генерируем новый секрет.
    value = secrets.token_urlsafe(48)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = key_file.with_suffix(key_file.suffix + ".tmp")

    # Атомарная запись: сначала в tmp с правами 0600, потом rename.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, key_file)
    except OSError as exc:
        raise CryptoError(f"не удалось создать файл ключа {key_file}: {exc}") from exc
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)

    try:
        os.chmod(key_file, 0o600)
    except OSError:  # pragma: no cover - на некоторых ФС не поддерживается
        logger.warning("не удалось выставить права 0600 на %s", key_file)

    logger.warning(
        "сгенерирован новый ключ шифрования в %s — сделайте бэкап, "
        "иначе сохранённые пароли станут нечитаемыми", key_file,
    )
    return value


class PasswordCipher:
    """Шифрование и хэширование паролей."""

    def __init__(self, secret: str) -> None:
        self._fernet = Fernet(_derive_fernet_key(secret))

    # --- обратимое шифрование (для Subsonic token-авторизации) ---------
    def encrypt(self, password: str) -> str:
        """Шифрует пароль, возвращает base64-строку для password_enc."""
        if not isinstance(password, str) or password == "":
            raise CryptoError("пароль не может быть пустым")
        token = self._fernet.encrypt(password.encode("utf-8"))
        return token.decode("ascii")

    def decrypt(self, token: str) -> str:
        """Расшифровывает password_enc.

        InvalidToken почти всегда означает «ключ сменился» или «файл БД
        принесли с другого инстанса» — сообщаем это явно, а не глотаем.
        """
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise CryptoError(
                "не удалось расшифровать пароль: ключ шифрования не совпадает "
                "с тем, которым база была зашифрована"
            ) from exc

    # --- необратимое хэширование (для веб-логина) ----------------------
    @staticmethod
    def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
        """Возвращает строку вида pbkdf2_sha256$600000$salt_b64$hash_b64."""
        if not isinstance(password, str) or password == "":
            raise CryptoError("пароль не может быть пустым")
        salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return "$".join(
            (
                PBKDF2_PREFIX,
                str(iterations),
                base64.b64encode(salt).decode("ascii"),
                base64.b64encode(digest).decode("ascii"),
            )
        )

    @staticmethod
    def verify_password(password: str, stored: str) -> bool:
        """Сверяет пароль с хэшем. Сравнение — постоянное по времени."""
        if not password or not stored:
            return False
        try:
            prefix, iterations_raw, salt_b64, hash_b64 = stored.split("$", 3)
            if prefix != PBKDF2_PREFIX:
                logger.error("неизвестный формат хэша пароля: %s", prefix)
                return False
            iterations = int(iterations_raw)
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(hash_b64)
        except (ValueError, TypeError):
            logger.error("повреждённый хэш пароля в базе")
            return False

        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(actual, expected)
