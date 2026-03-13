"""AlertingService — fires HTTP webhooks when observability thresholds are breached.

Supports four channels out of the box:
  * Slack          — Block Kit message via Incoming Webhook
  * Discord        — Embed via Webhook
  * PagerDuty      — Incident via Events API v2 (trigger / dedup by alert_type)
  * Microsoft Teams — Adaptive Card via Incoming Webhook (Connector)

Configuration (via .env):
    SLACK_WEBHOOK_URL       — https://hooks.slack.com/services/T.../B.../xxx
    DISCORD_WEBHOOK_URL     — https://discord.com/api/webhooks/...
    PAGERDUTY_ROUTING_KEY   — 32-char routing key from a PagerDuty Events API v2 integration
    TEAMS_WEBHOOK_URL       — https://<tenant>.webhook.office.com/webhookb2/...
    ALERT_COOLDOWN_SECONDS  — minimum seconds between repeated alerts of the same type
                              (default 300 = 5 minutes)

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

        if settings.pagerduty_routing_key:
            await cls._send_pagerduty(
                settings.pagerduty_routing_key, alert_type, title, message, details, color
            )

        if settings.teams_webhook_url:
            await cls._send_teams(settings.teams_webhook_url, title, message, details, color)

        _any_configured = any([
            settings.slack_webhook_url,
            settings.discord_webhook_url,
            settings.pagerduty_routing_key,
            settings.teams_webhook_url,
        ])
        if not _any_configured:
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

    # ------------------------------------------------------------------ #
    # PagerDuty (Events API v2)
    # ------------------------------------------------------------------ #

    @classmethod
    async def _send_pagerduty(
        cls,
        routing_key: str,
        alert_type: str,
        title: str,
        message: str,
        details: Dict[str, Any],
        color_name: str,
    ) -> None:
        """Trigger a PagerDuty incident via Events API v2.

        Uses ``alert_type`` as the ``dedup_key`` so repeated firings of the
        same alert update the existing incident rather than creating a new one.

        Severity mapping:
            danger  → critical
            warning → warning
            info    → info
        """
        severity_map = {"danger": "critical", "warning": "warning", "info": "info"}
        severity = severity_map.get(color_name, "error")

        payload: Dict[str, Any] = {
            "routing_key": routing_key,
            "event_action": "trigger",
            "dedup_key": alert_type,          # idempotent — same key updates open incident
            "payload": {
                "summary": f"{title}: {message}",
                "severity": severity,
                "source": "llm-observability-dashboard",
                "custom_details": details,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    "https://events.pagerduty.com/v2/enqueue",
                    json=payload,
                )
                if resp.status_code not in (200, 202):
                    logger.warning(
                        "PagerDuty Events API returned %s: %s", resp.status_code, resp.text
                    )
                else:
                    logger.info(
                        "PagerDuty alert triggered: %s (dedup_key=%s)", title, alert_type
                    )
        except Exception as exc:
            logger.warning("Failed to send PagerDuty alert: %s", exc)

    # ------------------------------------------------------------------ #
    # Microsoft Teams (Adaptive Card via Incoming Webhook)
    # ------------------------------------------------------------------ #

    @classmethod
    async def _send_teams(
        cls,
        url: str,
        title: str,
        message: str,
        details: Dict[str, Any],
        color_name: str,
    ) -> None:
        """Post an Adaptive Card to a Microsoft Teams channel via Incoming Webhook.

        Uses the ``application/vnd.microsoft.card.adaptive`` wrapper payload
        accepted by all Teams Incoming Webhook connectors.

        Theme colour:
            danger  → FF4444 (red)
            warning → FF9900 (amber)
            info    → 6264A7 (Teams purple)
        """
        # Build Adaptive Card fact set from details dict
        facts = [
            {"title": str(k), "value": str(v)}
            for k, v in details.items()
        ]

        adaptive_card: Dict[str, Any] = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": [
                {
                    "type": "TextBlock",
                    "text": title,
                    "weight": "Bolder",
                    "size": "Medium",
                    "color": "Attention" if color_name == "danger" else (
                        "Warning" if color_name == "warning" else "Default"
                    ),
                },
                {
                    "type": "TextBlock",
                    "text": message,
                    "wrap": True,
                },
            ],
        }

        if facts:
            adaptive_card["body"].append({
                "type": "FactSet",
                "facts": facts,
            })

        # Teams Incoming Webhook payload wrapper
        payload: Dict[str, Any] = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": adaptive_card,
                }
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, json=payload)
                # Teams returns 200 with body "1" on success
                if resp.status_code not in (200, 202, 204):
                    logger.warning(
                        "Teams webhook returned %s: %s", resp.status_code, resp.text
                    )
                else:
                    logger.info("Teams alert sent: %s", title)
        except Exception as exc:
            logger.warning("Failed to send Teams alert: %s", exc)
