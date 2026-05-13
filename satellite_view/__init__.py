"""Package entry point for the satellite_view application."""

from .webapp import app, create_app

__all__ = ["app", "create_app"]
