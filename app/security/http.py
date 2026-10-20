"""Защитные механизмы HTTP-слоя.

Закрывает проблемы, найденные аудитом:

1. **Пароль в логах.** uvicorn пишет строку вида
   `GET /rest/ping.view?u=admin&p=changeme123 HTTP/1.1 200`,
   то есть открытый пароль попадает в `docker logs` и в любой сборщик логов.
   `RedactSecretsFilter` вырезает значения чувствительных параметров
   (`p`, `t`, `s`, `jwt`, `password`, `token`) до записи в лог.

2. **Отсутствие security-заголовков.** Добавляются middleware:
   `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
   `Content-Security-Policy` для HTML-страниц.

3. **Неавторизованный доступ к служебным эндпоинтам.** `/api/v1/stats`,
   `/api/v1/info` и главная страница отдавали статистику библиотеки и
   абсолютный путь к музыке кому угодно. Теперь они за авторизацией.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Параметры, значения которых нельзя писать в лог.
SENSITIVE_PARAMS = ("p", "t", "s", "jwt", "password", "token", "salt", "key")

# (?<=[?&]) — имя параметра строго после ? или &
_REDACT_RE = re.compile(
    r"(?<=[?&])(" + "|".join(SENSITIVE_PARAMS) + r")=([^&\s\"]*)",
    re.IGNORECASE,
)

REDACTED = "***"


def redact_url(url: str) -> str:
    """Вырезает значения чувствительных query-параметров из URL.

    Имена параметров остаются: по логу надо понимать, каким способом
    аутентифицировался клиент, но не знать сам пароль или токен.
    """
    if not url or "?" not in url:
        return url
    return _REDACT_RE.sub(lambda m: f"{m.group(1)}={REDACTED}", url)


class RedactSecretsFilter(logging.Filter):
    """Фильтр для логгеров uvicorn: маскирует секреты в строке запроса.

    uvicorn.access пишет через `%`-форматирование с кортежем аргументов,
    поэтому маскировать надо именно аргументы, а не готовое сообщение —
    иначе фильтр сработал бы после форматирования и не увидел бы URL.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_url(value) if isinstance(value, str) else value
                for value in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: redact_url(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        if isinstance(record.msg, str) and "?" in record.msg and "=" in record.msg:
            record.msg = redact_url(record.msg)
        return True


def install_log_redaction() -> None:
    """Ставит фильтр на uvicorn-логгеры. Идемпотентно."""
    for name in ("uvicorn.access", "uvicorn.error", "uvicorn"):
        target = logging.getLogger(name)
        if not any(isinstance(f, RedactSecretsFilter) for f in target.filters):
            target.addFilter(RedactSecretsFilter())


# Заголовки, безопасные для API и HTML одновременно.
SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Permitted-Cross-Domain-Policies": "none",
}

# Строгая политика для обычных страниц: внешних источников нет вовсе.
HTML_CSP = (
    "default-src 'self'; img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
    "media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'"
)

# Своя политика для /docs и /redoc: Swagger UI и ReDoc грузят JS/CSS со CDN.
# Ослабляем правила ТОЛЬКО на этих двух путях — остальные страницы
# продолжают жить под строгой политикой без внешних источников.
DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'"
)

DOCS_PATHS = frozenset({"/docs", "/redoc"})


class SecurityHeadersMiddleware:
    """Добавляет защитные заголовки ко всем ответам.

    Написан как чистый ASGI-middleware, а не BaseHTTPMiddleware: последний
    буферизует поток и ломает стриминг аудио — ответ начинает копиться
    целиком вместо отдачи по частям.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Путь нужен, чтобы подобрать CSP: документации разрешён CDN.
        request_path = scope.get("path", "")
        is_docs = request_path in DOCS_PATHS

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {name.lower() for name, _ in headers}

                for name, value in SECURITY_HEADERS.items():
                    if name.lower().encode() not in present:
                        headers.append((name.lower().encode(), value.encode()))

                # CSP только для HTML: на аудиопотоке он бессмысленен.
                if b"content-security-policy" not in present:
                    content_type = ""
                    for name, value in headers:
                        if name.lower() == b"content-type":
                            content_type = value.decode("latin-1").lower()
                    if "text/html" in content_type:
                        policy = DOCS_CSP if is_docs else HTML_CSP
                        headers.append(
                            (b"content-security-policy", policy.encode())
                        )

                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
