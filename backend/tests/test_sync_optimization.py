import os
import tempfile
import threading
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import AppSettings, Base, MediaItem
from app.services import sync_service


class _FakeAnalysisResult:
    def __init__(self, groups: int = 0) -> None:
        self.groups = groups


class _BaseFakeEmbyClient:
    views: list[dict] = []
    library_items: dict[str, list[dict]] = {}
    detail_items: dict[str, dict] = {}
    detail_fail_ids: set[str] = set()
    detail_calls: list[str] = []
    page_gate_start_index: int | None = None
    page_seen_event: threading.Event | None = None
    page_release_event: threading.Event | None = None

    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0, retries: int = 3, retry_backoff_seconds: float = 0.5) -> None:
        self.base_url = base_url
        self.api_key = api_key

    @classmethod
    def reset(cls) -> None:
        cls.views = []
        cls.library_items = {}
        cls.detail_items = {}
        cls.detail_fail_ids = set()
        cls.detail_calls = []
        cls.page_gate_start_index = None
        cls.page_seen_event = None
        cls.page_release_event = None

    def list_user_views(self, user_id: str) -> list[dict[str, str]]:
        return list(self.views)

    def list_library_items_page(self, user_id: str, library_id: str, start_index: int, limit: int = 200) -> tuple[list[dict], int]:
        if self.page_gate_start_index is not None and start_index == self.page_gate_start_index:
            if self.page_seen_event is not None:
                self.page_seen_event.set()
            if self.page_release_event is not None:
                self.page_release_event.wait(timeout=5)

        items = list(self.library_items.get(library_id, []))
        page = items[start_index : start_index + limit]
        return page, len(items)

    def get_item_detail(self, user_id: str, item_id: str) -> dict:
        self.detail_calls.append(item_id)
        if item_id in self.detail_fail_ids:
            raise RuntimeError(f"detail failed: {item_id}")
        return dict(self.detail_items[item_id])


class SyncOptimizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "sync_opt.db")
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)

        self.original_session_local = sync_service.SessionLocal
        self.original_client = sync_service.EmbyClient
        self.original_page_size = sync_service._LIBRARY_PAGE_SIZE
        self.original_run_analysis = sync_service.run_analysis

        sync_service.SessionLocal = self.SessionLocal
        sync_service.EmbyClient = _BaseFakeEmbyClient
        sync_service._LIBRARY_PAGE_SIZE = 1
        sync_service.run_analysis = lambda db: _FakeAnalysisResult(groups=0)
        _BaseFakeEmbyClient.reset()

        db = self.SessionLocal()
        try:
            db.add(
                AppSettings(
                    emby_base_url="http://emby",
                    emby_api_key="k",
                    emby_user_id="u",
                    selected_libraries_json='["TV"]',
                    excluded_paths_json="[]",
                    sync_concurrency=4,
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

        sync_service.sync_status_tracker.start()

    def tearDown(self) -> None:
        sync_service.SessionLocal = self.original_session_local
        sync_service.EmbyClient = self.original_client
        sync_service._LIBRARY_PAGE_SIZE = self.original_page_size
        sync_service.run_analysis = self.original_run_analysis
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _movie_item(self, item_id: str) -> dict:
        return {
            "Id": item_id,
            "Type": "Movie",
            "Name": f"Movie {item_id}",
            "Path": f"/mnt/media/{item_id}.mkv",
            "ProviderIds": {"Tmdb": "1001"},
            "ProductionYear": 2024,
            "DateCreated": "2026-01-01T00:00:00",
            "DateLastMediaAdded": "2026-01-01T00:00:00",
            "MediaSources": [
                {
                    "Id": f"mediasource_{item_id}",
                    "Path": f"/mnt/media/{item_id}.mkv",
                    "Container": "mkv",
                    "Size": 1234,
                    "Bitrate": 2000,
                    "MediaStreams": [
                        {"Type": "Video", "Codec": "h264", "Width": 1920, "Height": 1080},
                        {"Type": "Audio", "Codec": "aac", "Channels": 2, "IsDefault": True},
                    ],
                }
            ],
        }

    def _episode_item_missing_series(self, item_id: str) -> dict:
        return {
            "Id": item_id,
            "Type": "Episode",
            "Name": f"Episode {item_id}",
            "Path": f"/mnt/media/{item_id}.mkv",
            "ProviderIds": {"Tmdb": "2001"},
            "ParentIndexNumber": 1,
            "IndexNumber": 2,
            "MediaSources": [
                {
                    "Id": f"mediasource_{item_id}",
                    "Path": f"/mnt/media/{item_id}.mkv",
                    "Container": "mkv",
                    "MediaStreams": [
                        {"Type": "Video", "Codec": "h264", "Width": 1920, "Height": 1080},
                    ],
                }
            ],
        }

    def _episode_detail(self, item_id: str) -> dict:
        item = self._episode_item_missing_series(item_id)
        item["SeriesName"] = "Test Show"
        item["ProductionYear"] = 2023
        item["DateCreated"] = "2026-01-01T00:00:00"
        item["DateLastMediaAdded"] = "2026-01-01T00:00:00"
        return item

    def test_complete_list_items_skip_detail_fallback(self) -> None:
        _BaseFakeEmbyClient.views = [{"id": "lib-tv", "name": "TV", "collection_type": "tvshows"}]
        _BaseFakeEmbyClient.library_items = {"lib-tv": [self._movie_item("movie-1")]}

        sync_service.run_full_sync_workflow()

        status = sync_service.sync_status_tracker.get_status()
        self.assertEqual(_BaseFakeEmbyClient.detail_calls, [])
        self.assertEqual(status.detail_requests_total, 0)
        self.assertEqual(status.items_discovered, 1)
        self.assertEqual(status.items_synced, 1)

        db = self.SessionLocal()
        try:
            rows = db.query(MediaItem).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].emby_item_id, "movie-1")
        finally:
            db.close()

    def test_fallback_only_for_missing_fields_and_status_updates_mid_sync(self) -> None:
        page_seen = threading.Event()
        page_release = threading.Event()
        _BaseFakeEmbyClient.views = [{"id": "lib-tv", "name": "TV", "collection_type": "tvshows"}]
        _BaseFakeEmbyClient.library_items = {
            "lib-tv": [
                self._episode_item_missing_series("ep-1"),
                self._movie_item("movie-2"),
            ]
        }
        _BaseFakeEmbyClient.detail_items = {"ep-1": self._episode_detail("ep-1")}
        _BaseFakeEmbyClient.page_gate_start_index = 1
        _BaseFakeEmbyClient.page_seen_event = page_seen
        _BaseFakeEmbyClient.page_release_event = page_release

        worker = threading.Thread(target=sync_service.run_full_sync_workflow)
        worker.start()
        self.assertTrue(page_seen.wait(timeout=5))

        status_during = sync_service.sync_status_tracker.get_status()
        self.assertEqual(status_during.current_page, 1)
        self.assertEqual(status_during.items_discovered, 1)
        self.assertEqual(status_during.libraries_total, 1)
        self.assertEqual(status_during.detail_requests_total, 1)

        page_release.set()
        worker.join(timeout=10)
        self.assertFalse(worker.is_alive())

        status = sync_service.sync_status_tracker.get_status()
        self.assertEqual(_BaseFakeEmbyClient.detail_calls, ["ep-1"])
        self.assertEqual(status.detail_requests_completed, 1)
        self.assertEqual(status.items_discovered, 2)
        self.assertEqual(status.items_synced, 2)

        db = self.SessionLocal()
        try:
            rows = db.query(MediaItem).order_by(MediaItem.emby_item_id.asc()).all()
            self.assertEqual(len(rows), 2)
            episode = next(row for row in rows if row.emby_item_id == "ep-1")
            self.assertEqual(episode.series_title, "Test Show")
            self.assertEqual(episode.season_number, 1)
            self.assertEqual(episode.episode_number, 2)
        finally:
            db.close()

    def test_detail_fallback_failure_does_not_abort_sync(self) -> None:
        _BaseFakeEmbyClient.views = [{"id": "lib-tv", "name": "TV", "collection_type": "tvshows"}]
        _BaseFakeEmbyClient.library_items = {
            "lib-tv": [
                self._movie_item("movie-ok"),
                self._episode_item_missing_series("ep-fail"),
            ]
        }
        _BaseFakeEmbyClient.detail_fail_ids = {"ep-fail"}

        sync_service.run_full_sync_workflow()

        status = sync_service.sync_status_tracker.get_status()
        self.assertEqual(status.last_result, "success")
        self.assertEqual(status.failed_items, 1)
        self.assertEqual(status.detail_requests_total, 1)
        self.assertEqual(status.detail_requests_completed, 1)
        self.assertEqual(status.items_synced, 1)

        db = self.SessionLocal()
        try:
            rows = db.query(MediaItem).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].emby_item_id, "movie-ok")
        finally:
            db.close()

    def test_sync_overwrites_selected_library_and_preserves_unselected_library(self) -> None:
        _BaseFakeEmbyClient.views = [{"id": "lib-tv", "name": "TV", "collection_type": "tvshows"}]
        _BaseFakeEmbyClient.library_items = {"lib-tv": [self._movie_item("movie-tv-new")]}

        db = self.SessionLocal()
        try:
            db.add_all(
                [
                    MediaItem(
                        emby_item_id="movie-tv-old",
                        media_source_id="ms-tv-old",
                        delete_target_item_id="movie-tv-old",
                        library_name="TV",
                        item_type="Movie",
                        title="Old TV Item",
                        tmdb_id="9001",
                        path="/mnt/old/tv-old.mkv",
                        eligible_for_dedup=1,
                    ),
                    MediaItem(
                        emby_item_id="movie-movie-old",
                        media_source_id="ms-movie-old",
                        delete_target_item_id="movie-movie-old",
                        library_name="Movies",
                        item_type="Movie",
                        title="Old Movie Library Item",
                        tmdb_id="9002",
                        path="/mnt/old/movie-old.mkv",
                        eligible_for_dedup=1,
                    ),
                ]
            )
            db.commit()
        finally:
            db.close()

        sync_service.run_full_sync_workflow()

        db = self.SessionLocal()
        try:
            rows = db.query(MediaItem).order_by(MediaItem.library_name.asc(), MediaItem.emby_item_id.asc()).all()
            ids = [row.emby_item_id for row in rows]
            self.assertIn("movie-tv-new", ids)
            self.assertIn("movie-movie-old", ids)
            self.assertNotIn("movie-tv-old", ids)
            self.assertEqual(len(rows), 2)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
