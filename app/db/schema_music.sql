-- =====================================================================
-- mtr_music.db — DATA PLANE
-- Метаданные медиатеки, плейлисты, статистика прослушиваний, лог сканов.
-- Ссылки на пользователей (owner_id, user_id) — МЯГКИЕ: целые числа без
-- FOREIGN KEY, потому что users живут в другом файле SQLite. Валидность
-- владельца проверяется в Python при чтении (см. repositories/playlists.py).
--
-- Главный инвариант переиндексации:
--   * tracks.id — суррогатный PK, никогда не переиспользуется (AUTOINCREMENT);
--   * стабильный ключ трека — путь (UNIQUE), а не id;
--   * upsert идёт по пути, поэтому ресканирование НЕ сдвигает id и не
--     обнуляет плейлисты;
--   * исчезнувший файл помечается missing=1, а не удаляется, чтобы
--     плейлисты и история прослушиваний не теряли ссылки.
-- =====================================================================

PRAGMA foreign_keys = ON;

-- Исполнители (альбомные исполнители и исполнители треков сводятся сюда).
CREATE TABLE IF NOT EXISTS artists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL COLLATE NOCASE,
    sort_name   TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_artists_name ON artists (name COLLATE NOCASE);

-- Альбомы.
CREATE TABLE IF NOT EXISTS albums (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL COLLATE NOCASE,
    artist_id    INTEGER REFERENCES artists (id) ON DELETE SET NULL,
    year         INTEGER,
    genre        TEXT,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_albums_name_artist
    ON albums (name COLLATE NOCASE, artist_id);
CREATE INDEX IF NOT EXISTS ix_albums_artist ON albums (artist_id);

-- Треки.
--   duration_ms — целое, миллисекунды (mutagen отдаёт float-секунды).
--   path        — абсолютный путь в Linux-нотации, /music/...
--   mtime       — время модификации файла (unix-время, REAL)
--   content_hash— sha1 содержимого, заполняется лениво (для поиска дублей
--                 и для обнаружения «тот же файл, переименован»)
CREATE TABLE IF NOT EXISTS tracks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path            TEXT    NOT NULL,
    filename        TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    artist          TEXT,
    artist_id       INTEGER REFERENCES artists (id) ON DELETE SET NULL,
    album_artist    TEXT,
    album           TEXT,
    album_id        INTEGER REFERENCES albums (id) ON DELETE SET NULL,
    track_number    INTEGER,
    disc_number     INTEGER,
    year            INTEGER,
    genre           TEXT,
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    bitrate         INTEGER,
    sample_rate     INTEGER,
    channels        INTEGER,
    format          TEXT,
    size_bytes      INTEGER NOT NULL DEFAULT 0,
    mtime           REAL    NOT NULL DEFAULT 0,
    content_hash    TEXT,
    has_cover       INTEGER NOT NULL DEFAULT 0 CHECK (has_cover IN (0, 1)),
    missing         INTEGER NOT NULL DEFAULT 0 CHECK (missing IN (0, 1)),
    added_at        TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

-- Стабильный ключ трека. upsert при сканировании идёт ИМЕННО по нему.
CREATE UNIQUE INDEX IF NOT EXISTS ux_tracks_path ON tracks (path);
CREATE INDEX IF NOT EXISTS ix_tracks_artist ON tracks (artist);
CREATE INDEX IF NOT EXISTS ix_tracks_album ON tracks (album);
CREATE INDEX IF NOT EXISTS ix_tracks_album_id ON tracks (album_id);
CREATE INDEX IF NOT EXISTS ix_tracks_artist_id ON tracks (artist_id);
CREATE INDEX IF NOT EXISTS ix_tracks_missing ON tracks (missing);
CREATE INDEX IF NOT EXISTS ix_tracks_added_at ON tracks (added_at);
CREATE INDEX IF NOT EXISTS ix_tracks_title ON tracks (title COLLATE NOCASE);

-- Плейлисты (статические и умные).
--   owner_id    — МЯГКАЯ ссылка на users.id из mtr_users.db (без FK).
--   is_smart    — 1 для динамических плейлистов.
--   smart_rules — JSON с фильтрами, напр.
--                 {"sort": "play_count", "order": "desc", "limit": 100,
--                  "filters": [{"field": "play_count", "op": "gt", "value": 10}]}
CREATE TABLE IF NOT EXISTS playlists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id    INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    comment     TEXT,
    is_public   INTEGER NOT NULL DEFAULT 0 CHECK (is_public IN (0, 1)),
    is_smart    INTEGER NOT NULL DEFAULT 0 CHECK (is_smart IN (0, 1)),
    smart_rules TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_playlists_owner ON playlists (owner_id);
CREATE INDEX IF NOT EXISTS ix_playlists_public ON playlists (is_public);

-- Состав статического плейлиста.
--   Суррогатный id вместо составного PK — упрощает переупорядочивание:
--   position можно переписывать пачкой без конфликтов уникальности.
CREATE TABLE IF NOT EXISTS playlist_tracks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL REFERENCES playlists (id) ON DELETE CASCADE,
    track_id    INTEGER NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    added_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_playlist_tracks_playlist
    ON playlist_tracks (playlist_id, position);
CREATE INDEX IF NOT EXISTS ix_playlist_tracks_track
    ON playlist_tracks (track_id);

-- Журнал прослушиваний: источник для смарт-плейлистов и статистики.
CREATE TABLE IF NOT EXISTS playback_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id     INTEGER NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL,  -- мягкая ссылка на users.id
    played_at    TEXT    NOT NULL,
    client       TEXT,
    played_ms    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_playback_track ON playback_log (track_id);
CREATE INDEX IF NOT EXISTS ix_playback_user ON playback_log (user_id, played_at);
CREATE INDEX IF NOT EXISTS ix_playback_played_at ON playback_log (played_at);

-- Агрегат по треку: держим отдельно, чтобы смарт-фильтр play_count > N
-- не превращался в COUNT(*) по всему журналу.
CREATE TABLE IF NOT EXISTS play_stats (
    track_id       INTEGER PRIMARY KEY REFERENCES tracks (id) ON DELETE CASCADE,
    play_count     INTEGER NOT NULL DEFAULT 0,
    last_played_at TEXT,
    updated_at     TEXT    NOT NULL
);

-- Звёздочки и оценки — персональные, поэтому user_id в мягкой ссылке.
CREATE TABLE IF NOT EXISTS track_stars (
    user_id   INTEGER NOT NULL,
    track_id  INTEGER NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    starred_at TEXT   NOT NULL,
    PRIMARY KEY (user_id, track_id)
);

CREATE TABLE IF NOT EXISTS track_ratings (
    user_id   INTEGER NOT NULL,
    track_id  INTEGER NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    rating    INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    rated_at  TEXT    NOT NULL,
    PRIMARY KEY (user_id, track_id)
);

-- Кэш обложек: ключ вида "album:12" / "track:340" / "artist:5",
-- файл лежит в COVERS_DIR. Сами байты в SQLite не кладём.
CREATE TABLE IF NOT EXISTS cover_cache (
    key        TEXT PRIMARY KEY,
    file_path  TEXT    NOT NULL,
    mime_type  TEXT    NOT NULL,
    size_bytes INTEGER NOT NULL,
    source     TEXT,
    created_at TEXT    NOT NULL
);

-- История сканирований: питает прогресс-бар и вкладку «Сканер».
CREATE TABLE IF NOT EXISTS scan_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    mode          TEXT    NOT NULL CHECK (mode IN ('full', 'incremental', 'watch')),
    status        TEXT    NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    started_at    TEXT    NOT NULL,
    finished_at   TEXT,
    files_seen    INTEGER NOT NULL DEFAULT 0,
    files_added   INTEGER NOT NULL DEFAULT 0,
    files_updated INTEGER NOT NULL DEFAULT 0,
    files_removed INTEGER NOT NULL DEFAULT 0,
    files_failed  INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    -- Тексты ошибок по файлам (список строк в JSON, обрезается при записи).
    -- errors_total хранит полное число, даже если в JSON попали не все.
    errors_total  INTEGER NOT NULL DEFAULT 0,
    errors_json   TEXT
);

CREATE INDEX IF NOT EXISTS ix_scan_runs_started ON scan_runs (started_at DESC);

-- Импортированные/экспортированные .m3u8: чтобы сканер не переимпортировал
-- один и тот же файл на каждом проходе.
CREATE TABLE IF NOT EXISTS m3u_imports (
    path         TEXT PRIMARY KEY,
    playlist_id  INTEGER REFERENCES playlists (id) ON DELETE SET NULL,
    mtime        REAL    NOT NULL,
    imported_at  TEXT    NOT NULL
);
