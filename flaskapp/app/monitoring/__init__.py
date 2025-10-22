# app/monitoring/__init__.py
"""
Error tracking and monitoring integration.

Provides:
- Sentry error tracking
- Performance monitoring (APM)
- Custom error context (user, account, request)
- Release tracking
- Environment tagging
"""

from flask import Flask, g, request
from typing import Optional
import os


def init_sentry(app: Flask):
    """
    Initialize Sentry error tracking and performance monitoring.

    Args:
        app: Flask application instance
    """
    sentry_dsn = app.config.get('SENTRY_DSN') or os.getenv('SENTRY_DSN')

    if not sentry_dsn:
        app.logger.info("Sentry DSN not configured - error tracking disabled")
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        # Configure Sentry
        sentry_sdk.init(
            dsn=sentry_dsn,

            # Integrations
            integrations=[
                FlaskIntegration(
                    transaction_style="url"  # Group by URL pattern, not individual URLs
                ),
                SqlalchemyIntegration(),
                LoggingIntegration(
                    level=app.config.get('SENTRY_LOG_LEVEL', None),  # Capture logs at this level
                    event_level=app.config.get('SENTRY_EVENT_LEVEL', None)  # Send logs as events
                ),
            ],

            # Performance monitoring
            traces_sample_rate=app.config.get('SENTRY_TRACES_SAMPLE_RATE', 0.1),  # 10% of requests
            profiles_sample_rate=app.config.get('SENTRY_PROFILES_SAMPLE_RATE', 0.1),  # 10% profiling

            # Environment and release tracking
            environment=app.config.get('SENTRY_ENVIRONMENT', os.getenv('ENVIRONMENT', 'production')),
            release=app.config.get('SENTRY_RELEASE', os.getenv('GIT_COMMIT', 'unknown')),

            # Additional options
            send_default_pii=False,  # Don't send PII by default (we'll add it manually)
            attach_stacktrace=True,
            max_breadcrumbs=50,

            # Ignore specific errors
            ignore_errors=[
                KeyboardInterrupt,
                SystemExit,
            ],

            # Sample rate for error events (1.0 = 100%)
            sample_rate=app.config.get('SENTRY_SAMPLE_RATE', 1.0),

            # Before send hook for filtering/modifying events
            before_send=before_send_event,
        )

        app.logger.info(
            f"✓ Sentry initialized (environment={app.config.get('SENTRY_ENVIRONMENT', 'production')}, "
            f"traces_sample_rate={app.config.get('SENTRY_TRACES_SAMPLE_RATE', 0.1)})"
        )

        # Register context processors
        register_context_processors(app)

        # Register error handlers
        register_error_handlers(app)

    except ImportError:
        app.logger.warning(
            "Sentry SDK not installed. Install with: pip install sentry-sdk[flask]"
        )
    except Exception as e:
        app.logger.error(f"Failed to initialize Sentry: {e}", exc_info=True)


def before_send_event(event, hint):
    """
    Filter or modify events before sending to Sentry.

    Args:
        event: Sentry event dict
        hint: Additional context

    Returns:
        Modified event dict or None to drop the event
    """
    # Drop events from health check endpoints
    if event.get('request', {}).get('url', '').endswith('/health'):
        return None

    # Drop 404 errors (usually not actionable)
    if event.get('exception', {}).get('values', [{}])[0].get('type') == 'NotFound':
        return None

    # Add custom fingerprinting for better grouping
    if 'exception' in event:
        exc_type = event['exception']['values'][0].get('type', 'Unknown')
        exc_value = event['exception']['values'][0].get('value', '')[:100]
        event['fingerprint'] = [exc_type, exc_value]

    return event


def register_context_processors(app: Flask):
    """Register before_request hooks to add context to Sentry events."""

    @app.before_request
    def add_sentry_context():
        """Add user and request context to Sentry."""
        try:
            import sentry_sdk

            # Add user context
            if hasattr(g, 'user') and g.user:
                sentry_sdk.set_user({
                    "id": str(g.user.id),
                    "email": g.user.email,
                    "username": g.user.name,
                })

                # Add account context
                if hasattr(g.user, 'account_id'):
                    sentry_sdk.set_context("account", {
                        "id": g.user.account_id,
                        "role": g.user.role if hasattr(g.user, 'role') else None,
                    })

            # Add request context (non-PII)
            sentry_sdk.set_context("request_info", {
                "method": request.method,
                "url": request.url,
                "endpoint": request.endpoint,
                "referrer": request.referrer,
            })

            # Add custom tags for filtering
            sentry_sdk.set_tag("request_method", request.method)
            sentry_sdk.set_tag("endpoint", request.endpoint or "unknown")

        except Exception as e:
            app.logger.warning(f"Failed to add Sentry context: {e}")


