from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def _engine_connect_args() -> dict:
    if settings.resolved_database_url.startswith("postgresql"):
        return {"ssl": False}
    return {}


engine = create_async_engine(
    settings.resolved_database_url,
    echo=False,
    connect_args=_engine_connect_args(),
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


def _migrate_sqlite_columns(connection) -> None:
    """Add new columns on existing SQLite databases."""
    if connection.dialect.name != "sqlite":
        return

    def _add(table: str, col: str, ddl: str) -> None:
        rows = connection.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
        existing = {row[1] for row in rows}
        if col not in existing:
            connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    _add("users", "is_active", "is_active BOOLEAN DEFAULT 1 NOT NULL")
    _add("users", "can_create_applicants", "can_create_applicants BOOLEAN DEFAULT 1 NOT NULL")
    _add("users", "max_applicants_per_month", "max_applicants_per_month INTEGER DEFAULT 50 NOT NULL")
    _add("users", "totp_secret", "totp_secret VARCHAR(64)")
    _add("users", "totp_enabled", "totp_enabled BOOLEAN DEFAULT 0 NOT NULL")
    _add("applicants", "assigned_staff_id", "assigned_staff_id CHAR(32)")
    _add("applicants", "deleted_at", "deleted_at DATETIME")
    _add("applicants", "client_name", "client_name VARCHAR(255)")
    _add("applicants", "project_name", "project_name VARCHAR(255)")
    _add("applicants", "department", "department VARCHAR(128)")
    _add("applicants", "tags", "tags TEXT")
    _add("applicants", "case_type", "case_type VARCHAR(32) DEFAULT 'immigration'")
    _add("applicants", "is_family_bundle", "is_family_bundle BOOLEAN DEFAULT 0 NOT NULL")
    _add("documents", "file_hash", "file_hash VARCHAR(64)")
    _add("documents", "tags", "tags TEXT")
    _add("documents", "duplicate_warning", "duplicate_warning BOOLEAN DEFAULT 0 NOT NULL")
    _add("documents", "registry_doc_type", "registry_doc_type VARCHAR(64)")
    _add("documents", "is_exception", "is_exception BOOLEAN DEFAULT 0 NOT NULL")
    _migrate_doc_records_per_file(connection)
    _add("form_templates", "is_active", "is_active BOOLEAN DEFAULT 1 NOT NULL")
    _add("form_templates", "created_at", "created_at DATETIME")


def _migrate_postgres_columns(connection) -> None:
    """Add new columns on existing PostgreSQL databases (Docker production)."""
    if connection.dialect.name != "postgresql":
        return

    def _add(table: str, ddl: str) -> None:
        connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {ddl}")

    _add("users", "is_active BOOLEAN DEFAULT TRUE NOT NULL")
    _add("users", "can_create_applicants BOOLEAN DEFAULT TRUE NOT NULL")
    _add("users", "max_applicants_per_month INTEGER DEFAULT 50 NOT NULL")
    _add("users", "totp_secret VARCHAR(64)")
    _add("users", "totp_enabled BOOLEAN DEFAULT FALSE NOT NULL")
    _add("applicants", "assigned_staff_id UUID")
    _add("applicants", "deleted_at TIMESTAMPTZ")
    _add("applicants", "client_name VARCHAR(255)")
    _add("applicants", "project_name VARCHAR(255)")
    _add("applicants", "department VARCHAR(128)")
    _add("applicants", "tags TEXT")
    _add("applicants", "case_type VARCHAR(32) DEFAULT 'immigration'")
    _add("applicants", "is_family_bundle BOOLEAN DEFAULT FALSE NOT NULL")
    _add("documents", "file_hash VARCHAR(64)")
    _add("documents", "tags TEXT")
    _add("documents", "duplicate_warning BOOLEAN DEFAULT FALSE NOT NULL")
    _add("documents", "registry_doc_type VARCHAR(64)")
    _add("documents", "is_exception BOOLEAN DEFAULT FALSE NOT NULL")
    _add("form_templates", "is_active BOOLEAN DEFAULT TRUE NOT NULL")
    _add("form_templates", "created_at TIMESTAMPTZ")


def _migrate_doc_records_per_file(connection) -> None:
    """Recreate applicant_doc_records: one row per file (source_document_id unique)."""
    if connection.dialect.name != "sqlite":
        return
    row = connection.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='applicant_doc_records'"
    ).fetchone()
    if not row or not row[0]:
        return
    ddl = row[0]
    if "uq_doc_record_source_document" in ddl or "uq_applicant_doc_type_variant" not in ddl:
        return
    connection.exec_driver_sql(
        """
        CREATE TABLE applicant_doc_records_new (
            id BLOB NOT NULL PRIMARY KEY,
            applicant_id BLOB NOT NULL,
            doc_type VARCHAR(64) NOT NULL,
            variant VARCHAR(16) DEFAULT 'standard',
            source_document_id BLOB UNIQUE,
            raw_data TEXT DEFAULT '{}',
            form_data TEXT DEFAULT '{}',
            profile_data TEXT DEFAULT '{}',
            updated_at DATETIME
        )
        """
    )
    connection.exec_driver_sql(
        """
        INSERT INTO applicant_doc_records_new
            (id, applicant_id, doc_type, variant, source_document_id, raw_data, form_data, profile_data, updated_at)
        SELECT id, applicant_id, doc_type, variant, source_document_id, raw_data, form_data, profile_data, updated_at
        FROM applicant_doc_records
        WHERE source_document_id IS NOT NULL
        GROUP BY source_document_id
        """
    )
    connection.exec_driver_sql("DROP TABLE applicant_doc_records")
    connection.exec_driver_sql("ALTER TABLE applicant_doc_records_new RENAME TO applicant_doc_records")
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_applicant_doc_records_applicant_id ON applicant_doc_records (applicant_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_applicant_doc_records_doc_type ON applicant_doc_records (doc_type)"
    )


