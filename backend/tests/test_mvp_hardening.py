import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import AnalysisResult, AppSettings, Base, DeleteQueue, MediaItem, OperationLog
from app.schemas.delete_preview import DeleteExecutePayload, DeleteWebhookEvent, DeleteWebhookPayload
from app.api.webhook import _parse_mount_paths_from_description, _process_new_item_event
from app.services.analysis_service import apply_manual_override
from app.services.delete_preview_service import execute_deletes, list_delete_queue_status, process_delete_webhook
from app.services import delete_preview_service
from app.services.sync_service import _has_chinese_subtitle, _is_playable_media_item


class _FakeShenyiClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 15.0) -> None:
        self.base_url = base_url
        self.api_key = api_key

    def delete_version(self, emby_item_id: str) -> tuple[int, str]:
        return 200, "success"


class _RetryThenSuccessShenyiClient:
    attempts: dict[str, int] = {}

    def __init__(self, base_url: str, api_key: str, timeout: float = 15.0) -> None:
        self.base_url = base_url
        self.api_key = api_key

    def delete_version(self, emby_item_id: str) -> tuple[int, str]:
        cnt = int(self.attempts.get(emby_item_id, 0))
        self.attempts[emby_item_id] = cnt + 1
        if cnt < 2:
            raise delete_preview_service.ShenyiServerError("temporary failure", status_code=500)
        return 204, "success"


class _AlwaysFailShenyiClient:
    attempts: dict[str, int] = {}

    def __init__(self, base_url: str, api_key: str, timeout: float = 15.0) -> None:
        self.base_url = base_url
        self.api_key = api_key

    def delete_version(self, emby_item_id: str) -> tuple[int, str]:
        cnt = int(self.attempts.get(emby_item_id, 0))
        self.attempts[emby_item_id] = cnt + 1
        raise delete_preview_service.ShenyiServerError("permanent failure", status_code=500)


class _SingleSourceEmbyClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0, retries: int = 3, retry_backoff_seconds: float = 0.5) -> None:
        self.base_url = base_url
        self.api_key = api_key

    def get_item_detail(self, user_id: str, item_id: str) -> dict:
        return {"Id": item_id, "MediaSources": [{"Id": f"ms-{item_id}"}]}

    def user_item_exists(self, user_id: str, item_id: str) -> bool:
        return True


class MvPHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _media(self, **kwargs) -> MediaItem:
        base = {
            "emby_item_id": kwargs.get("emby_item_id", "m1"),
            "media_source_id": kwargs.get("media_source_id", "src1"),
            "library_name": kwargs.get("library_name", "Movies"),
            "item_type": kwargs.get("item_type", "Movie"),
            "title": kwargs.get("title", "T"),
            "series_title": kwargs.get("series_title", ""),
            "tmdb_id": kwargs.get("tmdb_id", "100"),
            "subtitle_streams_json": "[]",
            "has_chinese_subtitle": kwargs.get("has_chinese_subtitle", 0),
            "eligible_for_dedup": kwargs.get("eligible_for_dedup", 1),
            "is_excluded_path": kwargs.get("is_excluded_path", 0),
            "path": kwargs.get("path", "/a.mkv"),
            "raw_json": "{}",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        return MediaItem(**base)

    def _analysis_row(self, **kwargs) -> AnalysisResult:
        base = {
            "group_key": kwargs.get("group_key", "movie:100"),
            "media_kind": kwargs.get("media_kind", "movie"),
            "tmdb_id": kwargs.get("tmdb_id", "100"),
            "title": kwargs.get("title", "T"),
            "season_number": kwargs.get("season_number"),
            "episode_number": kwargs.get("episode_number"),
            "item_id": kwargs["item_id"],
            "emby_item_id": kwargs.get("emby_item_id", "x"),
            "action": kwargs.get("action", "delete_candidate"),
            "reason_json": "{}",
            "is_manual_override": kwargs.get("is_manual_override", 0),
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        return AnalysisResult(**base)

    def test_sync_path_playable_filter(self) -> None:
        self.assertTrue(_is_playable_media_item({"Type": "Movie", "IsFolder": False, "Path": "/a.mkv"}))
        self.assertTrue(_is_playable_media_item({"Type": "Episode", "IsFolder": False, "Path": "/b.mkv"}))
        self.assertFalse(_is_playable_media_item({"Type": "Series", "IsFolder": False, "Path": "/s"}))
        self.assertFalse(_is_playable_media_item({"Type": "Movie", "IsFolder": True, "Path": "/folder"}))
        self.assertTrue(_is_playable_media_item({"Type": "Movie", "IsFolder": False}))

    def test_subtitle_detection(self) -> None:
        item_lang = {"MediaStreams": [{"Type": "Subtitle", "Language": "zh", "Title": "Chinese"}]}
        item_title = {
            "MediaStreams": [
                {
                    "Type": "Subtitle",
                    "Language": "en",
                    "Title": "\u7b80\u4f53 \u4e2d\u6587\u5b57\u5e55",
                }
            ]
        }
        item_none = {"MediaStreams": [{"Type": "Subtitle", "Language": "en", "Title": "English"}]}

        self.assertEqual(_has_chinese_subtitle(item_lang), 1)
        self.assertEqual(_has_chinese_subtitle(item_title), 1)
        self.assertEqual(_has_chinese_subtitle(item_none), 0)

    def test_override_sets_keep_manual_and_preserves_protected(self) -> None:
        db = self.SessionLocal()
        try:
            keep = self._media(emby_item_id="k", is_excluded_path=0)
            cand = self._media(emby_item_id="c", is_excluded_path=0)
            prot = self._media(emby_item_id="p", is_excluded_path=1)
            db.add_all([keep, cand, prot])
            db.commit()
            db.refresh(keep)
            db.refresh(cand)
            db.refresh(prot)

            db.add_all(
                [
                    self._analysis_row(item_id=keep.id, emby_item_id="k", action="keep_recommended"),
                    self._analysis_row(item_id=cand.id, emby_item_id="c", action="delete_candidate"),
                    self._analysis_row(item_id=prot.id, emby_item_id="p", action="protected"),
                ]
            )
            db.commit()

            result = apply_manual_override(db, "movie:100", keep_item_id=cand.id)
            self.assertEqual(result.status, "ok")

            rows = db.query(AnalysisResult).order_by(AnalysisResult.item_id.asc()).all()
            actions = {r.item_id: r.action for r in rows}
            self.assertEqual(actions[cand.id], "keep_manual")
            self.assertEqual(actions[prot.id], "protected")
            self.assertNotEqual(actions[prot.id], "delete_candidate")
        finally:
            db.close()

    def test_delete_execution_safety_uses_delete_candidates_only(self) -> None:
        db = self.SessionLocal()
        old_client = delete_preview_service.ShenyiClient
        delete_preview_service.ShenyiClient = _FakeShenyiClient
        try:
            db.add(
                AppSettings(
                    emby_base_url="http://emby",
                    emby_api_key="k",
                    selected_libraries_json="[]",
                    excluded_paths_json="[]",
                    sync_concurrency=6,
                    shenyi_base_url="http://shenyi",
                    shenyi_api_key="sk",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00",
                )
            )

            del_item = self._media(emby_item_id="d1", is_excluded_path=0)
            keep_item = self._media(emby_item_id="k1", is_excluded_path=0)
            prot_item = self._media(emby_item_id="p1", is_excluded_path=1)
            db.add_all([del_item, keep_item, prot_item])
            db.commit()
            db.refresh(del_item)
            db.refresh(keep_item)
            db.refresh(prot_item)
            del_item_id = int(del_item.id)
            keep_item_id = int(keep_item.id)
            prot_item_id = int(prot_item.id)

            db.add_all(
                [
                    self._analysis_row(item_id=del_item_id, emby_item_id="d1", action="delete_candidate"),
                    self._analysis_row(item_id=keep_item_id, emby_item_id="k1", action="keep_manual"),
                    self._analysis_row(item_id=prot_item_id, emby_item_id="p1", action="protected"),
                ]
            )
            db.commit()

            response = execute_deletes(db, DeleteExecutePayload(group_ids=["movie:100"]))
            self.assertEqual(response.success_count, 0)
            self.assertEqual(response.failed_count, 0)
            self.assertEqual(len(response.results), 1)
            self.assertEqual(response.results[0].emby_item_id, "d1")
            self.assertEqual(response.results[0].delete_status, "in_progress")
            self.assertTrue(response.results[0].id is not None)
            self.assertTrue(bool(response.results[0].deleted_paths))

            # Queue mode keeps local rows until webhook confirms deletion.
            self.assertIsNotNone(db.query(MediaItem).filter(MediaItem.id == del_item_id).first())
            self.assertIsNotNone(db.query(MediaItem).filter(MediaItem.id == keep_item_id).first())
            self.assertIsNotNone(db.query(MediaItem).filter(MediaItem.id == prot_item_id).first())

            queue_rows = db.query(DeleteQueue).all()
            self.assertEqual(len(queue_rows), 1)
            self.assertEqual(queue_rows[0].delete_status, "in_progress")
            self.assertEqual(queue_rows[0].retry_count, 1)

            webhook_result = process_delete_webhook(db, DeleteWebhookPayload(ItemId="d1", DeletedFiles=["/a.mkv"]))
            self.assertEqual(webhook_result.updated, 1)

            self.assertIsNone(db.query(MediaItem).filter(MediaItem.id == del_item_id).first())
            self.assertIsNotNone(db.query(MediaItem).filter(MediaItem.id == keep_item_id).first())
            self.assertIsNotNone(db.query(MediaItem).filter(MediaItem.id == prot_item_id).first())

            queue_row = db.query(DeleteQueue).first()
            self.assertIsNotNone(queue_row)
            self.assertEqual(queue_row.delete_status, "done")
            self.assertIn("/a.mkv", queue_row.deleted_paths_json)

            logs = db.query(OperationLog).all()
            self.assertGreaterEqual(len(logs), 2)
            self.assertTrue(any(log.item_id == str(del_item_id) and log.status == "in_progress" for log in logs))
            self.assertTrue(any(log.item_id == str(del_item_id) and log.status == "done" for log in logs))
        finally:
            delete_preview_service.ShenyiClient = old_client
            db.close()

    def test_delete_execution_retries_then_success(self) -> None:
        db = self.SessionLocal()
        old_client = delete_preview_service.ShenyiClient
        delete_preview_service.ShenyiClient = _RetryThenSuccessShenyiClient
        _RetryThenSuccessShenyiClient.attempts = {}
        try:
            db.add(
                AppSettings(
                    emby_base_url="http://emby",
                    emby_api_key="k",
                    selected_libraries_json="[]",
                    excluded_paths_json="[]",
                    sync_concurrency=6,
                    shenyi_base_url="http://shenyi",
                    shenyi_api_key="sk",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00",
                )
            )
            row = self._media(emby_item_id="retry-ok", path="/retry-ok.mkv")
            db.add(row)
            db.commit()
            db.refresh(row)
            db.add(self._analysis_row(item_id=row.id, emby_item_id="retry-ok", action="delete_candidate"))
            db.commit()

            response = execute_deletes(db, DeleteExecutePayload(group_ids=["movie:100"]))
            self.assertEqual(response.success_count, 0)
            self.assertEqual(response.failed_count, 0)
            self.assertEqual(_RetryThenSuccessShenyiClient.attempts.get("retry-ok"), 3)

            queue_row = db.query(DeleteQueue).first()
            self.assertIsNotNone(queue_row)
            self.assertEqual(queue_row.delete_status, "in_progress")
            self.assertEqual(queue_row.status_code, 204)
            self.assertEqual(queue_row.retry_count, 3)
        finally:
            delete_preview_service.ShenyiClient = old_client
            db.close()

    def test_delete_execution_retries_then_failed(self) -> None:
        db = self.SessionLocal()
        old_client = delete_preview_service.ShenyiClient
        delete_preview_service.ShenyiClient = _AlwaysFailShenyiClient
        _AlwaysFailShenyiClient.attempts = {}
        try:
            db.add(
                AppSettings(
                    emby_base_url="http://emby",
                    emby_api_key="k",
                    selected_libraries_json="[]",
                    excluded_paths_json="[]",
                    sync_concurrency=6,
                    shenyi_base_url="http://shenyi",
                    shenyi_api_key="sk",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00",
                )
            )
            row = self._media(emby_item_id="retry-failed", path="/retry-failed.mkv")
            db.add(row)
            db.commit()
            db.refresh(row)
            db.add(self._analysis_row(item_id=row.id, emby_item_id="retry-failed", action="delete_candidate"))
            db.commit()

            response = execute_deletes(db, DeleteExecutePayload(group_ids=["movie:100"]))
            self.assertEqual(response.success_count, 0)
            self.assertEqual(response.failed_count, 1)
            self.assertEqual(_AlwaysFailShenyiClient.attempts.get("retry-failed"), 3)

            queue_row = db.query(DeleteQueue).first()
            self.assertIsNotNone(queue_row)
            self.assertEqual(queue_row.delete_status, "failed")
            self.assertIn("retried 3 times", queue_row.message)
            self.assertEqual(queue_row.retry_count, 3)
        finally:
            delete_preview_service.ShenyiClient = old_client
            db.close()

    def test_delete_preflight_rejects_non_multiversion_target(self) -> None:
        db = self.SessionLocal()
        old_client = delete_preview_service.ShenyiClient
        old_emby_client = delete_preview_service.EmbyClient
        try:
            delete_preview_service.ShenyiClient = _FakeShenyiClient
            delete_preview_service.EmbyClient = _SingleSourceEmbyClient
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
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00",
                )
            )
            row = self._media(emby_item_id="preflight-fail", path="/preflight-fail.mkv")
            db.add(row)
            db.commit()
            db.refresh(row)
            db.add(self._analysis_row(item_id=row.id, emby_item_id="preflight-fail", action="delete_candidate"))
            db.commit()

            response = execute_deletes(db, DeleteExecutePayload(group_ids=["movie:100"]))
            self.assertEqual(response.success_count, 0)
            self.assertEqual(response.failed_count, 1)
            self.assertEqual(len(response.results), 1)
            self.assertEqual(response.results[0].status_reason, "manual_cleanup_required")
            self.assertIn("not merged multi-version", response.results[0].message)
            queue_rows = db.query(DeleteQueue).all()
            self.assertEqual(len(queue_rows), 0)
        finally:
            delete_preview_service.ShenyiClient = old_client
            delete_preview_service.EmbyClient = old_emby_client
            db.close()

    def test_invalid_webhook_marks_queue_failed(self) -> None:
        db = self.SessionLocal()
        try:
            row = DeleteQueue(
                group_id="movie:100",
                item_id=123,
                delete_target_item_id="x1",
                emby_item_id="x1",
                deleted_paths_json="[]",
                delete_status="in_progress",
                retry_count=1,
                status_code=204,
                message="waiting webhook",
                created_at="2026-01-01T00:00:00",
                updated_at="2026-01-01T00:00:00",
            )
            db.add(row)
            db.commit()

            result = process_delete_webhook(
                db,
                DeleteWebhookPayload(events=[DeleteWebhookEvent()]),
            )
            self.assertEqual(result.updated, 0)
            queue_row = db.query(DeleteQueue).first()
            self.assertIsNotNone(queue_row)
            self.assertEqual(queue_row.delete_status, "in_progress")
        finally:
            db.close()

    def test_queue_status_latest_only_dedupes_by_target(self) -> None:
        db = self.SessionLocal()
        try:
            db.add(
                AppSettings(
                    emby_base_url="http://emby",
                    emby_api_key="k",
                    selected_libraries_json="[]",
                    excluded_paths_json="[]",
                    sync_concurrency=6,
                    shenyi_base_url="http://shenyi",
                    shenyi_api_key="sk",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00",
                )
            )
            db.add_all(
                [
                    DeleteQueue(
                        group_id="movie:100",
                        item_id=1,
                        delete_target_item_id="target-1",
                        emby_item_id="emby-1",
                        deleted_paths_json="[]",
                        delete_status="failed",
                        status_reason="timeout_exists",
                        retry_count=3,
                        status_code=500,
                        message="old failed",
                        created_at="2026-01-01T00:00:00",
                        updated_at="2026-01-01T00:00:00",
                    ),
                    DeleteQueue(
                        group_id="movie:100",
                        item_id=1,
                        delete_target_item_id="target-1",
                        emby_item_id="emby-1",
                        deleted_paths_json="[]",
                        delete_status="done",
                        status_reason="webhook_confirmed",
                        retry_count=3,
                        status_code=204,
                        message="new success",
                        created_at="2026-01-01T00:01:00",
                        updated_at="2026-01-01T00:01:00",
                    ),
                ]
            )
            db.commit()

            latest = list_delete_queue_status(db, ids=[], limit=20, latest_only=True)
            self.assertEqual(len(latest.items), 1)
            self.assertEqual(latest.items[0].delete_status, "done")
            all_rows = list_delete_queue_status(db, ids=[], limit=20, latest_only=False)
            self.assertEqual(len(all_rows.items), 2)
        finally:
            db.close()

    def test_in_progress_timeout_probe_confirms_done(self) -> None:
        db = self.SessionLocal()
        old_emby_client = delete_preview_service.EmbyClient
        old_interval = delete_preview_service.DEFAULT_IN_PROGRESS_RETRY_INTERVAL_SECONDS
        try:
            class _ProbeMissingEmbyClient:
                def __init__(self, base_url: str, api_key: str, timeout: float = 10.0, retries: int = 3, retry_backoff_seconds: float = 0.5) -> None:
                    self.base_url = base_url
                    self.api_key = api_key

                def item_exists(self, item_id: str) -> bool:
                    return False

            delete_preview_service.EmbyClient = _ProbeMissingEmbyClient
            delete_preview_service.DEFAULT_IN_PROGRESS_RETRY_INTERVAL_SECONDS = 1
            db.add(
                AppSettings(
                    emby_base_url="http://emby",
                    emby_api_key="k",
                    selected_libraries_json="[]",
                    excluded_paths_json="[]",
                    sync_concurrency=6,
                    shenyi_base_url="http://shenyi",
                    shenyi_api_key="sk",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00",
                )
            )
            media = self._media(emby_item_id="probe-1", path="/probe-1.mkv")
            keep = self._media(emby_item_id="probe-keep", path="/probe-keep.mkv")
            db.add(media)
            db.add(keep)
            db.commit()
            db.refresh(media)
            db.refresh(keep)
            db.add(
                self._analysis_row(
                    group_key="movie:100",
                    item_id=int(keep.id),
                    emby_item_id="probe-keep",
                    action="keep_recommended",
                )
            )
            db.add(
                self._analysis_row(
                    group_key="movie:100",
                    item_id=int(media.id),
                    emby_item_id="probe-1",
                    action="delete_candidate",
                )
            )
            db.add(
                DeleteQueue(
                    group_id="movie:100",
                    item_id=int(media.id),
                    delete_target_item_id="probe-target-1",
                    emby_item_id="probe-1",
                    deleted_paths_json='["/probe-1.mkv"]',
                    delete_status="in_progress",
                    status_reason="accepted",
                    retry_count=3,
                    status_code=204,
                    message="waiting webhook",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2020-01-01T00:00:00",
                )
            )
            db.commit()

            resp = list_delete_queue_status(db, ids=[], limit=20, latest_only=True)
            self.assertEqual(len(resp.items), 1)
            self.assertEqual(resp.items[0].delete_status, "done")
            self.assertEqual(resp.items[0].status_reason, "probe_confirmed")
            remaining_group_rows = db.query(AnalysisResult).filter(AnalysisResult.group_key == "movie:100").count()
            self.assertEqual(remaining_group_rows, 0)
        finally:
            delete_preview_service.EmbyClient = old_emby_client
            delete_preview_service.DEFAULT_IN_PROGRESS_RETRY_INTERVAL_SECONDS = old_interval
            db.close()

    def test_deep_delete_mount_paths_parsing_and_cleanup(self) -> None:
        db = self.SessionLocal()
        try:
            media = self._media(emby_item_id="deep-1", path="/mnt/media/a.mkv")
            db.add(media)
            db.commit()
            db.refresh(media)
            media_id = int(media.id)
            db.add(self._analysis_row(item_id=media.id, emby_item_id="deep-1", action="delete_candidate"))
            db.add(
                DeleteQueue(
                    group_id="movie:100",
                    item_id=media.id,
                    delete_target_item_id="deep-1",
                    emby_item_id="deep-1",
                    deleted_paths_json='["/mnt/media/a.mkv"]',
                    delete_status="in_progress",
                    retry_count=1,
                    status_code=204,
                    message="waiting webhook",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00",
                )
            )
            db.commit()

            desc = "Something happened\nMount Paths:\n/mnt/media/a.mkv\n/mnt/media/b.mkv\n"
            parsed = _parse_mount_paths_from_description(desc)
            self.assertIn("/mnt/media/a.mkv", parsed)
            self.assertIn("/mnt/media/b.mkv", parsed)

            result = process_delete_webhook(
                db,
                DeleteWebhookPayload(
                    Event="deep.delete",
                    Description=desc,
                    DeletedFiles=parsed,
                ),
            )
            self.assertEqual(result.updated, 1)
            self.assertIsNone(db.query(MediaItem).filter(MediaItem.id == media_id).first())
            queue = db.query(DeleteQueue).first()
            self.assertIsNotNone(queue)
            self.assertEqual(queue.delete_status, "done")
            self.assertIn("/mnt/media/a.mkv", queue.deleted_paths_json)
        finally:
            db.close()

    def test_library_new_item_realtime_ingest(self) -> None:
        db = self.SessionLocal()
        try:
            db.add(
                AppSettings(
                    emby_base_url="http://emby",
                    emby_api_key="k",
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

            payload = DeleteWebhookPayload(
                Event="library.new",
                Item={
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
                            "MediaStreams": [
                                {"Type": "Video", "Codec": "h264", "Width": 1920, "Height": 1080},
                            ],
                        }
                    ],
                },
            )
            _process_new_item_event(db, payload)
            rows = db.query(MediaItem).filter(MediaItem.emby_item_id == "new-item-1").all()
            self.assertGreaterEqual(len(rows), 1)
            self.assertTrue(any(str(r.path) == "/mnt/media/new-movie.mkv" for r in rows))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()

