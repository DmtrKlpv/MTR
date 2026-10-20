"""Прямой эндпоинт потоковой отдачи: /stream.

Это НЕ Subsonic-метод (тот живёт на /rest/stream), а простой внутренний
API для собственного веб-плеера на этапе 6. Требует ту же авторизацию:
принимает u/t/s/p в query, как Subsonic, чтобы не заводить второй
механизм аутентификации.

Параметры:
  id          — id трека в mtr_music.db
  format      — raw | mp3_128 | mp3_256 | mp3_320 | mp3_v0 | flac | alac
  timeOffset  — секунды с начала трека
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.audio.ffmpeg import TranscodeBusy, TranscodeError
from app.audio.profiles import ProfileError
from app.audio.service import SourceMissing, TrackNotFound, parse_format, parse_offset
from app.api.stream_builder import build_stream_response
from app.bootstrap import AppContext
from app.subsonic.auth import AuthContext
from app.subsonic.deps import require_auth_or_session

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stream"])


@router.get("/stream")
async def stream_track(
    request: Request,
    id: int = Query(..., ge=1, description="id трека"),
    format: str | None = Query(
        None,
        description="raw | mp3_128 | mp3_256 | mp3_320 | mp3_v0 | flac | alac",
    ),
    timeOffset: str | None = Query(None, description="смещение в секундах"),
    auth: AuthContext | None = Depends(require_auth_or_session),
):
    """Отдаёт трек: исходником, копией с перемотки или перекодированным."""
    if auth is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": 'Subsonic realm="mtr"'},
        )
    ctx: AppContext = request.app.state.ctx

    try:
        requested = parse_format(format, ctx.settings.default_transcode)
        offset = parse_offset(timeOffset)
        return await build_stream_response(ctx, id, requested, offset)
    except ProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (TrackNotFound, SourceMissing) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TranscodeBusy as exc:
        raise HTTPException(
            status_code=503, detail=str(exc), headers={"Retry-After": "2"}
        ) from exc
    except TranscodeError as exc:
        logger.error("сбой запуска транскода трека %d: %s", id, exc)
        raise HTTPException(
            status_code=500, detail="не удалось запустить транскодирование"
        ) from exc
