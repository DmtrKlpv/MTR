"""Сборка зависимостей приложения (composition root).

Один класс AppContext держит всё состояние: конфиг, две базы, шифр паролей,
репозитории, сканер. Никаких глобальных синглтонов — контекст создаётся в
lifespan FastAPI (этап 2) и явно прокидывается дальше, поэтому в тестах
можно поднять изолированный инстанс на временных файлах.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass

from app.config import Settings
from app.db.database import Database
from app.db.migrations import init_databases
from app.audio.ffmpeg import TranscodeLimiter
from app.audio.service import StreamService
from app.covers.service import CoverResolver
from app.repositories.covers import CoverRepository
from app.repositories.library import LibraryRepository
from app.repositories.playlists import PlaylistRepository
from app.repositories.settings import SettingsRepository
from app.repositories.tracks import TrackRepository
from app.repositories.users import UserRepository
from app.web.sessions import SessionRepository
from app.scanner.library_scanner import Scanner
from app.scanner.state import ScanState
from app.scanner.watcher import LibraryWatcher
from app.security.crypto import PasswordCipher, load_or_create_secret

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AppContext:
    """Контейнер зависимостей."""

    settings: Settings
    users_db: Database
    music_db: Database
    cipher: PasswordCipher
    users: UserRepository
    tracks: TrackRepository
    library: LibraryRepository
    playlists: PlaylistRepository
    covers: CoverRepository
    sessions: SessionRepository
    settings_repo: SettingsRepository
    stream_service: StreamService
    scanner: Scanner
    scan_state: ScanState
    watcher: LibraryWatcher | None = None

    @classmethod
    async def create(cls, settings: Settings | None = None) -> "AppContext":
        """Инициализирует контекст: каталоги, ключ, базы, миграции."""
        settings = settings or Settings.from_env()
        settings.ensure_directories()

        secret = load_or_create_secret(settings.secret_key, settings.secret_key_file)
        cipher = PasswordCipher(secret)

        # Два независимых соединения — по одному на базу. Между ними
        # никогда не выполняется общий SQL-запрос.
        users_db = Database(settings.users_db, label="users")
        music_db = Database(settings.music_db, label="music")

        await init_databases(users_db, music_db)

        users_repo = UserRepository(users_db, cipher)
        sessions_repo = SessionRepository(users_db, users_repo)
        settings_repo = SettingsRepository(users_db)
        tracks_repo = TrackRepository(music_db)
        library_repo = LibraryRepository(music_db)
        playlists_repo = PlaylistRepository(music_db)
        covers_repo = CoverRepository(
            music_db,
            CoverResolver(settings.covers_dir, settings.music_dir),
        )
        limiter = TranscodeLimiter(settings.max_transcodes)
        stream_service = StreamService(tracks_repo, limiter)
        scan_state = ScanState()
        scanner = Scanner(
            tracks_repo, settings.music_dir, on_progress=scan_state.update
        )

        watcher = LibraryWatcher(
            scanner,
            settings.music_dir,
            force_polling=settings.watch_polling,
            scan_interval_sec=settings.scan_interval_sec,
            poll_delay_ms=settings.watch_poll_ms,
        ) if (settings.watch_enabled or settings.scan_interval_sec > 0) else None

        return cls(
            settings=settings,
            users_db=users_db,
            music_db=music_db,
            cipher=cipher,
            users=users_repo,
            tracks=tracks_repo,
            library=library_repo,
            playlists=playlists_repo,
            covers=covers_repo,
            sessions=sessions_repo,
            settings_repo=settings_repo,
            stream_service=stream_service,
            scanner=scanner,
            scan_state=scan_state,
            watcher=watcher,
        )

    async def close(self) -> None:
        """Закрывает обе базы. Безопасно вызывать повторно."""
        await self.music_db.close()
        await self.users_db.close()

    async def __aenter__(self) -> "AppContext":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()


async def ensure_bootstrap_admin(
    users: UserRepository, *, username: str, password: str
) -> bool:
    """Создаёт первого админа, если база пуста.

    Нужно ровно для одного случая: свежий контейнер, в котором ещё нет
    ни одной учётки, иначе в веб-интерфейс просто некому войти.
    Если пользователи уже есть — ничего не делает.
    """
    existing = await users.count_users()
    if existing > 0:
        logger.warning(
            "пользователи уже существуют (%d), стартовый админ НЕ создаётся — "
            "MTR_ADMIN_PASSWORD из окружения проигнорирован. Чтобы задать пароль "
            "заново: python -m app.cli setpassword --username <имя>",
            existing,
        )
        return False
    await users.create_user(
        username, password, role="admin", display_name="Administrator"
    )
    logger.warning(
        "создан стартовый администратор %r — смените пароль после первого входа",
        username,
    )
    return True

async def apply_runtime_settings(ctx: "AppContext") -> list[str]:
    """Переносит переопределения из БД в `ctx.settings`.

    Что применяется на лету: значения, которые читаются из `ctx.settings`
    в момент запроса (формат по умолчанию, лимит транскодов для новых
    стримов, интервал скана для наблюдателя).

    Что требует перезапуска и здесь не трогается: пути, ключ шифрования,
    состав пользователей. Об этом честно сказано на странице настроек.
    """
    import dataclasses

    from app.repositories.settings import SPECS

    overrides = await ctx.settings_repo.all_overrides()
    if not overrides:
        return []

    known = {field.name for field in dataclasses.fields(ctx.settings)}
    applied: list[str] = []
    changes = {key: value for key, value in overrides.items()
               if key in known and key in SPECS}
    if not changes:
        return []

    ctx.settings = dataclasses.replace(ctx.settings, **changes)
    applied = sorted(changes)

    # Лимит транскодов живёт в объекте ограничителя, а не в settings.
    if "max_transcodes" in changes:
        ctx.stream_service.limiter.resize(changes["max_transcodes"])
    return applied
