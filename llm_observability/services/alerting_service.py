"""AlertingService — fires HTTP webhooks when observability thresholds are breached.

Supports Slack and Discord out of the box.  Any other service that accepts
an inbound webhook (PagerDuty, Teams, custom HTTP endpoint) can be added by
extending ``_send_generic``.

Configuration (via .env):
    SLACK_WEBHOOK_URL   — e.g. https://hooks.slack.com/services/T.../B.../xxx
    DISCORD_WEBHOOK_URL — e.g. https://discord.com/api/webhooks/...
    ALERT_COOLDOWN_SECONDS — minimum seconds between repeated alerts of the
                             same type (default 300 = 5 minutes)

Cooldown state is in-memory (resets on process restart).  This is intentional
— it keeps the service stateless and dependency-free.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class AlertingService:
    """Fire-and-forget webhook alerting with per-type cooldowns."""

    # Class-level cooldown tracker: alert_type → last_fired_unix_timestamp
    _last_fired: Dict[str, float] = {}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @classmethod
    async def send_alert(
        cls,
        alert_type: str,
        title: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        color: str = "danger",  # "danger" | "warning" | "info"
    ) -> None:
        """Fire a webhook alert if the cooldown period has elapsed.

        Args:
            alert_type: Short key used for deduplication, e.g. "high_latency".
            title:      Bold headline shown in the notification.
            message:    One-line description of the alert.
            details:    Optional dict of key-value pairs shown as fields.
            color:      Semantic colour hint (used in Discord embeds).
        """
        from llm_observability.core.config import settings  # lazy to avoid circular

        # --- cooldown check ----------------------------------------------- #
        now = time.time()
        last = cls._last_fired.get(alert_type, 0.0)
        if now - last < settings.alert_cooldown_seconds:
            logger.debug(
                "Alert '%s' suppressed (cooldown %ds remaining)",
                alert_type,
                int(settings.alert_cooldown_seconds - (now - last)),
            )
            return
        cls._last_fired[alert_type] = now

        # --- dispatch ------------------------------------------------------- #
        details = details or {}

        if settings.slack_webhook_url:
            await cls._send_slack(settings.slack_webhook_url, title, message, details)

        if settings.discord_webhook_url:
            await cls._send_discord(settings.discord_webhook_url, title, message, details, color)

        if not settings.slack_webhook_url and not settings.discord_webhook_url:
            # No webhook configured — fall back to a prominent log line so the
            # operator can still see the alert in console/log files.
            logger.warning(
                "ALERT [%s] %s — %s | %s",
                alert_type.upper(),
                title,
                message,
                details,
            )

    # ------------------------------------------------------------------ #
    # Slack
    # ------------------------------------------------------------------ #

    @classmethod
    async def _send_slack(
        cls,
        url: str,
        title: str,
        message: str,
        details: Dict[str, Any],
    ) -> None:
        icon = ":rotating_light:"
        fields = [
            {"type": "mrkdwn", "text": f"*{k}*\n{v}"}
            for k, v in details.items()
        ]
        payload: Dict[str, Any] = {
            "text": f"{icon} *LLM Observability Alert*",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"{title}", "emoji": True},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message},
                },
            ],
        }
        if fields:
            payload["blocks"].append({"type": "section", "fields": fields})

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code not in (200, 204):
                    logger.warning("Slack webhook returned %s: %s", resp.status_code, resp.text)
        except Exception as exc:
            logger.warning("Failed to send Slack alert: %s", exc)

    # ------------------------------------------------------------------ #
    # Discord
    # ------------------------------------------------------------------ #

    @classmethod
    async def _send_discord(
        cls,
        url: str,
        title: str,
        message: str,
        details: Dict[str, Any],
        color_name: str,
    ) -> None:
        color_map = {"danger": 0xF43F5E, "warning": 0xF59E0B, "info": 0x6366F1}
        embed_color = color_map.get(color_name, 0x6366F1)

        fields = [
            {"name": str(k), "value": str(v), "inline": True}
            for k, v in details.items()
        ]
        payload: Dict[str, Any] = {
            "embeds": [
                {
                    "title": title,
                    "description": message,
                    "color": embed_color,
                    "fields": fields,
                    "footer": {"text": "LLM Observability Dashboard"},
                }
            ]
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code not in (200, 204):
                    logger.warning(
                        "Discord webhook returned %s: %s", resp.status_code, resp.text
                    )
        except Exception as exc:
            logger.warning("Failed to send Discord alert: %s", exc)
