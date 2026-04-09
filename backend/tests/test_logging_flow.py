import logging
import os
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.webhook import router as webhook_router
from app.core.logging_setup import init_logging
from app.db.database import Base, get_db
from app.db.models import AnalysisResult, AppSettings, MediaItem
from app.schemas.delete_preview import DeleteExecutePayload, DeleteWebhookPayload
from app.services import delete_preview_service
from app.services.analysis_service import run_analysis
from app.services.delete_preview_service import execute_deletes, process_delete_webhook


class _FakeShenyiClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 15.0) -> None:
        self.base_url = base_url
        self.api_key = api_key

    def delete_version(self, emby_item_id: str) -> tuple[int, str]:
        return 200, "ok"


class LoggingFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_temp_dir_ctx = tempfile.TemporaryDirectory()
        self.db_path = Path(self.db_temp_dir_ctx.name) / "logging_flow.db"
        self.engine = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)

        self.temp_dir_ctx = tempfile.TemporaryDirectory()
        self.logs_dir = self.temp_dir_ctx.name
        init_logging(self.logs_dir, force=True)

        self.old_client = delete_preview_service.ShenyiClient
        delete_preview_service.ShenyiClient = _FakeShenyiClient

        db = self.SessionLocal()
        try:
            db.add(
                AppSettings(
                    emby_base_url="http://emby",
                    emby_api_key="k",
                    emby_user_id="u",
                    selected_libraries_json="[]",
                    excluded_paths_json="[]",
                    sync_concurrency=6,
                    shenyi_base_url="http://shenyi",
                    shenyi_api_key="sk",
                    webhook_token="tok",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00",
                )
            )
            db.commit()
        finally:
            db.close()

    def tearDown(self) -> None:
        delete_preview_service.ShenyiClient = self.old_client
        logging.shutdown()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.temp_dir_ctx.cleanup()
        self.db_temp_dir_ctx.cleanup()

    def _seed_media_for_delete(self) -> int:
        db = self.SessionLocal()
        try:
            media = MediaItem(
                emby_item_id="del-1",
                media_source_id="ms-1",
                delete_target_item_id="del-1-target",
                library_name="Movies",
                item_type="Movie",
                title="Delete Target",
                tmdb_id="100",
                subtitle_streams_json="[]",
                has_chinese_subtitle=0,
                eligible_for_dedup=1,
                is_excluded_path=0,
                path="/mnt/media/delete-target.mkv",
                raw_json="{}",
                created_at="2026-01-01T00:00:00",
                updated_at="2026-01-01T00:00:00",
            )
            db.add(media)
            db.commit()
            db.refresh(media)
            db.add(
                AnalysisResult(
                    group_key="movie:100",
                    media_kind="movie",
                    tmdb_id="100",
                    title="Delete Target",
                    item_id=int(media.id),
                    emby_item_id="del-1",
                    action="delete_candidate",
                    reason_json="{}",
                    is_manual_override=0,
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00",
                )
            )
            db.commit()
            return int(media.id)
        finally:
            db.close()

    def _seed_media_for_analysis(self) -> None:
        db = self.SessionLocal()
        try:
            db.add_all(
                [
                    MediaItem(
                        emby_item_id="ana-1",
                        media_source_id="ana-ms-1",
                        delete_target_item_id="ana-1",
                        library_name="Movies",
                        item_type="Movie",
                        title="A",
                        tmdb_id="8888",
                        subtitle_streams_json="[]",
                        has_chinese_subtitle=0,
                        eligible_for_dedup=1,
                        is_excluded_path=0,
                        path="/mnt/media/a.mkv",
                        raw_json="{}",
                        created_at="2026-01-01T00:00:00",
                        updated_at="2026-01-01T00:00:00",
                    ),
                    MediaItem(
                        emby_item_id="ana-2",
                        media_source_id="ana-ms-2",
                        delete_target_item_id="ana-2",
                        library_name="Movies",
                        item_type="Movie",
                        title="A",
                        tmdb_id="8888",
                        subtitle_streams_json="[]",
                        has_chinese_subtitle=0,
                        eligible_for_dedup=1,
                        is_excluded_path=0,
                        path="/mnt/media/b.mkv",
                        raw_json="{}",
                        created_at="2026-01-01T00:00:00",
                        updated_at="2026-01-01T00:00:00",
                    ),
                ]
            )
            db.commit()
            run_analysis(db)
        finally:
            db.close()

    def test_logging_files_are_written_for_webhook_delete_analysis(self) -> None:
        self._seed_media_for_analysis()
        media_id = self._seed_media_for_delete()

        db = self.SessionLocal()
        try:
            execute_deletes(db, DeleteExecutePayload(group_ids=["movie:100"]))
            process_delete_webhook(
                db,
                DeleteWebhookPayload(
                    Event="library.deleted",
                    ItemId="del-1-target",
                    DeletedFiles=["/mnt/media/delete-target.mkv"],
                ),
            )
        finally:
            db.close()

        app = FastAPI()
        app.include_router(webhook_router)

        def _override_get_db():
            db_local = self.SessionLocal()
            try:
                yield db_local
            finally:
                db_local.close()

        app.dependency_overrides[get_db] = _override_get_db
        client = TestClient(app)
        response = client.post(
            "/api/webhook/emby?token=tok",
            json={"Event": "system.webhooktest", "Title": "Ping", "ItemId": "none"},
        )
        self.assertEqual(response.status_code, 200)

        logging.shutdown()

        webhook_log = os.path.join(self.logs_dir, "dedup-webhook.log")
        delete_log = os.path.join(self.logs_dir, "dedup-delete.log")
        analysis_log = os.path.join(self.logs_dir, "dedup-analysis.log")
        self.assertTrue(os.path.exists(webhook_log))
        self.assertTrue(os.path.exists(delete_log))
        self.assertTrue(os.path.exists(analysis_log))

        with open(webhook_log, "r", encoding="utf-8") as f:
            webhook_text = f.read()
        with open(delete_log, "r", encoding="utf-8") as f:
            delete_text = f.read()
        with open(analysis_log, "r", encoding="utf-8") as f:
            analysis_text = f.read()

        self.assertIn("Webhook request received", webhook_text)
        self.assertIn("Delete execution start", delete_text)
        self.assertIn("Process delete webhook end", delete_text)
        self.assertIn("Analysis run start", analysis_text)

        # Ensure local cleanup happened in the flow and was logged.
        self.assertIn("Local cleanup", delete_text)
        db_check = self.SessionLocal()
        try:
            self.assertIsNone(db_check.query(MediaItem).filter(MediaItem.id == media_id).first())
        finally:
            db_check.close()


if __name__ == "__main__":
    unittest.main()

