"""Time-series aggregation service for dashboard charts and the timeseries API."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from llm_observability.core.config import settings


def _is_postgres() -> bool:
    return settings.database_url.startswith("postgresql")


def _timeseries_sql(bucket_minutes: int) -> str:
    """Return a DB-appropriate SELECT for time-bucketed aggregation.

    SQLite uses ``strftime`` + ``printf`` integer-division bucketing.
    PostgreSQL uses ``date_trunc`` + ``date_bin`` (PG 14+) or the equivalent
    ``floor(extract(epoch…) / interval)`` approach for older versions.
    We use the ``date_bin`` path (available in PostgreSQL >= 14, which covers
    all Supabase-hosted projects) and fall back to the ``floor/epoch`` trick.
    """
    if _is_postgres():
        interval = f"{bucket_minutes} minutes"
        return f"""
            SELECT
                date_bin(
                    '{interval}'::interval,
                    timestamp AT TIME ZONE 'UTC',
                    TIMESTAMP '2000-01-01 00:00:00'
                ) AS bucket,
                COUNT(*)                                               AS request_count,
                AVG(CASE WHEN is_error = false THEN latency_ms END)   AS avg_latency_ms,
                SUM(COALESCE(estimated_cost, 0))                       AS total_cost,
                SUM(COALESCE(total_tokens, 0))                         AS total_tokens,
                SUM(CASE WHEN is_error = true THEN 1 ELSE 0 END)      AS error_count
            FROM llm_requests
            WHERE timestamp >= :since
            GROUP BY bucket
            ORDER BY bucket
        """
    else:
        # SQLite-compatible bucketing.
        # IMPORTANT: avoid any ':digit' pattern in string literals — SQLAlchemy's
        # text() parser treats ':word' sequences as named bind parameters.
        # Use char(58) (ASCII colon) instead of literal ':' before digits.
        return f"""
            SELECT
                strftime('%Y-%m-%dT%H', timestamp)
                || char(58)
                || printf('%02d', (CAST(strftime('%M', timestamp) AS INTEGER)
                                  / {bucket_minutes}) * {bucket_minutes})
                || char(58) || '00Z' AS bucket,
                COUNT(*)                                               AS request_count,
                AVG(CASE WHEN is_error = 0 THEN latency_ms END)       AS avg_latency_ms,
                SUM(COALESCE(estimated_cost, 0))                       AS total_cost,
                SUM(COALESCE(total_tokens, 0))                         AS total_tokens,
                SUM(CASE WHEN is_error = 1 THEN 1 ELSE 0 END)         AS error_count
            FROM llm_requests
            WHERE timestamp >= :since
            GROUP BY bucket
            ORDER BY bucket
        """


class MetricsService:
    """Provides pre-aggregated, time-bucketed metrics for charting."""

    @staticmethod
    async def get_timeseries(
        db: AsyncSession,
        *,
        hours: int = 24,
        bucket_minutes: int = 5,
    ) -> List[Dict[str, Any]]:
        """Return per-bucket aggregates suitable for time-series charts.

        Works with both SQLite (default, local) and PostgreSQL / Supabase.
        Each bucket contains:
          - timestamp        : ISO-8601 bucket start
          - request_count    : number of requests in the bucket
          - avg_latency_ms   : mean latency for successful requests
          - total_cost       : sum of estimated_cost
          - total_tokens     : sum of total_tokens
          - error_count      : number of error requests
        """
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        sql = text(_timeseries_sql(bucket_minutes))
        result = await db.execute(sql, {"since": since.isoformat()})
        rows = result.fetchall()

        return [
            {
                "timestamp": str(row[0]),
                "request_count": int(row[1]),
                "avg_latency_ms": round(float(row[2] or 0), 2),
                "total_cost": round(float(row[3] or 0), 8),
                "total_tokens": int(row[4] or 0),
                "error_count": int(row[5] or 0),
            }
            for row in rows
        ]

    @staticmethod
    async def get_model_breakdown(
        db: AsyncSession,
        *,
        hours: int = 24,
    ) -> List[Dict[str, Any]]:
        """Return per-model aggregates for the given time window."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

        sql = text(
            """
            SELECT
                model_name,
                COUNT(*)                                       AS request_count,
                AVG(CASE WHEN is_error = 0 THEN latency_ms END) AS avg_latency_ms,
                SUM(COALESCE(estimated_cost, 0))               AS total_cost,
                SUM(COALESCE(total_tokens, 0))                 AS total_tokens,
                SUM(CASE WHEN is_error = 1 THEN 1 ELSE 0 END) AS error_count
            FROM llm_requests
            WHERE timestamp >= :since
            GROUP BY model_name
            ORDER BY request_count DESC
            """
        )
        result = await db.execute(sql, {"since": since.isoformat()})
        rows = result.fetchall()

        return [
            {
                "model_name": row[0],
                "request_count": int(row[1]),
                "avg_latency_ms": round(float(row[2] or 0), 2),
                "total_cost": round(float(row[3] or 0), 6),
                "total_tokens": int(row[4] or 0),
                "error_count": int(row[5] or 0),
            }
            for row in rows
        ]
