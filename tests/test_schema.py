"""Тесты схемы: версии, индексы, ограничения обоих файлов БД."""

from __future__ import annotations

import pytest

from app.db.migrations import MUSIC_SCHEMA_VERSION, SCHEMA_VERSION


async def test_both_databases_migrated(ctx):
    """Обе базы существуют, версия схемы выставлена, файлы на диске."""
    assert ctx.settings.users_db.exists()
    assert ctx.settings.music_db.exists()
    assert await ctx.users_db.get_user_version() == SCHEMA_VERSION
    assert await ctx.music_db.get_user_version() == MUSIC_SCHEMA_VERSION


async def test_migration_is_idempotent(ctx):
    """Повторная миграция ничего не ломает и не создаёт дублей."""
    from app.db.migrations import init_databases

    before = await ctx.music_db.fetch_value(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
    )
    await init_databases(ctx.users_db, ctx.music_db)
    after = await ctx.music_db.fetch_value(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
    )
    assert before == after


async def test_wal_mode_enabled(ctx):
    """WAL включён — иначе сканер блокировал бы чтение API."""
    for db in (ctx.users_db, ctx.music_db):
        mode = await db.fetch_value("PRAGMA journal_mode")
        assert str(mode).lower() == "wal"


async def test_users_check_constraints(ctx):
    """role и is_active ограничены CHECK-констрейнтами."""
    with pytest.raises(Exception) as exc:
        await ctx.users_db.execute(
            "INSERT INTO users (username, password_enc, password_hash, role, "
            "is_active, created_at, updated_at) "
            "VALUES ('x', 'e', 'h', 'root', 1, 'now', 'now')"
        )
    assert "CHECK" in str(exc.value).upper() or "constraint" in str(exc.value).lower()


async def test_username_unique_case_insensitive(ctx):
    """Alice и alice — один и тот же аккаунт."""
    await ctx.users.create_user("alice", "password123")
    with pytest.raises(Exception):
        await ctx.users.create_user("ALICE", "password123")


async def test_tracks_path_unique(ctx):
    """Путь — стабильный ключ, дубликат запрещён на уровне схемы."""
    await ctx.music_db.execute(
        "INSERT INTO tracks (path, filename, title, added_at, updated_at) "
        "VALUES ('/music/a.mp3', 'a.mp3', 'A', 'now', 'now')"
    )
    with pytest.raises(Exception):
        await ctx.music_db.execute(
            "INSERT INTO tracks (path, filename, title, added_at, updated_at) "
            "VALUES ('/music/a.mp3', 'a.mp3', 'A2', 'now', 'now')"
        )


async def test_no_cross_database_foreign_keys(ctx):
    """Гарантия архитектуры: в music.db нет FK на пользователей.

    Проверяем именно схему, а не соглашение: если кто-то добавит
    REFERENCES users(...), тест упадёт и это будет видно сразу.
    """
    rows = await ctx.music_db.fetch_all(
        "SELECT name, sql FROM sqlite_master WHERE type='table'"
    )
    for row in rows:
        sql = (row["sql"] or "").lower()
        assert "references users" not in sql, f"таблица {row['name']} ссылается на users"
        assert "references sessions" not in sql

    # И обратная проверка: в users.db нет музыкальных таблиц.
    user_tables = {
        str(row["name"])
        for row in await ctx.users_db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert not ({"tracks", "albums", "playlists"} & user_tables)


async def test_playlists_owner_id_is_soft_reference(ctx):
    """owner_id принимается без проверки существования пользователя."""
    # Пользователь с id=9999 не существует, но строка вставляется:
    # целостность обеспечивает Python, а не SQLite.
    playlist_id = await ctx.music_db.execute(
        "INSERT INTO playlists (owner_id, name, is_public, is_smart, "
        "created_at, updated_at) VALUES (?, ?, 0, 0, 'now', 'now')",
        (9999, "ghost playlist"),
    )
    assert playlist_id > 0


async def test_playlist_tracks_cascade(ctx):
    """Удаление плейлиста чистит позиции (внутри одной базы FK работает)."""
    playlist_id = await ctx.music_db.execute(
        "INSERT INTO playlists (owner_id, name, is_public, is_smart, "
        "created_at, updated_at) VALUES (1, 'p', 0, 0, 'now', 'now')"
    )
    track_id = await ctx.music_db.execute(
        "INSERT INTO tracks (path, filename, title, added_at, updated_at) "
        "VALUES ('/music/b.mp3', 'b.mp3', 'B', 'now', 'now')"
    )
    await ctx.music_db.execute(
        "INSERT INTO playlist_tracks (playlist_id, track_id, position, added_at) "
        "VALUES (?, ?, 0, 'now')",
        (playlist_id, track_id),
    )
    await ctx.music_db.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
    remaining = await ctx.music_db.fetch_value(
        "SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,)
    )
    assert remaining == 0
