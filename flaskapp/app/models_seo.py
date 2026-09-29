# app/models_seo.py
from datetime import datetime
from app import db


class SEOScanResult(db.Model):
    """
    Persists every SEO/AEO/GEO tool scan result for trend tracking, agent memory,
    and ML training. One row per scan run per tool per URL/site.

    scan_type values:
        aeo_audit          — AI Overview optimizer
        cannibalization    — keyword cannibalization detector
        llm_citations      — LLM/GEO citation tracker
        index_coverage     — index coverage monitor
        orphan_pages       — orphan page detector
        seo_foundation     — WordPress SEO foundation checker
        redirects          — redirect chain scanner
        broken_links       — broken link scanner
        content_quality    — thin/duplicate content detector
        image_seo          — image optimisation audit
        eeat               — E-E-A-T checker
        local_seo          — local SEO audit
        pagespeed          — PageSpeed / Core Web Vitals
        freshness          — content freshness audit
        internal_links     — internal linking opportunities
        content_brief      — content brief generator
        snippets           — featured snippet optimizer
        page_performance   — per-page GSC performance
    """
    __tablename__ = "seo_scan_results"
    __table_args__ = (
        db.Index("ix_ssr_account_type_created", "account_id", "scan_type", "created_at"),
        db.Index("ix_ssr_url_type", "url", "scan_type"),
        db.Index("ix_ssr_site_type", "site_id", "scan_type"),
        {"extend_existing": True},
    )

    id          = db.Column(db.Integer, primary_key=True)
    account_id  = db.Column(db.Integer, nullable=False)
    site_id     = db.Column(db.Integer, nullable=True)   # wp_sites.id — null for URL-only scans
    scan_type   = db.Column(db.String(64),  nullable=False)

    # Optional URL — set for page-level scans, null for site-wide scans
    url         = db.Column(db.String(2048), nullable=True)

    # Normalised scalars — populated where applicable (null otherwise)
    score       = db.Column(db.Integer, nullable=True)   # 0-100
    pass_count  = db.Column(db.Integer, nullable=True)
    warn_count  = db.Column(db.Integer, nullable=True)
    fail_count  = db.Column(db.Integer, nullable=True)
    issue_count = db.Column(db.Integer, nullable=True)   # generic count (orphans, chains, etc.)
    item_count  = db.Column(db.Integer, nullable=True)   # total items examined

    # Full structured result — everything the tool returned
    data        = db.Column(db.JSON, nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @classmethod
    def save_result(cls, account_id, scan_type, data, site_id=None, url=None,
                    score=None, pass_count=None, warn_count=None, fail_count=None,
                    issue_count=None, item_count=None):
        """Convenience factory — creates and flushes a result row."""
        from app import db as _db
        row = cls(
            account_id=account_id,
            site_id=site_id,
            scan_type=scan_type,
            url=url,
            score=score,
            pass_count=pass_count,
            warn_count=warn_count,
            fail_count=fail_count,
            issue_count=issue_count,
            item_count=item_count,
            data=data,
        )
        _db.session.add(row)
        _db.session.commit()
        return row

    @classmethod
    def latest(cls, account_id, scan_type, url=None, site_id=None):
        """Return the most recent scan of a given type for this account/URL."""
        q = cls.query.filter_by(account_id=account_id, scan_type=scan_type)
        if url:
            q = q.filter_by(url=url)
        if site_id:
            q = q.filter_by(site_id=site_id)
        return q.order_by(cls.created_at.desc()).first()

    @classmethod
    def history(cls, account_id, scan_type, url=None, site_id=None, limit=30):
        """Return recent scans ordered newest-first — for trend charts."""
        q = cls.query.filter_by(account_id=account_id, scan_type=scan_type)
        if url:
            q = q.filter_by(url=url)
        if site_id:
            q = q.filter_by(site_id=site_id)
        return q.order_by(cls.created_at.desc()).limit(limit).all()


class SEOKeywordPosition(db.Model):
    """
    Persists keyword position snapshots from GSC for trend analysis and ML.
    One row per keyword per page per GSC window end-date per account.
    Lets agents track rank movement over time without re-querying GSC.
    """
    __tablename__ = "seo_keyword_positions"
    __table_args__ = (
        db.UniqueConstraint("account_id", "site_url", "keyword", "page", "date_end",
                            name="uq_seo_kw_pos"),
        db.Index("ix_skp_account_kw", "account_id", "keyword"),
        db.Index("ix_skp_account_date", "account_id", "date_end"),
        {"extend_existing": True},
    )

    id          = db.Column(db.Integer, primary_key=True)
    account_id  = db.Column(db.Integer, nullable=False)
    site_url    = db.Column(db.String(512), nullable=False)
    keyword     = db.Column(db.String(512), nullable=False)
    page        = db.Column(db.String(2048), nullable=True)
    position    = db.Column(db.Numeric(7, 2), nullable=True)
    impressions = db.Column(db.Integer, nullable=True)
    clicks      = db.Column(db.Integer, nullable=True)
    ctr         = db.Column(db.Numeric(6, 4), nullable=True)
    date_start  = db.Column(db.Date, nullable=True)
    date_end    = db.Column(db.Date, nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @classmethod
    def upsert(cls, account_id, site_url, keyword, page, position,
               impressions, clicks, ctr, date_start, date_end):
        from app import db as _db
        existing = cls.query.filter_by(
            account_id=account_id, site_url=site_url,
            keyword=keyword, page=page or "", date_end=date_end
        ).first()
        if existing:
            existing.position = position
            existing.impressions = impressions
            existing.clicks = clicks
            existing.ctr = ctr
        else:
            existing = cls(
                account_id=account_id, site_url=site_url,
                keyword=keyword, page=page or "", position=position,
                impressions=impressions, clicks=clicks, ctr=ctr,
                date_start=date_start, date_end=date_end,
            )
            _db.session.add(existing)
        _db.session.commit()
        return existing


class SEOHealthSnapshot(db.Model):
    """One row per monitoring run per site. Stores key health metrics for trending."""
    __tablename__ = "seo_health_snapshots"
    __table_args__ = {"extend_existing": True}

    id              = db.Column(db.Integer, primary_key=True)
    site_id         = db.Column(db.Integer, nullable=True)   # wp_sites.id (nullable — URL-only sites)
    account_id      = db.Column(db.Integer, nullable=True)
    site_url        = db.Column(db.String(512), nullable=False)

    # Technical health
    health_score        = db.Column(db.Integer, default=0)
    sitemap_ok          = db.Column(db.Boolean, default=True)
    robots_ok           = db.Column(db.Boolean, default=True)
    homepage_status     = db.Column(db.Integer, default=200)
    broken_links_count  = db.Column(db.Integer, default=0)

    # GSC snapshot (null if GSC not connected)
    gsc_clicks          = db.Column(db.Integer, nullable=True)
    gsc_impressions     = db.Column(db.Integer, nullable=True)
    gsc_avg_position    = db.Column(db.Float, nullable=True)

    # Full raw data blob for diffing
    data        = db.Column(db.JSON, nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class SEOAlert(db.Model):
    """An alert generated by the monitoring engine for a site/account."""
    __tablename__ = "seo_alerts"
    __table_args__ = {"extend_existing": True}

    id          = db.Column(db.Integer, primary_key=True)
    site_id     = db.Column(db.Integer, nullable=True)
    account_id  = db.Column(db.Integer, nullable=True)
    site_url    = db.Column(db.String(512), nullable=True)

    # alert_type: traffic_drop | ranking_drop | sitemap_error | robots_blocked |
    #             homepage_error | health_score_drop | broken_links | new_404s
    alert_type  = db.Column(db.String(64), nullable=False)
    severity    = db.Column(db.String(16), nullable=False)   # critical | warning | info
    message     = db.Column(db.Text, nullable=False)
    detail      = db.Column(db.JSON, nullable=True)          # extra structured context

    is_read     = db.Column(db.Boolean, default=False, nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
