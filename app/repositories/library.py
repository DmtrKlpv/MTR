"""Репозиторий альбомов и исполнителей (mtr_music.db).

JOIN между albums/artists/tracks здесь полностью законен: все три таблицы
живут в одном файле. Запрет на JOIN касается только пары mtr_users.db и
mtr_music.db — это разные SQLite-базы, и связывать их можно лишь в Python.

Все запросы фильтруют missing = 0: трек, чей файл исчез, не должен
попадать в выдачу, но строка в БД остаётся ради плейлистов.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from app.db.database import Database
from app.repositories.tracks import TrackRow, _row_to_track

logger = logging.getLogger(__name__)

# Допустимые порядки сортировки для getAlbumList2.
ALBUM_SORTS: dict[str, str] = {
    "newest": "a.created_at DESC, a.id DESC",
    "recent": "COALESCE(last_play, '') DESC, a.id DESC",
    "frequent": "COALESCE(plays, 0) DESC, a.id DESC",
    "random": "RANDOM()",
    "alphabeticalbyname": "a.name COLLATE NOCASE ASC",
    "alphabeticalbyartist": "ar.name COLLATE NOCASE ASC, a.year, a.name COLLATE NOCASE",
    "byyear": "a.year DESC, a.name COLLATE NOCASE",
    "bygenre": "a.genre COLLATE NOCASE, a.name COLLATE NOCASE",
}

# Общая часть выборки альбома: счётчики и агрегаты считаются подзапросами,
# потому что JOIN с tracks размножил бы строки при подсчёте.
_ALBUM_SELECT = """
SELECT
    a.id, a.name, a.artist_id, a.year, a.genre, a.created_at,
    ar.name AS artist_name,
    (SELECT COUNT(*) FROM tracks t WHERE t.album_id = a.id AND t.missing = 0)
        AS song_count,
    (SELECT COALESCE(SUM(t.duration_ms), 0) FROM tracks t
      WHERE t.album_id = a.id AND t.missing = 0) AS duration_ms,
    (SELECT COALESCE(SUM(ps.play_count), 0)
       FROM tracks t JOIN play_stats ps ON ps.track_id = t.id
      WHERE t.album_id = a.id) AS plays,
    (SELECT MAX(pb.played_at)
       FROM tracks t JOIN playback_log pb ON pb.track_id = t.id
      WHERE t.album_id = a.id) AS last_play
  FROM albums a
  LEFT JOIN artists ar ON ar.id = a.artist_id
