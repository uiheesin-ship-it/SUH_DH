"""Earnings-AI (eai) subsystem: conference-call analysis → investment themes.

A separate bounded context inside the existing FastAPI app. Routes live under
/api/eai/* so they never collide with the legacy price-signal dashboards.
"""

__version__ = "0.1.0"