async def init_db() -> None:
    from app import models  # noqa: F401
    from sqlalchemy import select

    from app.models.entities import User, UserRole

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_sqlite_columns)
        await conn.run_sync(_migrate_postgres_columns)

    async with async_session() as db:
        await _ensure_admin_user(db)
        await db.commit()


async def _ensure_admin_user(db) -> None:
    """Create or update the configured admin login (ADMIN_EMAIL / ADMIN_PASSWORD)."""
    from sqlalchemy import select

    from app.config import settings
    from app.models.entities import User, UserRole
    from app.services.auth import get_user_by_email, hash_password

    email = (settings.admin_email or "").strip().lower()
    password = settings.admin_password or ""
    if not email or not password:
        result = await db.execute(select(User).where(User.role == UserRole.admin))
        if result.scalar_one_or_none() is None:
            first = await db.execute(select(User).order_by(User.created_at).limit(1))
            user = first.scalar_one_or_none()
            if user:
                user.role = UserRole.admin
        return

    user = await get_user_by_email(db, email)
    if user:
        user.email = email
        user.hashed_password = hash_password(password)
        user.role = UserRole.admin
        user.is_active = True
        user.can_create_applicants = True
        user.totp_enabled = False
        user.totp_secret = None
        if user.full_name in {"Demo User", "IT Admin"}:
            user.full_name = None
        return

    # Prefer upgrading existing admin account to the new email
    admin_result = await db.execute(
        select(User).where(User.role == UserRole.admin).order_by(User.created_at).limit(1)
    )
    admin_user = admin_result.scalar_one_or_none()
    if admin_user:
        admin_user.email = email
        admin_user.hashed_password = hash_password(password)
        admin_user.is_active = True
        admin_user.can_create_applicants = True
        admin_user.totp_enabled = False
        admin_user.totp_secret = None
        if admin_user.full_name in {"Demo User", "IT Admin"}:
            admin_user.full_name = None
        return

    db.add(
        User(
            email=email,
            hashed_password=hash_password(password),
            full_name=None,
            role=UserRole.admin,
            is_active=True,
            can_create_applicants=True,
        )
    )