"""


@dataclass(slots=True)
class AlbumRow:
    """Альбом с агрегатами для Subsonic-ответа."""

    id: int
    name: str
    artist_id: int | None
    artist_name: str | None
    year: int | None
    genre: str | None
    created_at: str
    song_count: int
    duration_ms: int
    play_count: int = 0

    @property
    def duration_sec(self) -> int:
        return int(round(self.duration_ms / 1000))


@dataclass(slots=True)
class ArtistRow:
    """Исполнитель с числом альбомов."""

    id: int
    name: str
    album_count: int

    @property
    def sort_letter(self) -> str:
        """Первая буква для группировки в getArtists.

        Не-латинские имена (кириллица, CJK) попадают в «#»: раскладывать их
        по Unicode-блокам бессмысленно для навигации, а клиенты ожидают
        именно однобуквенный индекс.
        """
        if not self.name:
            return "#"
        first = self.name.lstrip()[0].upper()
        return first if "A" <= first <= "Z" else "#"


def _row_to_album(row: sqlite3.Row) -> AlbumRow:
    return AlbumRow(
        id=int(row["id"]),
        name=str(row["name"]),
        artist_id=row["artist_id"],
        artist_name=row["artist_name"],
        year=row["year"],
        genre=row["genre"],
        created_at=str(row["created_at"]),
        song_count=int(row["song_count"] or 0),
        duration_ms=int(row["duration_ms"] or 0),
        play_count=int(row["plays"] or 0),
    )


class LibraryRepository:
    """Чтение альбомов, исполнителей и жанров."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Альбомы
    # ------------------------------------------------------------------
    async def list_albums(
        self,
        *,
        sort: str = "alphabeticalByArtist",
        limit: int = 10,
        offset: int = 0,
        genre: str | None = None,
        from_year: int | None = None,
        to_year: int | None = None,
    ) -> list[AlbumRow]:
        """Список альбомов по типу сортировки из getAlbumList2."""
        order = ALBUM_SORTS.get(sort.lower())
        if order is None:
            order = ALBUM_SORTS["alphabeticalbyartist"]

        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))

        clauses = [
            "(SELECT COUNT(*) FROM tracks t WHERE t.album_id = a.id "
            "AND t.missing = 0) > 0"
        ]
        params: list[object] = []
        if genre:
            clauses.append("a.genre = ? COLLATE NOCASE")
            params.append(genre)
        if from_year is not None:
            clauses.append("a.year >= ?")
            params.append(int(from_year))
        if to_year is not None:
            clauses.append("a.year <= ?")
            params.append(int(to_year))

        sql = (
            f"{_ALBUM_SELECT} WHERE {' AND '.join(clauses)} "
            f"ORDER BY {order} LIMIT ? OFFSET ?"
        )
        rows = await self._db.fetch_all(sql, (*params, limit, offset))
        return [_row_to_album(row) for row in rows]

    async def first_album_id(self, artist_id: int) -> int | None:
        """id первого непустого альбома исполнителя — для аватара.

        Обложек у исполнителей в схеме нет, поэтому берём обложку альбома.
        Пустые альбомы (без треков) пропускаем: у них нет и картинки.
        """
        row = await self._db.fetch_one(
            "SELECT a.id FROM albums a WHERE a.artist_id = ? "
            "AND (SELECT COUNT(*) FROM tracks t "
            "     WHERE t.album_id = a.id AND t.missing = 0) > 0 "
            "ORDER BY a.year, a.name COLLATE NOCASE LIMIT 1",
            (artist_id,),
        )
        return None if row is None else int(row["id"])

    async def get_album(self, album_id: int) -> AlbumRow | None:
        row = await self._db.fetch_one(f"{_ALBUM_SELECT} WHERE a.id = ?", (album_id,))
        return _row_to_album(row) if row else None

    async def album_tracks(self, album_id: int) -> list[TrackRow]:
        """Треки альбома в порядке диска и номера."""
        rows = await self._db.fetch_all(
            "SELECT * FROM tracks WHERE album_id = ? AND missing = 0 "
            "ORDER BY disc_number, track_number, title COLLATE NOCASE",
            (album_id,),
        )
        return [_row_to_track(row) for row in rows]

    async def count_albums(self) -> int:
        return int(
            await self._db.fetch_value(
                "SELECT COUNT(*) FROM albums a WHERE (SELECT COUNT(*) FROM tracks t "
                "WHERE t.album_id = a.id AND t.missing = 0) > 0",
                default=0,
            )
            or 0
        )

    # ------------------------------------------------------------------
    # Исполнители
    # ------------------------------------------------------------------
    async def list_artists(self) -> list[ArtistRow]:
        """Все исполнители хотя бы с одним непустым альбомом."""
        rows = await self._db.fetch_all(
            """
            SELECT ar.id, ar.name,
                   (SELECT COUNT(*) FROM albums a
                     WHERE a.artist_id = ar.id
                       AND (SELECT COUNT(*) FROM tracks t
                             WHERE t.album_id = a.id AND t.missing = 0) > 0)
                   AS album_count
              FROM artists ar
             ORDER BY ar.name COLLATE NOCASE
            """
        )
        artists = [
            ArtistRow(
                id=int(row["id"]),
                name=str(row["name"]),
                album_count=int(row["album_count"] or 0),
            )
            for row in rows
        ]
        # Исполнитель без альбомов (встречается только в тегах треков)
        # клиентам бесполезен и засоряет навигацию.
        return [artist for artist in artists if artist.album_count > 0]

    async def get_artist(self, artist_id: int) -> ArtistRow | None:
        row = await self._db.fetch_one(
            """
            SELECT ar.id, ar.name,
                   (SELECT COUNT(*) FROM albums a
                     WHERE a.artist_id = ar.id
                       AND (SELECT COUNT(*) FROM tracks t
                             WHERE t.album_id = a.id AND t.missing = 0) > 0)
                   AS album_count
              FROM artists ar WHERE ar.id = ?
            """,
            (artist_id,),
        )
        if row is None:
            return None
        return ArtistRow(
            id=int(row["id"]),
            name=str(row["name"]),
            album_count=int(row["album_count"] or 0),
        )

    async def artist_albums(self, artist_id: int) -> list[AlbumRow]:
        rows = await self._db.fetch_all(
            f"{_ALBUM_SELECT} WHERE a.artist_id = ? "
            "AND (SELECT COUNT(*) FROM tracks t WHERE t.album_id = a.id "
            "AND t.missing = 0) > 0 "
            "ORDER BY a.year, a.name COLLATE NOCASE",
            (artist_id,),
        )
        return [_row_to_album(row) for row in rows]

    # ------------------------------------------------------------------
    # Жанры и поиск
    # ------------------------------------------------------------------
    async def list_genres(self) -> list[tuple[str, int, int]]:
        """(жанр, число треков, число альбомов) — для getGenres."""
        rows = await self._db.fetch_all(
            """
            SELECT genre,
                   COUNT(*) AS song_count,
                   COUNT(DISTINCT album_id) AS album_count
              FROM tracks
             WHERE missing = 0 AND genre IS NOT NULL AND TRIM(genre) <> ''
             GROUP BY genre COLLATE NOCASE
             ORDER BY genre COLLATE NOCASE
            """
        )
        return [
            (str(row["genre"]), int(row["song_count"]), int(row["album_count"]))
            for row in rows
        ]

    async def search_albums(self, query: str, *, limit: int = 20) -> list[AlbumRow]:
        like = _like(query)
        if like is None:
            return []
        # Ищем по названию альбома И по имени исполнителя: запрос "Queen"
        # должен находить альбомы Queen, даже если слово не в названии.
        rows = await self._db.fetch_all(
            f"{_ALBUM_SELECT} WHERE (a.name LIKE ? ESCAPE '\\' "
            "OR ar.name LIKE ? ESCAPE '\\') "
            "AND (SELECT COUNT(*) FROM tracks t WHERE t.album_id = a.id "
            "AND t.missing = 0) > 0 "
            "ORDER BY a.name COLLATE NOCASE LIMIT ?",
            (like, like, max(1, min(limit, 200))),
        )
        return [_row_to_album(row) for row in rows]

    async def search_artists(self, query: str, *, limit: int = 20) -> list[ArtistRow]:
        like = _like(query)
        if like is None:
            return []
        rows = await self._db.fetch_all(
            """
            SELECT ar.id, ar.name,
                   (SELECT COUNT(*) FROM albums a WHERE a.artist_id = ar.id
                     AND (SELECT COUNT(*) FROM tracks t WHERE t.album_id = a.id
                           AND t.missing = 0) > 0) AS album_count
              FROM artists ar
             WHERE ar.name LIKE ? ESCAPE '\\'
             ORDER BY ar.name COLLATE NOCASE LIMIT ?
            """,
            (like, max(1, min(limit, 200))),
        )
        return [
            ArtistRow(int(row["id"]), str(row["name"]), int(row["album_count"] or 0))
            for row in rows
            if int(row["album_count"] or 0) > 0
        ]


def _like(query: str) -> str | None:
    """Экранированный LIKE-шаблон. None для пустого запроса."""
    cleaned = (query or "").strip()
    if not cleaned:
        return None
    escaped = cleaned.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"
