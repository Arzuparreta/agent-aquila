from fastapi import APIRouter

from app.routes import agent, ai, auth, automations, connectors, contacts, deals, emails, events, oauth

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(contacts.router)
api_router.include_router(emails.router)
api_router.include_router(deals.router)
api_router.include_router(events.router)
api_router.include_router(ai.router)
api_router.include_router(agent.router)
api_router.include_router(connectors.router)
api_router.include_router(oauth.router)
api_router.include_router(automations.router)
