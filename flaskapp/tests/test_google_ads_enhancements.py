"""
Tests for Google Ads tool enhancements (Items 1–10).

No MySQL connection required — all DB calls are mocked.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.services.google_ads_type_benchmarks import (
    CAMPAIGN_TYPE_BENCHMARKS,
    SEARCH, PERFORMANCE_MAX, SHOPPING, DEMAND_GEN, VIDEO, DISPLAY, UNKNOWN,
    get_benchmark, is_upper_funnel, kw_rules_apply, get_halo_pct,
    effective_roas, period_budget_remaining,
)


# ── Benchmarks ────────────────────────────────────────────────────────────────

class TestBenchmarks:
    def test_all_types_present(self):
        for t in [SEARCH, PERFORMANCE_MAX, SHOPPING, DEMAND_GEN, VIDEO, DISPLAY, UNKNOWN]:
            assert t in CAMPAIGN_TYPE_BENCHMARKS

    def test_get_benchmark_known_type(self):
        bm = get_benchmark(SHOPPING)
        assert bm["iroas"] == 2.1
        assert bm["target_cvr"] == pytest.approx(0.0286)

    def test_get_benchmark_case_insensitive(self):
        bm = get_benchmark("shopping")
        assert bm["iroas"] == 2.1

    def test_get_benchmark_unknown_falls_back(self):
        bm = get_benchmark("SOME_NEW_TYPE_2027")
        assert bm is CAMPAIGN_TYPE_BENCHMARKS[UNKNOWN]

    def test_get_benchmark_none_falls_back(self):
        bm = get_benchmark(None)
        assert bm is CAMPAIGN_TYPE_BENCHMARKS[UNKNOWN]


# ── is_upper_funnel ───────────────────────────────────────────────────────────

class TestIsUpperFunnel:
    def test_search_is_not_upper_funnel(self):
        assert is_upper_funnel(SEARCH) is False

    def test_pmax_is_not_upper_funnel(self):
        assert is_upper_funnel(PERFORMANCE_MAX) is False

    def test_shopping_is_not_upper_funnel(self):
        assert is_upper_funnel(SHOPPING) is False

    def test_demand_gen_is_upper_funnel(self):
        assert is_upper_funnel(DEMAND_GEN) is True

    def test_video_is_upper_funnel(self):
        assert is_upper_funnel(VIDEO) is True

    def test_display_is_upper_funnel(self):
        assert is_upper_funnel(DISPLAY) is True

    def test_none_is_not_upper_funnel(self):
        assert is_upper_funnel(None) is False


# ── kw_rules_apply ────────────────────────────────────────────────────────────

class TestKwRulesApply:
    def test_search_kw_rules_apply(self):
        assert kw_rules_apply(SEARCH) is True

    def test_pmax_kw_rules_do_not_apply(self):
        assert kw_rules_apply(PERFORMANCE_MAX) is False

    def test_shopping_kw_rules_do_not_apply(self):
        assert kw_rules_apply(SHOPPING) is False

    def test_demand_gen_kw_rules_do_not_apply(self):
        assert kw_rules_apply(DEMAND_GEN) is False

    def test_video_kw_rules_do_not_apply(self):
        assert kw_rules_apply(VIDEO) is False

    def test_none_defaults_to_true(self):
        assert kw_rules_apply(None) is True


# ── get_halo_pct ──────────────────────────────────────────────────────────────

class TestGetHaloPct:
    def test_search_halo(self):
        assert get_halo_pct(SEARCH) == pytest.approx(50.9)

    def test_pmax_halo(self):
        assert get_halo_pct(PERFORMANCE_MAX) == pytest.approx(27.9)

    def test_shopping_halo_is_none(self):
        assert get_halo_pct(SHOPPING) is None

    def test_demand_gen_halo(self):
        assert get_halo_pct(DEMAND_GEN) == pytest.approx(29.9)

    def test_video_halo(self):
        assert get_halo_pct(VIDEO) == pytest.approx(15.4)

    def test_unknown_halo_is_none(self):
        assert get_halo_pct(None) is None


# ── effective_roas ────────────────────────────────────────────────────────────

class TestEffectiveRoas:
    def test_no_adjustment(self):
        assert effective_roas(4.0, SEARCH, 1.0) == 4.0

    def test_attribution_adjustment(self):
        # Video: last-click underestimates by ~50%, so ratio=1.5
        assert effective_roas(2.0, VIDEO, 1.5) == 3.0

    def test_default_ratio_is_one(self):
        assert effective_roas(5.0, DEMAND_GEN) == 5.0


# ── period_budget_remaining ───────────────────────────────────────────────────

class TestPeriodBudgetRemaining:
    def test_basic_remaining(self):
        remaining = period_budget_remaining(
            period_budget_cents=100_000,
            period_budget_start=date(2026, 1, 1),
            period_budget_end=date(2026, 1, 31),
            spend_to_date_cents=30_000,
        )
        assert remaining == 70_000

    def test_fully_spent(self):
        remaining = period_budget_remaining(
            period_budget_cents=50_000,
            period_budget_start=date(2026, 1, 1),
            period_budget_end=date(2026, 1, 31),
            spend_to_date_cents=60_000,
        )
        assert remaining == 0

    def test_missing_period_returns_none(self):
        assert period_budget_remaining(None, None, None) is None

    def test_missing_start_returns_none(self):
        assert period_budget_remaining(100_000, None, date(2026, 1, 31)) is None


# ── Digest enhancements ───────────────────────────────────────────────────────

class TestDigestRenderEnhancements:
    """render_digest_text picks up new fields (by_type, new_customer_pct, halo)."""

    def _base_digest(self):
        return {
            "account_id": 1,
            "has_data": True,
            "this_week": {"spend": 1000.0, "clicks": 100, "leads": 10.0, "cost_per_lead": 100.0},
            "prior_week": None,
            "deltas": {},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "by_type": [],
            "new_customer_pct": None,
            "halo_estimate_pct": None,
        }

    def test_render_no_crash_with_no_new_fields(self):
        from app.services.google_ads_digest import render_digest_text
        d = self._base_digest()
        result = render_digest_text(d)
        assert "headline" in result
        assert isinstance(result["summary_lines"], list)

    def test_new_customer_pct_high_shown(self):
        from app.services.google_ads_digest import render_digest_text
        d = self._base_digest()
        d["new_customer_pct"] = 65.0
        result = render_digest_text(d)
        lines = " ".join(result["summary_lines"])
        assert "65%" in lines
        assert "new customers" in lines.lower()

    def test_new_customer_pct_low_shown(self):
        from app.services.google_ads_digest import render_digest_text
        d = self._base_digest()
        d["new_customer_pct"] = 15.0
        result = render_digest_text(d)
        lines = " ".join(result["summary_lines"])
        assert "15%" in lines
        assert "new customers" in lines.lower()

    def test_halo_note_shown_when_present(self):
        from app.services.google_ads_digest import render_digest_text
        d = self._base_digest()
        d["halo_estimate_pct"] = 50.9
        result = render_digest_text(d)
        lines = " ".join(result["summary_lines"])
        assert "51%" in lines or "50%" in lines
        assert "off-platform" in lines.lower() or "true roas" in lines.lower()

    def test_by_type_summary_shown_when_multiple(self):
        from app.services.google_ads_digest import render_digest_text
        d = self._base_digest()
        d["by_type"] = [
            {"campaign_type": "SEARCH", "campaign_count": 2, "spend": 700.0, "clicks": 70, "leads": 7.0, "cost_per_lead": 100.0, "halo_pct": 50.9},
            {"campaign_type": "SHOPPING", "campaign_count": 1, "spend": 300.0, "clicks": 30, "leads": 3.0, "cost_per_lead": 100.0, "halo_pct": None},
        ]
        result = render_digest_text(d)
        lines = " ".join(result["summary_lines"])
        assert "SEARCH" in lines
        assert "SHOPPING" in lines

    def test_by_type_not_shown_when_single(self):
        from app.services.google_ads_digest import render_digest_text
        d = self._base_digest()
        d["by_type"] = [
            {"campaign_type": "SEARCH", "campaign_count": 3, "spend": 1000.0, "clicks": 100, "leads": 10.0, "cost_per_lead": 100.0, "halo_pct": 50.9},
        ]
        result = render_digest_text(d)
        lines = " ".join(result["summary_lines"])
        # Single type shouldn't show the breakdown
        assert "By campaign type" not in lines


# ── Campaign mix snapshot ─────────────────────────────────────────────────────

class TestCampaignMixSnapshot:
    """
    take_mix_snapshot imports `db` from `app` inside the function body
    (`from app import db`), so we patch 'app.db' — not a module-level
    attribute of google_ads_campaign_mix — to intercept that lookup.
    """

    def _make_db(self, type_rows=None):
        mock_db = MagicMock()
        session = MagicMock()
        mock_db.session = session
        mock_db.engine = MagicMock()

        result = MagicMock()
        result.mappings.return_value.all.return_value = type_rows or []
        session.execute.return_value = result
        session.commit = MagicMock()
        session.rollback = MagicMock()
        return mock_db

    def test_no_rows_returns_error(self):
        from app.services.google_ads_campaign_mix import take_mix_snapshot
        mock_db = self._make_db(type_rows=[])
        with patch("app.db", mock_db):
            result = take_mix_snapshot(1, week_start=date(2026, 1, 6))
        assert result["rows"] == []
        assert result["errors"]

    def test_snapshot_computes_spend_pct(self):
        from app.services.google_ads_campaign_mix import take_mix_snapshot
        type_rows = [
            {"campaign_type": "SEARCH", "campaign_count": 2, "spend": 700.0, "conversions": 10.0},
            {"campaign_type": "SHOPPING", "campaign_count": 1, "spend": 300.0, "conversions": 5.0},
        ]
        mock_db = self._make_db(type_rows=type_rows)
        with patch("app.db", mock_db):
            result = take_mix_snapshot(1, week_start=date(2026, 1, 6))
        assert len(result["rows"]) == 2
        search_row = next(r for r in result["rows"] if r["campaign_type"] == "SEARCH")
        shop_row = next(r for r in result["rows"] if r["campaign_type"] == "SHOPPING")
        assert search_row["spend_pct"] == pytest.approx(70.0)
        assert shop_row["spend_pct"] == pytest.approx(30.0)

    def test_missing_high_roi_types_flagged(self):
        from app.services.google_ads_campaign_mix import take_mix_snapshot
        type_rows = [
            {"campaign_type": "SEARCH", "campaign_count": 3, "spend": 1000.0, "conversions": 15.0},
        ]
        mock_db = self._make_db(type_rows=type_rows)
        with patch("app.db", mock_db):
            result = take_mix_snapshot(1, week_start=date(2026, 1, 6))
        assert "SHOPPING" in result["missing_high_roi_types"]
        assert "PERFORMANCE_MAX" in result["missing_high_roi_types"]

    def test_no_missing_types_when_all_present(self):
        from app.services.google_ads_campaign_mix import take_mix_snapshot
        type_rows = [
            {"campaign_type": "SEARCH", "campaign_count": 2, "spend": 400.0, "conversions": 5.0},
            {"campaign_type": "SHOPPING", "campaign_count": 1, "spend": 300.0, "conversions": 4.0},
            {"campaign_type": "PERFORMANCE_MAX", "campaign_count": 1, "spend": 300.0, "conversions": 6.0},
        ]
        mock_db = self._make_db(type_rows=type_rows)
        with patch("app.db", mock_db):
            result = take_mix_snapshot(1, week_start=date(2026, 1, 6))
        assert result["missing_high_roi_types"] == []


# ── Credit gap halo ───────────────────────────────────────────────────────────

class TestCreditGapHalo:
    """build_credit_gap now returns halo_estimate_pct for the dominant campaign type."""

    def _make_db(self, campaigns=None, job_rows=None):
        db = MagicMock()
        session = MagicMock()
        db.session = session
        session.commit = MagicMock()
        session.rollback = MagicMock()

        call_count = [0]

        def _mock_mappings(rows):
            r = MagicMock()
            r.mappings.return_value.all.return_value = rows
            return r

        def _mock_fetchall(rows):
            r = MagicMock()
            r.fetchall.return_value = [(x,) for x in rows]
            return r

        def side_effect(sql_obj, params=None):
            sql = str(sql_obj)
            call_count[0] += 1
            if "gads_stats_daily" in sql:
                return _mock_mappings(campaigns or [])
            if "servicetitan_jobs" in sql and "completed_date >= :s" in sql:
                return _mock_mappings(job_rows or [])
            if "servicetitan_jobs" in sql and "completed_date < :s" in sql:
                return _mock_fetchall([])
            if "servicetitan_customers" in sql:
                return _mock_fetchall([])
            return _mock_mappings([])

        session.execute.side_effect = side_effect
        return db

    def test_halo_pct_returned_for_search_campaigns(self):
        from app.services.credit_gap_service import build_credit_gap
        campaigns = [
            {"campaign_id": 1, "campaign_name": "HVAC", "campaign_type": "SEARCH",
             "spend": 1000.0, "conversions": 5},
        ]
        db = self._make_db(campaigns=campaigns)
        result = build_credit_gap(db, 1, date(2026, 1, 1), date(2026, 1, 31))
        assert result["halo_estimate_pct"] == pytest.approx(50.9)

    def test_halo_pct_none_for_shopping_campaigns(self):
        from app.services.credit_gap_service import build_credit_gap
        campaigns = [
            {"campaign_id": 1, "campaign_name": "Shop", "campaign_type": "SHOPPING",
             "spend": 500.0, "conversions": 10},
        ]
        db = self._make_db(campaigns=campaigns)
        result = build_credit_gap(db, 1, date(2026, 1, 1), date(2026, 1, 31))
        assert result["halo_estimate_pct"] is None  # Shopping halo not measured in report

    def test_halo_pct_none_when_no_campaigns(self):
        from app.services.credit_gap_service import build_credit_gap
        db = self._make_db(campaigns=[])
        result = build_credit_gap(db, 1, date(2026, 1, 1), date(2026, 1, 31))
        assert result["halo_estimate_pct"] is None


# ── Sync campaign_type propagation ───────────────────────────────────────────

class TestSyncCampaignType:
    """_get_or_create_campaign writes campaign_type on create and update."""

    def _make_session(self, existing_camp=None):
        session = MagicMock()
        from app.models_ads import AdsCampaign
        # query().filter_by().first()
        q = MagicMock()
        q.first.return_value = existing_camp
        session.query = MagicMock(return_value=q)
        return session

    def test_creates_campaign_with_type(self):
        from app.services.google_ads_sync import _get_or_create_campaign
        session = MagicMock()
        # AdsCampaign is imported inside _get_or_create_campaign via
        # `from app.models_ads import AdsCampaign`, so patch there.
        with patch("app.models_ads.AdsCampaign") as MockCamp:
            mock_instance = MagicMock()
            mock_instance.id = 42
            MockCamp.query.filter_by.return_value.first.return_value = None
            MockCamp.query.filter.return_value.first.return_value = None
            MockCamp.return_value = mock_instance

            _get_or_create_campaign(session, 1, 999, "Test", "ENABLED", campaign_type="SHOPPING")

            call_kwargs = MockCamp.call_args[1]
            assert call_kwargs.get("campaign_type") == "SHOPPING"

    def test_updates_campaign_type_on_existing(self):
        from app.services.google_ads_sync import _get_or_create_campaign
        session = MagicMock()
        with patch("app.models_ads.AdsCampaign") as MockCamp:
            existing = MagicMock()
            existing.id = 10
            MockCamp.query.filter_by.return_value.first.return_value = existing

            _get_or_create_campaign(session, 1, 999, "Test", "ENABLED", campaign_type="PERFORMANCE_MAX")
            assert existing.campaign_type == "PERFORMANCE_MAX"

    def test_no_type_does_not_overwrite(self):
        from app.services.google_ads_sync import _get_or_create_campaign
        session = MagicMock()
        with patch("app.models_ads.AdsCampaign") as MockCamp:
            existing = MagicMock()
            existing.id = 10
            existing.campaign_type = "SEARCH"
            MockCamp.query.filter_by.return_value.first.return_value = existing

            _get_or_create_campaign(session, 1, 999, "Test", "ENABLED", campaign_type=None)
            # campaign_type should NOT be set to None — existing value preserved
            assert existing.campaign_type == "SEARCH"
