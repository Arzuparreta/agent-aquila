"""SQLAlchemy model registry.

After the OpenClaw refactor the data model is intentionally tiny:
- Agent state: AgentRun/AgentRunStep, AgentMemory, ChatThread/ChatMessage,
  PendingProposal, AuditLog.
- Connector credentials: ConnectorConnection.
- User account + AI provider settings.

No CRM (contacts/deals/events), no email/calendar/drive mirrors, no
push subscriptions, no automations, no rag_chunks, no executed_actions.
All of those have been removed in favor of live API calls + the agent
memory table. Email sends/replies are still gated through PendingProposal,
but every other tool runs auto-applied against the live provider API.
"""
from app.models.agent_memory import AgentMemory
from app.models.agent_run import AgentRun, AgentRunStep, AgentTraceEvent
from app.models.channel_thread_binding import ChannelThreadBinding
from app.models.audit_log import AuditLog
from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread
from app.models.connector_connection import ConnectorConnection
from app.models.instance_oauth_settings import InstanceOAuthSettings
from app.models.pending_proposal import PendingProposal
from app.models.user import User
from app.models.user_ai_provider_config import UserAIProviderConfig
from app.models.user_ai_settings import UserAISettings
from app.models.telegram_channel import TelegramAccountLink, TelegramPairingCode

__all__ = [
    "AgentMemory",
    "AgentRun",
    "AgentRunStep",
    "AgentTraceEvent",
    "ChannelThreadBinding",
    "AuditLog",
    "ChatMessage",
    "ChatThread",
    "ConnectorConnection",
    "InstanceOAuthSettings",
    "PendingProposal",
    "User",
    "UserAIProviderConfig",
    "UserAISettings",
    "TelegramAccountLink",
    "TelegramPairingCode",
]
