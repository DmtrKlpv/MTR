"""Преобразование внутренних моделей в JSON-структуры Subsonic.

Каждый форматтер возвращает обычный dict — сериализацией занимается
JSONResponse. None-поля не попадают в ответ: часть клиентов падает на
явном null, а спецификация допускает отсутствие необязательных атрибутов.

Идентификаторы:
  * трек/альбом/артист — строка с числовым id (совместимо с большинством);
  * coverArt — префикс «tr-»/«al-», чтобы при разборе было понятно, из чего
    извлекать обложку. Это не влияет на совместимость: клиенты считают id
    непрозрачной строкой.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from app.repositories.library import AlbumRow, ArtistRow
from app.repositories.tracks import TrackRow

# Расширение файла -> суффикс в терминах Subsonic (suffix).
SUFFIX_BY_EXT: dict[str, str] = {
    ".mp3": "mp3", ".flac": "flac", ".ogg": "ogg", ".oga": "ogg",
    ".opus": "opus", ".m4a": "m4a", ".m4b": "m4b", ".mp4": "mp4",
    ".aac": "aac", ".wav": "wav", ".aiff": "aiff", ".aif": "aiff",
    ".wma": "wma", ".ape": "ape", ".wv": "wv", ".mpc": "mpc",
    ".dsf": "dsf", ".dff": "dff",
}

# Расширение -> MIME для contentType.
CONTENT_TYPE_BY_EXT: dict[str, str] = {
    ".mp3": "audio/mpeg", ".flac": "audio/flac", ".ogg": "audio/ogg",
    ".oga": "audio/ogg", ".opus": "audio/ogg", ".m4a": "audio/mp4",
    ".m4b": "audio/mp4", ".mp4": "audio/mp4", ".aac": "audio/aac",
    ".wav": "audio/wav", ".aiff": "audio/aiff", ".aif": "audio/aiff",
    ".wma": "audio/x-ms-wma", ".ape": "audio/ape", ".wv": "audio/x-wavpack",
    ".mpc": "audio/x-musepack",
}


def track_id(track: TrackRow) -> str:
    return str(track.id)


def album_id(album: AlbumRow) -> str:
    return str(album.id)


def artist_id(artist: ArtistRow) -> str:
    return str(artist.id)


def cover_art_id(kind: str, entity_id: int) -> str:
    """Идентификатор обложки: 'tr-12' или 'al-7'."""
    return f"{kind}-{entity_id}"


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def child_json(track: TrackRow) -> dict[str, Any]:
    """Трек в формате Subsonic Child.

    isDir=0 и type='music' обязательны: клиенты отличают папки от треков
    именно по этим полям при разборе getIndexes.
    """
    suffix = PurePosixPath(track.path).suffix.lower()
    return _drop_empty(
        {
            "id": str(track.id),
            "parent": str(track.album_id) if track.album_id else None,
            "isDir": False,
            "title": track.title,
            "album": track.album,
            "artist": track.artist,
            "track": track.track_number,
            "discNumber": track.disc_number,
            "year": track.year,
            "genre": track.genre,
            "coverArt": cover_art_id("tr", track.id) if track.has_cover else None,
            "size": track.size_bytes,
            # duration в Subsonic — целые секунды, не миллисекунды.
            "duration": track.duration_sec,
            "bitRate": track.bitrate,
            "sampleRate": track.sample_rate,
            "channelCount": track.channels,
            "suffix": SUFFIX_BY_EXT.get(suffix, suffix.lstrip(".")),
            "contentType": CONTENT_TYPE_BY_EXT.get(suffix, "application/octet-stream"),
            "path": track.path,
            "albumId": str(track.album_id) if track.album_id else None,
            "artistId": str(track.artist_id) if track.artist_id else None,
            "type": "music",
            "created": track.added_at,
        }
    )


def album_json(album: AlbumRow) -> dict[str, Any]:
    """Альбом в формате AlbumID3 (getAlbumList2, getArtist, search3)."""
    return _drop_empty(
        {
            "id": str(album.id),
            "name": album.name,
            "artist": album.artist_name,
            "artistId": str(album.artist_id) if album.artist_id else None,
            "coverArt": cover_art_id("al", album.id),
            "songCount": album.song_count,
            "duration": album.duration_sec,
            "playCount": album.play_count,
            "created": album.created_at,
            "year": album.year,
            "genre": album.genre,
        }
    )


def artist_json(artist: ArtistRow) -> dict[str, Any]:
    """Исполнитель в формате ArtistID3."""
    return _drop_empty(
        {
            "id": str(artist.id),
            "name": artist.name,
            "coverArt": None,  # обложки исполнителей появятся на этапе 5
            "albumCount": artist.album_count,
        }
    )


def album_with_songs_json(
    album: AlbumRow, tracks: list[TrackRow]
) -> dict[str, Any]:
    """Ответ getAlbum: метаданные альбома + вложенный список треков."""
    payload = album_json(album)
    payload["song"] = [child_json(track) for track in tracks]
    return payload


def artist_with_albums_json(
    artist: ArtistRow, albums: list[AlbumRow]
) -> dict[str, Any]:
    """Ответ getArtist: исполнитель + его альбомы."""
    payload = artist_json(artist)
    payload["album"] = [album_json(album) for album in albums]
    return payload


def indexes_json(artists: list[ArtistRow]) -> list[dict[str, Any]]:
    """Группировка исполнителей по первой букве для getArtists.

    Один элемент массива на букву, внутри — artist с массивом album.
    Пустые группы не отдаём: клиенты рисуют по ним пустые секции.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for artist in artists:
        grouped.setdefault(artist.sort_letter, []).append(artist_json(artist))

    result: list[dict[str, Any]] = []
    for letter in sorted(grouped, key=lambda value: (value == "#", value)):
        result.append({"name": letter, "artist": grouped[letter]})
    return result


def legacy_index_json(artists: list[ArtistRow]) -> list[dict[str, Any]]:
    """Группировка для устаревшего getIndexes (artist вместо ArtistID3).

    Там artist — «папка»: name + id. Клиенты используют его только для
    навигации, поэтому переиспользуем те же artist_json.
    """
    return indexes_json(artists)


def music_folder_json() -> dict[str, Any]:
    """Единственная музыкальная папка: у нас плоская библиотека."""
    return {"id": 1, "name": "Music"}


def user_json(auth_user, *, include_email: bool = True) -> dict[str, Any]:
    """Пользователь в формате Subsonic user.

    Права выставляем честно: раз мы не поддерживаем комментарии, подкасты,
    загрузку и смену обложек, соответствующие флаги должны быть false,
    иначе клиент покажет нерабочие кнопки.
    """
    return _drop_empty(
        {
            "username": auth_user.username,
            "email": auth_user.email if include_email else None,
            "scrobblingEnabled": False,
            "adminRole": auth_user.role == "admin",
            "settingsRole": auth_user.role == "admin",
            "downloadRole": True,
            "uploadRole": False,
            "playlistRole": True,
            "coverArtRole": False,
            "commentRole": False,
            "podcastRole": False,
            "shareRole": False,
            "videoConversionRole": False,
            "folder": [1],
        }
    )
