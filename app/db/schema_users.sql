-- =====================================================================
-- mtr_users.db — CONTROL PLANE
-- Учётные записи, роли, сессии, пользовательские и глобальные настройки.
-- Здесь НЕТ ни одной таблицы, относящейся к музыке. Связь с mtr_music.db
-- отсутствует на уровне SQL: внешние ключи между разными файлами SQLite
-- физически невозможны. Ссылки вида playlists.owner_id разрешаются в Python.
-- =====================================================================

-- Пользователи.
--   password_enc  — пароль, зашифрованный Fernet (AES-128-CBC + HMAC).
--                   Нужен для Subsonic token-авторизации: сервер обязан
--                   посчитать md5(password + salt), т.е. знать сам пароль.
--   password_hash — PBKDF2-SHA256, используется для веб-логина и как
--                   контрольная сумма при смене пароля.
CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    username            TEXT    NOT NULL COLLATE NOCASE,
    password_enc        TEXT    NOT NULL,
    password_hash       TEXT    NOT NULL,
    role                TEXT    NOT NULL DEFAULT 'user'
                                CHECK (role IN ('admin', 'user')),
    is_active           INTEGER NOT NULL DEFAULT 1
                                CHECK (is_active IN (0, 1)),
    email               TEXT,
    display_name        TEXT,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL,
    last_login_at       TEXT,
    password_changed_at TEXT
);

-- Username уникален без учёта регистра: "Alice" и "alice" — один аккаунт.
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_username
    ON users (username COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS ix_users_role ON users (role);

-- Сессии веб-интерфейса (Subsonic-запросы stateless и сессий не требуют,
-- но админ-панели нужен устойчивый логин).
CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT    PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at   TEXT    NOT NULL,
    expires_at   TEXT    NOT NULL,
    last_seen_at TEXT    NOT NULL,
    user_agent   TEXT,
    ip_address   TEXT
);

CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_sessions_expires ON sessions (expires_at);

-- Персональные настройки пользователя (формат транскодирования по умолчанию,
-- тема оформления, размер страницы и т.п.). Значения — строки, парсятся
-- на уровне сервисов.
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id    INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    key        TEXT    NOT NULL,
    value      TEXT,
    updated_at TEXT    NOT NULL,
    PRIMARY KEY (user_id, key)
);

-- Глобальные настройки инстанса (например, включён ли watchdog-сканер,
-- формат транскодирования по умолчанию, лимит битрейта).
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT NOT NULL,
    updated_by INTEGER  -- мягкая ссылка на users.id; NULL = системное значение
);
