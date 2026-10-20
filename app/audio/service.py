"""Сервис потоковой отдачи треков.

Связывает три слоя: репозиторий треков (mtr_music.db), планировщик профилей
(profiles.py) и управление процессами (ffmpeg.py). Сам по себе HTTP не знает —
возвращает StreamResponsePlan, который слой API превращает в ответ.

Все проверки доступности и существования файла делаются ДО отдачи заголовков,
чтобы клиент получил осмысленный 404/400/503, а не обрыв посреди потока.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from app.audio.ffmpeg import TranscodeBusy, TranscodeError, TranscodeLimiter, TranscodeStream
from app.audio.profiles import (
    ALL_FORMATS,
    ProfileError,
    StreamPlan,
    build_ffmpeg_argv,
    resolve_plan,
)
from app.repositories.tracks import TrackRepository, TrackRow

logger = logging.getLogger(__name__)


class TrackNotFound(LookupError):
    """Трека нет в БД, или он помечен missing (404)."""


class SourceMissing(LookupError):
    """Трек есть в БД, но файл на диске не найден (404, с пометкой для скана)."""


@dataclass(slots=True)
class OpenedStream:
    """Всё, что нужно HTTP-слою для ответа."""

    plan: StreamPlan
    track: TrackRow
    # Для kind=file: путь к исходнику (FileResponse сам отдаст Range).
    file_path: Path | None = None
    # Для copy/encode: асинхронный итератор байт; закрывается сам.
    body: AsyncIterator[bytes] | None = None
    # Размер известен только для kind=file.
    size_bytes: int | None = None


class StreamService:
    """Выбирает стратегию, проверяет файл и запускает ffmpeg при необходимости."""

    def __init__(self, tracks: TrackRepository, limiter: TranscodeLimiter) -> None:
        self._tracks = tracks
        self._limiter = limiter

    @property
    def limiter(self) -> TranscodeLimiter:
        return self._limiter

    async def open(
        self,
        track_id: int,
        *,
        requested_format: str,
        offset_sec: float,
    ) -> OpenedStream:
        """Подготавливает поток. Исключения — только до первого байта."""
        track = await self._tracks.get_by_id(track_id)
        if track is None or track.missing:
            raise TrackNotFound(f"трек {track_id} не найден")

        source = Path(track.path)
        if not source.is_file():
            # Файл пропал между сканами: помечаем, чтобы следующий скан
            # увидел реальное состояние, и сообщаем клиенту 404.
            logger.warning("файл трека %d отсутствует на диске: %s", track_id, source)
            raise SourceMissing(f"файл трека {track_id} отсутствует")

        plan = resolve_plan(
            source_path=track.path,
            source_bitrate_kbps=track.bitrate,
            requested=requested_format,
            offset_sec=offset_sec,
        )
        if plan.substituted:
            logger.info("трек %d: %s", track_id, plan.substitution_reason)

        if plan.kind == "file":
            return OpenedStream(
                plan=plan,
                track=track,
                file_path=source,
                size_bytes=source.stat().st_size,
            )

        # copy / encode: нужен слот транскодирования.
        if not self._limiter.try_acquire():
            raise TranscodeBusy(
                f"занято {self._limiter.active}/{self._limiter.limit} транскодов"
            )

        argv = build_ffmpeg_argv(plan, source_path=track.path, offset_sec=offset_sec)
        stream = TranscodeStream(argv, on_close=self._limiter.release)
        try:
            stream.start()
        except TranscodeError:
            # on_close уже освободил слот внутри start()
            raise

        return OpenedStream(plan=plan, track=track, body=stream.iterate())


def parse_format(value: str | None, default: str) -> str:
    """Нормализует параметр format. Пустой или отсутствующий — умолчание."""
    if value is None or not value.strip():
        return default
    fmt = value.strip().lower()
    if fmt not in ALL_FORMATS:
        raise ProfileError(
            f"неизвестный формат {fmt!r}, допустимы: {', '.join(ALL_FORMATS)}"
        )
    return fmt


def parse_offset(value: str | None) -> float:
    """timeOffset в секундах. Некорректное значение — ошибка, а не молчаливый 0."""
    if value is None or not value.strip():
        return 0.0
    try:
        offset = float(value)
    except ValueError as exc:
        raise ProfileError("timeOffset должен быть числом") from exc
    if offset != offset or offset in (float("inf"), float("-inf")):  # NaN / inf
        raise ProfileError("timeOffset должен быть конечным числом")
    if offset < 0:
        raise ProfileError("timeOffset не может быть отрицательным")
    # Ограничение разумное: трек длиннее 24 часов не существует в библиотеке.
    return min(offset, 86_400.0)
