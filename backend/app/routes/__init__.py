"""FastAPI router aggregator.

After the OpenClaw-style refactor this is intentionally short: there is
no CRM (contacts/deals/events), no automations, no push notifications,
no local mail mirror. The agent and the live provider proxies are the
only surface area now.
"""
from fastapi import APIRouter

from app.routes import (
    agent,
    ai,
    auth,
    calendar,
    connectors,
    drive,
    gmail,
    maintenance,
    memory,
    oauth,
    outlook,
    skills,
    teams,
    threads,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(ai.router)
api_router.include_router(agent.router)
api_router.include_router(connectors.router)
api_router.include_router(oauth.router)
api_router.include_router(threads.router)
api_router.include_router(maintenance.router)
# Live provider proxies — every external API call goes through these.
api_router.include_router(gmail.router)
api_router.include_router(calendar.router)
api_router.include_router(drive.router)
api_router.include_router(outlook.router)
api_router.include_router(teams.router)
# Agent self-state: persistent memory + skill files.
api_router.include_router(memory.router)
api_router.include_router(skills.router)