def register_error_handlers(app: Flask):
    """Register custom error handlers that report to Sentry."""

    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 errors and report to Sentry."""
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(error)
        except:
            pass

        return {
            "error": "Internal server error",
            "message": "An unexpected error occurred. Our team has been notified."
        }, 500

    @app.errorhandler(Exception)
    def unhandled_exception(error):
        """Catch all unhandled exceptions."""
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(error)
        except:
            pass

        # Re-raise to let Flask handle it
        raise error


# Helper functions for manual error reporting

def capture_exception(error: Exception, **extra_context):
    """
    Manually capture an exception to Sentry.

    Args:
        error: Exception to capture
        **extra_context: Additional context to attach
    """
    try:
        import sentry_sdk

        if extra_context:
            with sentry_sdk.push_scope() as scope:
                for key, value in extra_context.items():
                    scope.set_context(key, value)
                sentry_sdk.capture_exception(error)
        else:
            sentry_sdk.capture_exception(error)

    except ImportError:
        pass  # Sentry not installed


def capture_message(message: str, level: str = "info", **extra_context):
    """
    Manually capture a message to Sentry.

    Args:
        message: Message to capture
        level: Severity level (debug, info, warning, error, fatal)
        **extra_context: Additional context to attach
    """
    try:
        import sentry_sdk

        if extra_context:
            with sentry_sdk.push_scope() as scope:
                for key, value in extra_context.items():
                    scope.set_context(key, value)
                sentry_sdk.capture_message(message, level=level)
        else:
            sentry_sdk.capture_message(message, level=level)

    except ImportError:
        pass


def add_breadcrumb(message: str, category: str = "custom", level: str = "info", data: Optional[dict] = None):
    """
    Add a breadcrumb to Sentry (for tracking user actions leading to errors).

    Args:
        message: Breadcrumb message
        category: Category (auth, navigation, http, etc.)
        level: Severity level
        data: Additional data dict
    """
    try:
        import sentry_sdk

        sentry_sdk.add_breadcrumb(
            message=message,
            category=category,
            level=level,
            data=data or {}
        )
    except ImportError:
        pass


def set_user_context(user_id: str, email: Optional[str] = None, **extra):
    """
    Set user context for error tracking.

    Args:
        user_id: User ID
        email: User email
        **extra: Additional user attributes
    """
    try:
        import sentry_sdk

        user_data = {"id": user_id}
        if email:
            user_data["email"] = email
        user_data.update(extra)

        sentry_sdk.set_user(user_data)
    except ImportError:
        pass


def set_transaction_name(name: str):
    """
    Set custom transaction name for performance monitoring.

    Args:
        name: Transaction name (e.g., "checkout.process_payment")
    """
    try:
        import sentry_sdk

        with sentry_sdk.configure_scope() as scope:
            scope.transaction = name
    except ImportError:
        pass


def start_transaction(name: str, op: str = "task"):
    """
    Start a custom transaction for performance monitoring.

    Args:
        name: Transaction name
        op: Operation type (task, http, db, etc.)

    Returns:
        Transaction object (use with context manager)
    """
    try:
        import sentry_sdk
        return sentry_sdk.start_transaction(name=name, op=op)
    except ImportError:
        # Return dummy context manager
        class DummyTransaction:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return DummyTransaction()


def start_span(operation: str, description: Optional[str] = None):
    """
    Start a span for detailed performance monitoring.

    Args:
        operation: Operation name (e.g., "db.query", "http.request")
        description: Detailed description

    Returns:
        Span object (use with context manager)
    """
    try:
        import sentry_sdk
        return sentry_sdk.start_span(op=operation, description=description)
    except ImportError:
        class DummySpan:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return DummySpan()


# Decorator for monitoring functions

def monitor_performance(operation: str):
    """
    Decorator to monitor function performance.

    Usage:
        @monitor_performance("user.registration")
        def register_user(email, password):
            ...
    """
    def decorator(func):
        from functools import wraps

        @wraps(func)
        def wrapper(*args, **kwargs):
            with start_span(operation, description=func.__name__):
                return func(*args, **kwargs)
        return wrapper
    return decorator
