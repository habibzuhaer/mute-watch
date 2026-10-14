"""MUTE alerts — templates, routing, LocalBrain enrichment, Telegram push."""

from alerts.router import ActivityRouter
from alerts.template_engine import TemplateEngine
from alerts.local_brain import LocalBrain

__all__ = ["ActivityRouter", "TemplateEngine", "LocalBrain"]
