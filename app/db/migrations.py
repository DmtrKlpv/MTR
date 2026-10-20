"""Инициализация и миграции двух баз данных.

Версионирование через PRAGMA user_version:
    0 — пустая база;
    1 — базовая схема (mtr_users / mtr_music);
    2 — сессии веб-интерфейса (только mtr_users);

Миграции применяются по порядку и идемпотентны: повторный запуск
на уже актуальной базе ничего не делает. DDL внутри каждого шага
выполняется под транзакцией, а версия выставляется только после успеха.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import MUSIC_DB_NAME, USERS_DB_NAME
from app.db.database import Database, DatabaseError

logger = logging.getLogger(__name__)

SCHEMA_DIR = Path(__file__).resolve().parent

# Текущая целевая версия схемы для обеих баз.
SCHEMA_VERSION = 2

# v2: сессии веб-интерфейса. В v1 таблица sessions уже есть, но хранит
# открытый id и не умеет CSRF. Миграция перестраивает её:
#   * token_hash  — SHA-256 токена из cookie (открытый токен не храним);
#   * csrf_token  — привязка CSRF к сессии;
#   * id INTEGER  — внутренний ключ вместо TEXT.
# Старые сессии удаляются: они всё равно недействительны без token_hash,
# а таблица на этом этапе пуста (веб-интерфейса ещё не было).
MIGRATION_V2_SESSIONS = """
DROP TABLE IF EXISTS sessions;
CREATE TABLE sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash   TEXT    NOT NULL UNIQUE,
    user_id      INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    csrf_token   TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    expires_at   TEXT    NOT NULL,
    last_seen_at TEXT    NOT NULL,
    user_agent   TEXT,
    ip           TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_sessions_expires ON sessions (expires_at);
"""


def _read_schema(filename: str) -> str:
    """Читает SQL-скрипт схемы рядом с этим модулем."""
    path = SCHEMA_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DatabaseError(f"не удалось прочитать схему {path}: {exc}") from exc


async def _migrate_users(db: Database) -> None:
    """Приводит mtr_users.db к SCHEMA_VERSION."""
    current = await db.get_user_version()
    if current > SCHEMA_VERSION:
        raise DatabaseError(
            f"mtr_users.db имеет версию схемы {current}, а код поддерживает "
            f"только {SCHEMA_VERSION}. База создана более новой версией."
        )
    if current == SCHEMA_VERSION and current != 0:
        logger.debug("mtr_users.db уже на версии %d", current)
        return

    if current < 1:
        logger.info("mtr_users.db: применяю базовую схему (v1)")
        await db.executescript(_read_schema("schema_users.sql"))
    if current < 2:
        logger.info("mtr_users.db: применяю миграцию v2 (сессии)")
        await db.executescript(MIGRATION_V2_SESSIONS)

    await db.set_user_version(SCHEMA_VERSION)
    logger.info("mtr_users.db готова, версия схемы %d", SCHEMA_VERSION)


async def _migrate_music(db: Database) -> None:
    """Приводит mtr_music.db к SCHEMA_VERSION."""
    current = await db.get_user_version()
    if current > SCHEMA_VERSION:
        raise DatabaseError(
            f"mtr_music.db имеет версию схемы {current}, а код поддерживает "
            f"только {SCHEMA_VERSION}. База создана более новой версией."
        )
    if current == SCHEMA_VERSION and current != 0:
        logger.debug("mtr_music.db уже на версии %d", current)
        return

    if current < 1:
        logger.info("mtr_music.db: применяю базовую схему (v1)")
        await db.executescript(_read_schema("schema_music.sql"))

    await db.set_user_version(SCHEMA_VERSION)
    logger.info("mtr_music.db готова, версия схемы %d", SCHEMA_VERSION)


async def init_databases(users_db: Database, music_db: Database) -> None:
    """Открывает и мигрирует обе базы.

    Открытие идёт последовательно и с явными именами в логах: если сломается
    одна база, сообщение сразу скажет какая, а вторая останется нетронутой.
    """
    await users_db.connect()
    try:
        await _migrate_users(users_db)
    except Exception:
        await users_db.close()
        raise

    await music_db.connect()
    try:
        await _migrate_music(music_db)
    except Exception:
        await music_db.close()
        await users_db.close()
        raise

    logger.info(
        "обе базы инициализированы: %s, %s",
        users_db.path.name or USERS_DB_NAME,
        music_db.path.name or MUSIC_DB_NAME,
    )
