"""Репозиторий кэша обложек (mtr_music.db + COVERS_DIR).

Таблица `cover_cache` уже есть в схеме v1, менять структуру не нужно.
Здесь — операции над ней и логика «откуда взять обложку».

Порядок для альбома:
  1. записи кэша с ключом `al-<id>` — если файл на диске ещё существует;
  2. поиск обложки у треков альбома (первый, у кого нашлась);
  3. файл cover.jpg в каталоге альбома.

Для трека (`tr-<id>`) — только его собственные данные: подставлять чужую
обложку к конкретному треку нельзя, клиент ждёт картинку именно этого файла.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.covers.service import CoverData, CoverResolver, extract_cover
from app.db.database import Database
from app.utils.timeutil import utcnow_iso

logger = logging.getLogger(__name__)


class CoverRepository:
    """Кэш обложек: метаданные в БД, байты в COVERS_DIR."""

    def __init__(self, db: Database, resolver: CoverResolver) -> None:
        self._db = db
        self._resolver = resolver

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------
    async def get_cached(self, key: str) -> CoverData | None:
        """Возвращает обложку из кэша, если файл ещё на месте."""
        row = await self._db.fetch_one(
            "SELECT file_path, mime_type FROM cover_cache WHERE key = ?", (key,)
        )
        if row is None:
            return None
        cover = self._resolver.read_cached(str(row["file_path"]))
        if cover is None:
            # Файл пропал (например, почистили volume) — запись устарела.
            await self._db.execute("DELETE FROM cover_cache WHERE key = ?", (key,))
            return None
        # MIME из БД авторитетнее угадывания по сигнатуре.
        return CoverData(cover.data, str(row["mime_type"]), "cache")

    async def store(self, key: str, cover: CoverData) -> None:
        """Сохраняет обложку и запись кэша (upsert по ключу)."""
        file_path, size = self._resolver.store(key, cover)
        await self._db.execute(
            "INSERT INTO cover_cache "
            "(key, file_path, mime_type, size_bytes, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (key) DO UPDATE SET "
            "file_path = excluded.file_path, "
            "mime_type = excluded.mime_type, "
            "size_bytes = excluded.size_bytes, "
            "source = excluded.source, "
            "created_at = excluded.created_at",
            (key, file_path, cover.mime, size, cover.source, utcnow_iso()),
        )

    # ------------------------------------------------------------------
    # Разрешение для альбома
    # ------------------------------------------------------------------
    async def for_album(self, album_id: int) -> CoverData | None:
        """Обложка альбома: кэш, затем обложки его треков."""
        key = f"al-{album_id}"
        cached = await self.get_cached(key)
        if cached is not None:
            return cached

        rows = await self._db.fetch_all(
            "SELECT path, has_cover FROM tracks "
            "WHERE album_id = ? AND missing = 0 "
            "ORDER BY has_cover DESC, disc_number, track_number LIMIT 50",
            (album_id,),
        )
        if not rows:
            return None

        for row in rows:
            path = Path(str(row["path"]))
            if not self._resolver.is_inside_music(path):
                continue
            cover = extract_cover(path)
            if cover is None:
                continue
            await self.store(key, cover)
            logger.debug("обложка альбома %d из %s (%s)", album_id, path, cover.source)
            return cover
        return None

    async def for_track(self, track_id: int) -> CoverData | None:
        """Обложка конкретного трека (для `tr-<id>`)."""
        key = f"tr-{track_id}"
        cached = await self.get_cached(key)
        if cached is not None:
            return cached

        row = await self._db.fetch_one(
            "SELECT path, has_cover, album_id FROM tracks WHERE id = ? AND missing = 0",
            (track_id,),
        )
        if row is None:
            return None

        path = Path(str(row["path"]))
        if not self._resolver.is_inside_music(path):
            return None

        cover = extract_cover(path)
        if cover is None:
            # У трека своей картинки нет — отдаём обложку альбома,
            # но НЕ кэшируем под ключом трека: иначе при появлении
            # собственной обложки кэш останется неверным.
            album_id = row["album_id"]
            if album_id is None:
                return None
            return await self.for_album(int(album_id))

        await self.store(key, cover)
        return cover

    async def invalidate_album(self, album_id: int) -> None:
        """Сбрасывает кэш альбома (вызывается при изменении тегов)."""
        await self._db.execute(
            "DELETE FROM cover_cache WHERE key = ?", (f"al-{album_id}",)
        )

    async def stats(self) -> dict[str, int]:
        """Сколько обложек в кэше и сколько занимают."""
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS total "
            "FROM cover_cache"
        )
        if row is None:
            return {"count": 0, "total_bytes": 0}
        return {
            "count": int(row["count"] or 0),
            "total_bytes": int(row["total"] or 0),
        }
