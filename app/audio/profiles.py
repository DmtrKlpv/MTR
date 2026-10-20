"""Профили транскодирования и выбор стратегии отдачи трека.

Три возможных стратегии для одного запроса:

  file    — отдаём исходный файл как есть (FileResponse, поддержка Range).
            Используется для format=raw без смещения.
  copy    — ffmpeg перемуксирует поток без перекодирования (-c:a copy).
            Нужна, когда клиент просит raw + timeOffset: исходник нельзя
            отдать целиком, а перекодировать без нужды не хочется.
  encode  — полное перекодирование в один из профилей (mp3/flac/alac).

Логика «не апскейлить»: если исходник уже MP3 с битрейтом не выше целевого,
перекодирование только добавит артефакты. Такой запрос обслуживается как raw.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

RAW = "raw"

# Фрагментированный MP4: без него ffmpeg не может писать moov-атом в pipe,
# потому что не умеет вернуться назад и дописать заголовок.
FRAGMENTED_MP4_FLAGS = ("-movflags", "frag_keyframe+empty_moov+default_base_moof")


@dataclass(frozen=True, slots=True)
class Profile:
    """Описание одного целевого формата."""

    name: str
    mime: str
    codec_args: tuple[str, ...]
    muxer_args: tuple[str, ...]
    # Целевой битрейт в бит/с для lossy-форматов, None для lossless/VBR.
    bitrate_bps: int | None = None


PROFILES: dict[str, Profile] = {
    "mp3_128": Profile(
        name="mp3_128", mime="audio/mpeg",
        codec_args=("-c:a", "libmp3lame", "-b:a", "128k"),
        muxer_args=("-f", "mp3"), bitrate_bps=128_000,
    ),
    "mp3_256": Profile(
        name="mp3_256", mime="audio/mpeg",
        codec_args=("-c:a", "libmp3lame", "-b:a", "256k"),
        muxer_args=("-f", "mp3"), bitrate_bps=256_000,
    ),
    "mp3_320": Profile(
        name="mp3_320", mime="audio/mpeg",
        codec_args=("-c:a", "libmp3lame", "-b:a", "320k"),
        muxer_args=("-f", "mp3"), bitrate_bps=320_000,
    ),
    # VBR качества 0 (~245 кбит/с средний, до 320 пиков).
    "mp3_v0": Profile(
        name="mp3_v0", mime="audio/mpeg",
        codec_args=("-c:a", "libmp3lame", "-q:a", "0"),
        muxer_args=("-f", "mp3"), bitrate_bps=None,
    ),
    "flac": Profile(
        name="flac", mime="audio/flac",
        codec_args=("-c:a", "flac", "-compression_level", "5"),
        muxer_args=("-f", "flac"),
    ),
    "alac": Profile(
        name="alac", mime="audio/mp4",
        codec_args=("-c:a", "alac"),
        muxer_args=("-f", "ipod", *FRAGMENTED_MP4_FLAGS),
    ),
}

ALL_FORMATS: tuple[str, ...] = (RAW, *PROFILES)

# Для копирования потока (raw + timeOffset): суффикс -> (muxer, mime).
# Форматы вне таблицы копировать нельзя, для них применяется fallback.
COPY_MUXERS: dict[str, tuple[tuple[str, ...], str]] = {
    ".mp3": (("-f", "mp3"), "audio/mpeg"),
    ".flac": (("-f", "flac"), "audio/flac"),
    ".ogg": (("-f", "ogg"), "audio/ogg"),
    ".oga": (("-f", "ogg"), "audio/ogg"),
    ".opus": (("-f", "ogg"), "audio/ogg"),
    ".m4a": (("-f", "ipod", *FRAGMENTED_MP4_FLAGS), "audio/mp4"),
    ".m4b": (("-f", "ipod", *FRAGMENTED_MP4_FLAGS), "audio/mp4"),
    ".aac": (("-f", "adts"), "audio/aac"),
}

# MIME для отдачи raw-файлов без ffmpeg.
MIME_BY_SUFFIX: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
    ".m4b": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
    ".wav": "audio/wav",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
    ".wma": "audio/x-ms-wma",
    ".ape": "audio/ape",
    ".wv": "audio/x-wavpack",
    ".mpc": "audio/x-musepack",
}

# Если копирование невозможно — что перекодируем вместо raw+offset.
FALLBACK_PROFILE = "mp3_320"


class ProfileError(ValueError):
    """Некорректный запрос формата или смещения (ответ 400)."""


@dataclass(frozen=True, slots=True)
class StreamPlan:
    """Итоговое решение: как отдать трек. Не содержит путей и процессов."""

    kind: str                       # "file" | "copy" | "encode"
    format_name: str                # фактически отдаваемый формат (для X-MTR-Format)
    mime: str
    codec_args: tuple[str, ...] = ()
    muxer_args: tuple[str, ...] = ()
    # True, если клиент просил один формат, а получил другой (fallback/no-upscale).
    substituted: bool = False
    substitution_reason: str | None = None


def resolve_plan(
    *,
    source_path: str,
    source_bitrate_kbps: int | None,
    requested: str,
    offset_sec: float,
) -> StreamPlan:
    """Выбирает стратегию отдачи. Чистая функция, без I/O — легко тестируется."""
    if requested not in ALL_FORMATS:
        raise ProfileError(
            f"неизвестный формат {requested!r}, допустимы: {', '.join(ALL_FORMATS)}"
        )
    if offset_sec < 0:
        raise ProfileError("timeOffset не может быть отрицательным")

    suffix = PurePosixPath(source_path).suffix.lower()
    source_mime = MIME_BY_SUFFIX.get(suffix, "application/octet-stream")

    # --- raw: отдаём файл как есть, при смещении — копируем поток --------
    if requested == RAW:
        return _plan_raw(suffix, source_mime, offset_sec)

    profile = PROFILES[requested]

    # --- Не апскейлим MP3: исходник не выше целевого битрейта ------------
    if (
        profile.bitrate_bps is not None
        and suffix == ".mp3"
        and source_bitrate_kbps
        and source_bitrate_kbps * 1000 <= profile.bitrate_bps
    ):
        plan = _plan_raw(suffix, source_mime, offset_sec)
        return StreamPlan(
            kind=plan.kind,
            format_name=plan.format_name,
            mime=plan.mime,
            codec_args=plan.codec_args,
            muxer_args=plan.muxer_args,
            substituted=True,
            substitution_reason=(
                f"исходник {source_bitrate_kbps} кбит/с не выше {requested}, "
                "перекодирование не делается"
            ),
        )

    return StreamPlan(
        kind="encode",
        format_name=profile.name,
        mime=profile.mime,
        codec_args=profile.codec_args,
        muxer_args=profile.muxer_args,
    )


def _plan_raw(suffix: str, source_mime: str, offset_sec: float) -> StreamPlan:
    """Стратегия raw: file без смещения, copy со смещением, иначе fallback."""
    if offset_sec <= 0:
        return StreamPlan(kind="file", format_name=RAW, mime=source_mime)

    copy = COPY_MUXERS.get(suffix)
    if copy is not None:
        muxer_args, mime = copy
        return StreamPlan(
            kind="copy",
            format_name=RAW,
            mime=mime,
            codec_args=("-c:a", "copy"),
            muxer_args=muxer_args,
        )

    # Копировать WAV/WMA/APE нельзя: перекодируем в MP3 и честно сообщаем.
    fallback = PROFILES[FALLBACK_PROFILE]
    return StreamPlan(
        kind="encode",
        format_name=fallback.name,
        mime=fallback.mime,
        codec_args=fallback.codec_args,
        muxer_args=fallback.muxer_args,
        substituted=True,
        substitution_reason=f"{suffix} нельзя скопировать при смещении, выдан {FALLBACK_PROFILE}",
    )


def build_ffmpeg_argv(
    plan: StreamPlan, *, source_path: str, offset_sec: float
) -> list[str]:
    """Собирает argv для subprocess. Только список, никакого shell.

    -ss ставится ДО -i: ffmpeg декодирует и отбрасывает данные до точки,
    поэтому смещение точное даже для VBR-файлов. -map 0:a:0 и -vn отсекают
    встроенные обложки, которые иначе попали бы в поток как видео.
    """
    argv: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-nostdin",
    ]
    if offset_sec > 0:
        argv += ["-ss", f"{offset_sec:.3f}"]
    argv += [
        "-i", source_path,
        "-map", "0:a:0",
        "-vn",
        "-map_metadata", "-1",
        *plan.codec_args,
        *plan.muxer_args,
        "pipe:1",
    ]
    return argv
