# app/performance_utils.py
"""
Performance optimization utilities for FieldSprout.

Provides caching, query optimization, and lazy loading helpers.
"""
from __future__ import annotations

import functools
import hashlib
import pickle
from typing import Any, Callable, Optional
from flask import current_app, g
from datetime import timedelta


def cache_result(ttl: int = 300, key_prefix: str = ""):
    """
    Decorator to cache function results in Redis or in-memory.

    Args:
        ttl: Time to live in seconds (default 5 minutes)
        key_prefix: Prefix for cache key

    Usage:
        @cache_result(ttl=600, key_prefix="dashboard")
        def get_dashboard_data(account_id):
            # expensive query
            return data
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key from function name and arguments
            key_parts = [key_prefix, func.__name__]
            key_parts.extend(str(arg) for arg in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = hashlib.md5(":".join(key_parts).encode()).hexdigest()
            cache_key = f"cache:{key_prefix}:{func.__name__}:{cache_key}"

            # Try to get from Redis first
            redis_client = getattr(current_app, "redis", None)
            if redis_client:
                try:
                    cached = redis_client.get(cache_key)
                    if cached:
                        return pickle.loads(cached)
                except Exception as e:
                    current_app.logger.warning(f"Redis cache read failed: {e}")

            # Execute function
            result = func(*args, **kwargs)

            # Store in Redis
            if redis_client:
                try:
                    redis_client.setex(
                        cache_key,
                        ttl,
                        pickle.dumps(result)
                    )
                except Exception as e:
                    current_app.logger.warning(f"Redis cache write failed: {e}")

            return result

        return wrapper
    return decorator


def request_cache(func: Callable) -> Callable:
    """
    Cache function result for the duration of the current request.
    Useful for avoiding duplicate queries within a single page load.

    Usage:
        @request_cache
        def get_account_settings(account_id):
            return db.query(...)
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Create cache key
        key = f"{func.__name__}:{args}:{tuple(sorted(kwargs.items()))}"

        # Initialize request cache if needed
        if not hasattr(g, "_request_cache"):
            g._request_cache = {}

        # Return cached result if available
        if key in g._request_cache:
            return g._request_cache[key]

        # Execute and cache
        result = func(*args, **kwargs)
        g._request_cache[key] = result
        return result

    return wrapper


def invalidate_cache(key_pattern: str):
    """
    Invalidate cache entries matching a pattern.

    Args:
        key_pattern: Pattern to match (e.g., "dashboard:*", "account:123:*")
    """
    redis_client = getattr(current_app, "redis", None)
    if redis_client:
        try:
            keys = redis_client.keys(f"cache:{key_pattern}")
            if keys:
                redis_client.delete(*keys)
        except Exception as e:
            current_app.logger.warning(f"Cache invalidation failed: {e}")


def batch_query_loader(model_class, ids: list, id_field: str = "id") -> dict:
    """
    Batch load multiple records to avoid N+1 queries.

    Args:
        model_class: SQLAlchemy model class
        ids: List of IDs to load
        id_field: Name of the ID field (default "id")

    Returns:
        Dict mapping ID to model instance

    Usage:
        campaign_ids = [c.id for c in campaigns]
        campaigns_map = batch_query_loader(Campaign, campaign_ids)
        for campaign in campaigns:
            details = campaigns_map.get(campaign.id)
    """
    if not ids:
        return {}

    id_attr = getattr(model_class, id_field)
    records = model_class.query.filter(id_attr.in_(ids)).all()
    return {getattr(r, id_field): r for r in records}


def lazy_load_property(loader_func: Callable, cache_attr: str):
    """
    Decorator for lazy-loading expensive properties.

    Args:
        loader_func: Function to load the data
        cache_attr: Attribute name to cache the result

    Usage:
        class Account:
            @lazy_load_property(loader_func=lambda self: expensive_query(), cache_attr="_stats")
            def stats(self):
                pass
    """
    def decorator(func: Callable) -> property:
        @functools.wraps(func)
        def wrapper(self):
            if not hasattr(self, cache_attr):
                setattr(self, cache_attr, loader_func(self))
            return getattr(self, cache_attr)
        return property(wrapper)
    return decorator


class QueryTimer:
    """
    Context manager to log slow queries.

    Usage:
        with QueryTimer("dashboard_queries", threshold=1.0):
            data = expensive_query()
    """

    def __init__(self, name: str, threshold: float = 0.5):
        self.name = name
        self.threshold = threshold
        self.start_time = None

    def __enter__(self):
        import time
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        import time
        elapsed = time.time() - self.start_time
        if elapsed > self.threshold:
            current_app.logger.warning(
                f"Slow query detected: {self.name} took {elapsed:.2f}s"
            )


def optimize_pagination(query, page: int = 1, per_page: int = 20, max_per_page: int = 100):
    """
    Optimized pagination helper that prevents excessive per_page values.

    Args:
        query: SQLAlchemy query object
        page: Page number (1-indexed)
        per_page: Items per page
        max_per_page: Maximum items per page (default 100)

    Returns:
        Paginated query object with items, has_next, has_prev attributes
    """
    # Cap per_page
    per_page = min(per_page, max_per_page)
    page = max(1, page)

    # Use limit/offset for better performance than paginate()
    items = query.limit(per_page + 1).offset((page - 1) * per_page).all()
    has_next = len(items) > per_page
    if has_next:
        items = items[:-1]

    class PaginationResult:
        def __init__(self, items, page, per_page, has_next):
            self.items = items
            self.page = page
            self.per_page = per_page
            self.has_next = has_next
            self.has_prev = page > 1

    return PaginationResult(items, page, per_page, has_next)


def warm_cache(cache_key: str, loader_func: Callable, ttl: int = 300):
    """
    Warm up cache with data from loader function.
    Useful for preloading frequently accessed data.

    Args:
        cache_key: Key to store in cache
        loader_func: Function to load data
        ttl: Time to live in seconds
    """
    redis_client = getattr(current_app, "redis", None)
    if redis_client:
        try:
            data = loader_func()
            redis_client.setex(
                f"cache:{cache_key}",
                ttl,
                pickle.dumps(data)
            )
        except Exception as e:
            current_app.logger.error(f"Cache warming failed for {cache_key}: {e}")
