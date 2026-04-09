import unittest
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.webhook import router as webhook_router
from app.db.database import Base, get_db
from app.db.models import AnalysisResult, AppSettings, DeleteQueue, MediaItem


class WebhookApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "webhook_api.db"
        self.engine = create_engine(f"sqlite:///{self.db_path.as_posix()}", connect_args={"check_same_thread": False}, future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)

        app = FastAPI()
        app.include_router(webhook_router)

        def _override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _override_get_db
        self.client = TestClient(app)

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
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _add_delete_queue_seed(self) -> int:
        db = self.SessionLocal()
        try:
            media = MediaItem(
                emby_item_id="emby-delete-1",
                media_source_id="ms-1",
                delete_target_item_id="target-delete-1",
                library_name="Movies",
                item_type="Movie",
                title="Delete Me",
                tmdb_id="100",
                subtitle_streams_json="[]",
                has_chinese_subtitle=0,
                eligible_for_dedup=1,
                is_excluded_path=0,
                path="/mnt/media/delete-me.mkv",
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
                    title="Delete Me",
                    item_id=int(media.id),
                    emby_item_id="emby-delete-1",
                    action="delete_candidate",
                    reason_json="{}",
                    is_manual_override=0,
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00",
                )
            )
            db.add(
                DeleteQueue(
                    group_id="movie:100",
                    item_id=int(media.id),
                    delete_target_item_id="target-delete-1",
                    emby_item_id="emby-delete-1",
                    deleted_paths_json='["/mnt/media/delete-me.mkv"]',
                    delete_status="in_progress",
                    retry_count=1,
                    status_code=204,
                    message="waiting webhook",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00",
                )
            )
            db.commit()
            return int(media.id)
        finally:
            db.close()

    def _add_path_only_delete_queue_seed(self) -> int:
        db = self.SessionLocal()
        try:
            media = MediaItem(
                emby_item_id="emby-path-only",
                media_source_id="ms-path-only",
                delete_target_item_id="target-path-only",
                library_name="Movies",
                item_type="Movie",
                title="Delete By Path",
                tmdb_id="101",
                subtitle_streams_json="[]",
                has_chinese_subtitle=0,
                eligible_for_dedup=1,
                is_excluded_path=0,
                path="/mnt/media/path-only.mkv",
                raw_json="{}",
                created_at="2026-01-01T00:00:00",
                updated_at="2026-01-01T00:00:00",
            )
            db.add(media)
            db.commit()
            db.refresh(media)

            db.add(
                AnalysisResult(
                    group_key="movie:101",
                    media_kind="movie",
                    tmdb_id="101",
                    title="Delete By Path",
                    item_id=int(media.id),
                    emby_item_id="emby-path-only",
                    action="delete_candidate",
                    reason_json="{}",
                    is_manual_override=0,
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00",
                )
            )
            db.add(
                DeleteQueue(
                    group_id="movie:101",
                    item_id=int(media.id),
                    delete_target_item_id="target-path-only",
                    emby_item_id="emby-path-only",
                    deleted_paths_json='["/mnt/media/path-only.mkv"]',
                    delete_status="in_progress",
                    retry_count=1,
                    status_code=204,
                    message="waiting webhook",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00",
                )
            )
            db.commit()
            return int(media.id)
        finally:
            db.close()

    def test_token_validation_query_priority_and_body_fallback(self) -> None:
        body_only = self.client.post(
            "/webhook/emby",
            json={
                "Token": "tok",
                "Event": "system.webhooktest",
                "Title": "Ping",
            },
        )
        self.assertEqual(body_only.status_code, 200)
        self.assertEqual(body_only.json(), {"status": "ok", "matched": 0, "updated": 0})

        query_overrides_body = self.client.post(
            "/webhook/emby?token=bad",
            json={
                "Token": "tok",
                "Event": "system.webhooktest",
                "Title": "Ping",
            },
        )
        self.assertEqual(query_overrides_body.status_code, 401)

    def test_invalid_multipart_payload_returns_safe_response(self) -> None:
        response = self.client.post(
            "/webhook/emby?token=tok",
            files={
                "Event": (None, "library.deleted"),
                "User": (None, '{"Name":"tester","Id":"u1"'),
                "Server": (None, "{bad-json}"),
                "DeletedFiles": (None, "[/not-json"),
                "Token": (None, "tok"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "matched": 0, "updated": 0})

    def test_library_new_item_ingest_via_webhook_api(self) -> None:
        response = self.client.post(
            "/webhook/emby?token=tok",
            json={
                "Event": "library.new",
                "Item": {
                    "Id": "new-item-1",
                    "Type": "Movie",
                    "Name": "New Movie",
                    "Path": "/mnt/media/new-movie.mkv",
                    "ProviderIds": {"Tmdb": "90001"},
                    "MediaSources": [
                        {
                            "Id": "mediasource_90001",
                            "Path": "/mnt/media/new-movie.mkv",
                            "Container": "mkv",
                            "Bitrate": 3000000,
                            "MediaStreams": [{"Type": "Video", "Codec": "h264", "Width": 1920, "Height": 1080}],
                        }
                    ],
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "matched": 0, "updated": 0})

        db = self.SessionLocal()
        try:
            rows = db.query(MediaItem).filter(MediaItem.emby_item_id == "new-item-1").all()
            self.assertGreaterEqual(len(rows), 1)
            self.assertTrue(any(str(r.path) == "/mnt/media/new-movie.mkv" for r in rows))
        finally:
            db.close()

    def test_library_deleted_updates_queue_and_cleans_local_rows(self) -> None:
        media_id = self._add_delete_queue_seed()
        response = self.client.post(
            "/webhook/emby?token=tok",
            json={
                "Event": "library.deleted",
                "ItemId": "target-delete-1",
                "DeletedFiles": ["/mnt/media/delete-me.mkv"],
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["updated"], 1)

        db = self.SessionLocal()
        try:
            queue = db.query(DeleteQueue).first()
            self.assertIsNotNone(queue)
            self.assertEqual(queue.delete_status, "done")
            self.assertIn("/mnt/media/delete-me.mkv", queue.deleted_paths_json)

            media = db.query(MediaItem).filter(MediaItem.id == media_id).first()
            analysis = db.query(AnalysisResult).filter(AnalysisResult.item_id == media_id).first()
            self.assertIsNone(media)
            self.assertIsNone(analysis)
        finally:
            db.close()

    def test_deep_delete_with_mount_paths_updates_queue(self) -> None:
        media_id = self._add_delete_queue_seed()
        response = self.client.post(
            "/webhook/emby?token=tok",
            json={
                "Event": "deep.delete",
                "Description": "Test event\nMount Paths:\n/mnt/media/delete-me.mkv\n/mnt/media/extra.mkv\n",
                "DeletedFiles": ["/mnt/media/delete-me.mkv"],
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["updated"], 1)

        db = self.SessionLocal()
        try:
            queue = db.query(DeleteQueue).first()
            self.assertIsNotNone(queue)
            self.assertEqual(queue.delete_status, "done")
            self.assertIn("/mnt/media/delete-me.mkv", queue.deleted_paths_json)

            media = db.query(MediaItem).filter(MediaItem.id == media_id).first()
            analysis = db.query(AnalysisResult).filter(AnalysisResult.item_id == media_id).first()
            self.assertIsNone(media)
            self.assertIsNone(analysis)
        finally:
            db.close()

    def test_multipart_deletedfiles_json_string_matches_by_path(self) -> None:
        media_id = self._add_path_only_delete_queue_seed()
        response = self.client.post(
            "/webhook/emby?token=tok",
            files={
                "Event": (None, "deep.delete"),
                "DeletedFiles": (None, '["/mnt/media/path-only.mkv"]'),
                "Description": (None, "Mount Paths:\n/mnt/media/path-only.mkv\n"),
                "Token": (None, "tok"),
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["updated"], 1)

        db = self.SessionLocal()
        try:
            queue = db.query(DeleteQueue).filter(DeleteQueue.item_id == media_id).first()
            self.assertIsNotNone(queue)
            self.assertEqual(queue.delete_status, "done")
            self.assertIn("/mnt/media/path-only.mkv", queue.deleted_paths_json)

            media = db.query(MediaItem).filter(MediaItem.id == media_id).first()
            analysis = db.query(AnalysisResult).filter(AnalysisResult.item_id == media_id).first()
            self.assertIsNone(media)
            self.assertIsNone(analysis)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
