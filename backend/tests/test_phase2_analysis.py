import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import AnalysisResult, Base, MediaItem
from app.schemas.rules import RuleItem, RulesPayload
from app.services.analysis_service import run_analysis
from app.services.comparator_service import compare_items
from app.services.rules_service import save_rules


class Phase2AnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _media(self, **kwargs) -> MediaItem:
        base = {
            "emby_item_id": kwargs.get("emby_item_id", "x"),
            "library_name": kwargs.get("library_name", "Movies"),
            "item_type": kwargs.get("item_type", "Movie"),
            "title": kwargs.get("title", "T"),
            "series_title": kwargs.get("series_title", ""),
            "tmdb_id": kwargs.get("tmdb_id", "100"),
            "season_number": kwargs.get("season_number"),
            "episode_number": kwargs.get("episode_number"),
            "runtime_seconds": kwargs.get("runtime_seconds"),
            "effect_label": kwargs.get("effect_label", ""),
            "resolution_label": kwargs.get("resolution_label", "1080p"),
            "bit_depth": kwargs.get("bit_depth"),
            "bitrate": kwargs.get("bitrate"),
            "video_codec": kwargs.get("video_codec", "h264"),
            "file_size": kwargs.get("file_size"),
            "date_added": kwargs.get("date_added", ""),
            "frame_rate": kwargs.get("frame_rate"),
            "has_chinese_subtitle": kwargs.get("has_chinese_subtitle", 0),
            "eligible_for_dedup": kwargs.get("eligible_for_dedup", 1),
            "is_excluded_path": kwargs.get("is_excluded_path", 0),
            "path": kwargs.get("path", "/a.mkv"),
            "subtitle_streams_json": "[]",
            "raw_json": "{}",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        return MediaItem(**base)

    def test_movie_grouping(self) -> None:
        db = self.SessionLocal()
        try:
            db.add_all(
                [
                    self._media(emby_item_id="m1", tmdb_id="200", item_type="Movie", title="A"),
                    self._media(emby_item_id="m2", tmdb_id="200", item_type="Movie", title="A"),
                    self._media(emby_item_id="m3", tmdb_id="201", item_type="Movie", title="B"),
                ]
            )
            db.commit()

            result = run_analysis(db)
            self.assertEqual(result.groups, 1)

            rows = db.query(AnalysisResult).all()
            self.assertTrue(all(r.group_key == "movie:200" for r in rows))
        finally:
            db.close()

    def test_episodic_grouping(self) -> None:
        db = self.SessionLocal()
        try:
            db.add_all(
                [
                    self._media(
                        emby_item_id="e1",
                        item_type="Episode",
                        tmdb_id="300",
                        season_number=1,
                        episode_number=2,
                        title="Ep",
                        series_title="Show",
                    ),
                    self._media(
                        emby_item_id="e2",
                        item_type="Episode",
                        tmdb_id="300",
                        season_number=1,
                        episode_number=2,
                        title="Ep",
                        series_title="Show",
                    ),
                    self._media(
                        emby_item_id="e3",
                        item_type="Episode",
                        tmdb_id="300",
                        season_number=1,
                        episode_number=3,
                        title="Ep2",
                        series_title="Show",
                    ),
                ]
            )
            db.commit()

            result = run_analysis(db)
            self.assertEqual(result.groups, 1)

            rows = db.query(AnalysisResult).all()
            self.assertTrue(all(r.group_key == "episode:300:1:2" for r in rows))
        finally:
            db.close()

    def test_subtitle_comparison(self) -> None:
        a = self._media(emby_item_id="a", has_chinese_subtitle=1)
        b = self._media(emby_item_id="b", has_chinese_subtitle=0)
        rules = [{"id": "subtitle", "enabled": True, "order": 1, "priority": ["zh", "other", "none"]}]

        result, rule = compare_items(a, b, rules)
        self.assertEqual(result, 1)
        self.assertEqual(rule, "subtitle")

        c = self._media(emby_item_id="c", has_chinese_subtitle=1)
        d = self._media(emby_item_id="d", has_chinese_subtitle=1)
        result2, _ = compare_items(c, d, rules)
        self.assertEqual(result2, 0)

    def test_excluded_path_protection(self) -> None:
        db = self.SessionLocal()
        try:
            save_rules(
                db,
                RulesPayload(
                    rules=[
                        RuleItem(id="resolution", enabled=True, order=1, priority=["4k", "1080p", "720p", "480p"])
                    ]
                ),
            )

            db.add_all(
                [
                    self._media(emby_item_id="x1", tmdb_id="400", resolution_label="4k", is_excluded_path=0),
                    self._media(emby_item_id="x2", tmdb_id="400", resolution_label="720p", is_excluded_path=1),
                ]
            )
            db.commit()

            run_analysis(db)
            rows = db.query(AnalysisResult).order_by(AnalysisResult.item_id.asc()).all()
            actions = {row.emby_item_id: row.action for row in rows}

            self.assertEqual(actions["x1"], "keep_recommended")
            self.assertEqual(actions["x2"], "protected")
            self.assertNotEqual(actions["x2"], "delete_candidate")
        finally:
            db.close()

    def test_ordered_rule_comparison(self) -> None:
        db = self.SessionLocal()
        try:
            db.add_all(
                [
                    self._media(emby_item_id="r1", tmdb_id="500", has_chinese_subtitle=1, resolution_label="720p"),
                    self._media(emby_item_id="r2", tmdb_id="500", has_chinese_subtitle=0, resolution_label="4k"),
                ]
            )
            db.commit()

            save_rules(
                db,
                RulesPayload(
                    rules=[
                        RuleItem(id="subtitle", enabled=True, order=1, priority=["zh", "other", "none"]),
                        RuleItem(id="resolution", enabled=True, order=2, priority=["4k", "1080p", "720p", "480p"]),
                    ]
                ),
            )
            run_analysis(db)
            keep_1 = db.query(AnalysisResult).filter(AnalysisResult.action == "keep_recommended").first()
            self.assertIsNotNone(keep_1)
            self.assertEqual(keep_1.emby_item_id, "r1")

            save_rules(
                db,
                RulesPayload(
                    rules=[
                        RuleItem(id="resolution", enabled=True, order=1, priority=["4k", "1080p", "720p", "480p"]),
                        RuleItem(id="subtitle", enabled=True, order=2, priority=["zh", "other", "none"]),
                    ]
                ),
            )
            run_analysis(db)
            keep_2 = db.query(AnalysisResult).filter(AnalysisResult.action == "keep_recommended").first()
            self.assertIsNotNone(keep_2)
            self.assertEqual(keep_2.emby_item_id, "r2")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
