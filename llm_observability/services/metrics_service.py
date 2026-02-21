"""Time-series aggregation service for dashboard charts and the timeseries API."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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

        Uses SQLite's ``strftime`` to bucket rows into fixed-width windows.
        Each bucket contains:
          - timestamp        : ISO-8601 bucket start
          - request_count    : number of requests in the bucket
          - avg_latency_ms   : mean latency for successful requests
          - total_cost       : sum of estimated_cost
          - total_tokens     : sum of total_tokens
          - error_count      : number of error requests

        Args:
            db:             Async SQLAlchemy session.
            hours:          How many hours back to look.
            bucket_minutes: Width of each time bucket in minutes.
        """
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

        # SQLite-compatible time bucketing:
        # strftime truncates to the minute, then we zero out the sub-bucket
        # remainder by integer division.
        sql = text(
            f"""
            SELECT
                strftime('%Y-%m-%dT%H:', timestamp)
                || printf('%02d', (CAST(strftime('%M', timestamp) AS INTEGER)
                                  / {bucket_minutes}) * {bucket_minutes})
                || ':00Z' AS bucket,
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
        )

        result = await db.execute(sql, {"since": since.isoformat()})
        rows = result.fetchall()

        return [
            {
                "timestamp": row[0],
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
