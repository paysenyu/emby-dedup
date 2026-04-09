"""Database initialization helpers."""

from sqlalchemy import inspect, text

from app.db.database import Base, engine
from app.db.models import AnalysisResult, AppSettings, DeleteQueue, MediaItem, OperationLog, WebhookInbox

# Import models so SQLAlchemy can register metadata.
from app.db import models  # noqa: F401


def _recreate_table(table_name: str) -> None:
    """Drop and recreate rebuildable tables when schema is outdated."""
    if table_name == MediaItem.__tablename__:
        MediaItem.__table__.drop(bind=engine, checkfirst=True)
        MediaItem.__table__.create(bind=engine, checkfirst=True)
    elif table_name == AnalysisResult.__tablename__:
        AnalysisResult.__table__.drop(bind=engine, checkfirst=True)
        AnalysisResult.__table__.create(bind=engine, checkfirst=True)


def _ensure_media_items_schema() -> None:
    inspector = inspect(engine)
    table_name = MediaItem.__tablename__
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
    expected_columns = {col.name for col in MediaItem.__table__.columns}

    if not expected_columns.issubset(existing_columns):
        _recreate_table(table_name)


def _ensure_app_settings_schema() -> None:
    inspector = inspect(engine)
    table_name = AppSettings.__tablename__
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
    if "emby_user_id" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE app_settings ADD COLUMN emby_user_id TEXT NOT NULL DEFAULT ''"))
    if "webhook_token" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE app_settings ADD COLUMN webhook_token TEXT NOT NULL DEFAULT ''"))


def _ensure_media_items_compat_columns() -> None:
    inspector = inspect(engine)
    table_name = MediaItem.__tablename__
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
    if "delete_target_item_id" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE media_items ADD COLUMN delete_target_item_id TEXT NOT NULL DEFAULT ''"))


def _ensure_delete_queue_schema() -> None:
    inspector = inspect(engine)
    table_name = DeleteQueue.__tablename__
    if table_name not in inspector.get_table_names():
        DeleteQueue.__table__.create(bind=engine, checkfirst=True)
        return

    existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
    if "retry_count" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE delete_queue ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0"))
    if "status_reason" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE delete_queue ADD COLUMN status_reason TEXT NOT NULL DEFAULT ''"))


def _ensure_operation_logs_schema() -> None:
    inspector = inspect(engine)
    table_name = OperationLog.__tablename__
    if table_name not in inspector.get_table_names():
        OperationLog.__table__.create(bind=engine, checkfirst=True)
        return

    existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
    if "delete_target_item_id" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE operation_logs ADD COLUMN delete_target_item_id TEXT NOT NULL DEFAULT ''"))
    if "status_reason" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE operation_logs ADD COLUMN status_reason TEXT NOT NULL DEFAULT ''"))


def _ensure_webhook_inbox_schema() -> None:
    inspector = inspect(engine)
    table_name = WebhookInbox.__tablename__
    if table_name not in inspector.get_table_names():
        WebhookInbox.__table__.create(bind=engine, checkfirst=True)
        return


def _ensure_indexes() -> None:
    statements = [
        "CREATE INDEX IF NOT EXISTS idx_media_items_tmdb_id ON media_items (tmdb_id)",
        "CREATE INDEX IF NOT EXISTS idx_media_items_eligible_for_dedup ON media_items (eligible_for_dedup)",
        "CREATE INDEX IF NOT EXISTS idx_media_items_emby_item_id ON media_items (emby_item_id)",
        "CREATE INDEX IF NOT EXISTS idx_analysis_results_group_key ON analysis_results (group_key)",
        "CREATE INDEX IF NOT EXISTS idx_analysis_results_action ON analysis_results (action)",
        "CREATE INDEX IF NOT EXISTS idx_delete_queue_status ON delete_queue (delete_status)",
        "CREATE INDEX IF NOT EXISTS idx_delete_queue_target ON delete_queue (delete_target_item_id)",
        "CREATE INDEX IF NOT EXISTS idx_webhook_inbox_status ON webhook_inbox (process_status)",
        "CREATE INDEX IF NOT EXISTS idx_webhook_inbox_target ON webhook_inbox (delete_target_item_id)",
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def init_db() -> None:
    """Create all configured database tables if they do not exist."""
    Base.metadata.create_all(bind=engine)
    _ensure_app_settings_schema()
    _ensure_media_items_schema()
    _ensure_media_items_compat_columns()
    _ensure_delete_queue_schema()
    _ensure_operation_logs_schema()
    _ensure_webhook_inbox_schema()
    _ensure_indexes()
