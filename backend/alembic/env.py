import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Project imports — dùng chung Base/metadata và settings với app runtime,
# để autogenerate so khớp đúng model hiện tại thay vì phải khai báo lại.
from app.config import settings
from app.database import Base
from app import models  # noqa: F401  — import để đăng ký toàn bộ model vào Base.metadata

config = context.config
# configparser dùng "%" cho interpolation — password/URL urlencode có thể chứa "%xx"
# (vd. "@" -> "%40"), phải escape "%%" trước khi set, nếu không set_main_option ném
# ValueError "invalid interpolation syntax".
config.set_main_option("sqlalchemy.url", settings.resolved_database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Sinh SQL script (không cần kết nối DB) — `alembic upgrade head --sql`."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Chạy migration qua async engine (asyncpg / aiosqlite) — cùng driver với app."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
