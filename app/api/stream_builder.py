"""Построение HTTP-ответа для стриминга — общее для /stream и /rest/stream.

Вынесено из api/stream.py, чтобы Subsonic-метод и «прямой» эндпоинт
отдавали байт-в-байт одинаковые ответы: один и тот же трек, один и тот же
процент качества, одинаковое поведение при ошибке.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi.responses import FileResponse, StreamingResponse

from app.audio.service import OpenedStream, StreamService
from app.bootstrap import AppContext

logger = logging.getLogger(__name__)


async def build_stream_response(
    ctx: AppContext,
    track_id: int,
    requested_format: str,
    offset_sec: float,
    *,
    as_download: bool = False,
) -> FileResponse | StreamingResponse:
    """Открывает поток и оборачивает его в FileResponse или StreamingResponse.

    Исключения сервиса (TrackNotFound, SourceMissing, TranscodeBusy,
    TranscodeError) не перехватываются: слой API решает, каким кодом
    их отдать Subsonic-клиенту или прямому вызову.
    """
    service: StreamService = ctx.stream_service
    opened: OpenedStream = await service.open(
        track_id, requested_format=requested_format, offset_sec=offset_sec
    )

    headers = {
        "X-MTR-Format": opened.plan.format_name,
        "X-MTR-Strategy": opened.plan.kind,
    }
    if opened.plan.substituted:
        headers["X-MTR-Substituted"] = "1"
        reason = (opened.plan.substitution_reason or "")[:200]
        headers["X-MTR-Substitution-Reason"] = quote(reason, safe=" ,.:/-_()")

    if opened.plan.kind == "file":
        # FileResponse сам корректно обрабатывает Range: перемотка в плеере
        # работает без единой строки нашего кода.
        return FileResponse(
            opened.file_path,
            media_type=opened.plan.mime,
            headers=headers,
            filename=opened.track.filename if as_download else None,
            content_disposition_type="attachment" if as_download else "inline",
        )

    # copy/encode: Content-Length неизвестен, отдаём chunked.
    return StreamingResponse(
        opened.body,
        media_type=opened.plan.mime,
        headers=headers,
    )
