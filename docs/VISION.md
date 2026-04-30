# Agent Aquila - Product Vision

## Mission

Agent Aquila is a **self-hosted personal AI operations assistant** that helps you manage digital life across multiple services while maintaining complete control over your data, credentials, and infrastructure. It combines intelligent automation with human oversight to create a trusted digital companion.

## Core Philosophy

### 1. Self-Hosted & Privacy-First
- **Your Data, Your Control**: All data stored on your infrastructure
- **No Cloud Dependencies**: Optional external services only when you choose
- **Transparent Operations**: Open source with clear data flows
- **Credential Security**: Encrypted storage, OAuth flows, no third-party sharing

### 2. Context-Aware Intelligence
- **Persistent Memory**: Learns your preferences, relationships, and patterns
- **Semantic Understanding**: Vector-based retrieval for relevant context
- **Personalized Responses**: Adapts to your communication style and needs
- **Continuous Learning**: Improves through interactions and feedback

### 3. Broad Integration Surface
- **Multi-Service Support**: Gmail, Calendar, Drive, Outlook, Teams, and more
- **Unified Interface**: Single chat interface for all operations
- **Consistent Workflows**: Similar patterns across different services
- **Extensible Architecture**: Easy to add new connectors and tools

### 4. Human-in-the-Loop Design
- **Proposal System**: Sensitive actions require explicit approval
- **Transparent Operations**: Clear visibility into agent reasoning
- **Configurable Safety**: Tunable risk thresholds and approval requirements
- **Audit Trail**: Complete history of actions and decisions

## What We Optimize For

### 1. Context-First Activation
When something wakes the agent (a message, a channel ping, a scheduler tick, or a future push notification), the default posture is: **understand the signal, relate it to what we already know about the user, then decide** — not an unbounded deep dive through every tool unless the situation calls for it. Runtime controls (turn profiles, step budgets, scoped tool palettes) make that policy enforceable, not just aspirational in the system prompt.

### 2. Token Efficiency
Full capabilities stay **registered**; non-chat entry points (channels, heartbeats, automation-class runs) can use a **compact** tool palette and stricter step limits so the model is not repaying the cost of the entire catalogue on every wake. A **user context snapshot** is maintained asynchronously so the model gets a short working summary instead of re-deriving the user from raw memory on every run.

### 3. Observability and Control
Runs log structured **AgentRunStep** records; proposals gate high-risk sends (email replies/sends); and **per-user runtime settings** let operators and users cap behavior without forked codebases. A fine-grained **trace event** system also exists (`AgentTraceEvent`) but is optional — see [AGENT_SETTINGS.md](./AGENT_SETTINGS.md).

### 4. Human, Coworker Feel
Persona and workspace files (`agent_workspace/`) describe tone and boundaries. The product goal is an assistant that feels like **another person with access to your systems**, with clear safety defaults (e.g. outbound email approval).

## Target Users

### Primary Users
- **Knowledge Workers**: Professionals managing email, calendar, and documents
- **Small Business Owners**: Need efficient operations without dedicated staff
- **Power Users**: Want automation while maintaining control
- **Privacy-Conscious Users**: Prefer self-hosted solutions over cloud services

### Secondary Users
- **Developers**: Want to extend and customize the system
- **Teams**: Small groups needing shared AI assistant
- **Organizations**: Require on-premises AI solutions

## Key Differentiators

### vs. Cloud AI Assistants
| Feature | Agent Aquila | Cloud Assistants |
|---------|--------------|-----------------|
| Data Control | Full self-hosting | Cloud-hosted |
| Customization | Extensible codebase | Limited configuration |
| Privacy | Complete control | Data shared with provider |
| Cost | Fixed infrastructure | Per-usage pricing |
| Integration | Broad connector support | Limited ecosystem |

### vs. Traditional Automation Tools
| Feature | Agent Aquila | Traditional Tools |
|---------|--------------|------------------|
| Intelligence | AI-powered reasoning | Rule-based automation |
| Flexibility | Natural language interface | Rigid workflows |
| Learning | Adapts to user behavior | Static rules |
| Context | Persistent memory | Limited state |

## Product Architecture

### System Components

#### 1. Agent Core
- **ReAct Loop**: Reasoning + Acting cycle for complex tasks
- **Tool Dispatch**: 50+ tools across multiple service categories
- **Memory Integration**: Context-aware decision making
- **Proposal System**: User approval for sensitive actions

#### 2. Memory System
- **Canonical Storage**: Markdown files for long-term storage
- **Vector Search**: pgvector-based semantic retrieval
- **Auto-Extraction**: Post-turn memory extraction from conversations
- **Consolidation**: Periodic summarization and cleanup

#### 3. Connector System
- **OAuth 2.0**: Secure authentication flow
- **Token Management**: Automatic refresh and rotation
- **Multi-Account**: Support for multiple connections per provider
- **Error Handling**: Graceful degradation and re-auth prompts

#### 4. Multi-Channel Access
- **Web UI**: Modern Next.js interface with real-time updates
- **Telegram Bot**: Chat with your agent via Telegram
- **Channel Gateway**: Extensible architecture for custom channels
- **API Access**: RESTful API for programmatic access

### Data Flow

```
User Input → Agent Core → Tool Dispatch → External Services
                ↓
            Memory System ← Context Extraction
                ↓
            Proposal System ← User Approval
                ↓
            Response Generation → Multi-Channel Output
```

## Current Capabilities (v0.0.9)

### Core Features
- ✅ ReAct-based agent with tool calling
- ✅ Persistent memory system with vector search
- ✅ Multi-provider AI support (OpenAI, Anthropic, Ollama, etc.)
- ✅ OAuth integration for major services
- ✅ Proposal system for sensitive actions
- ✅ Multi-user support with admin controls
- ✅ Web UI with real-time updates
- ✅ Telegram bot integration
- ✅ Skills system for reusable workflows

### Supported Connectors
- ✅ Google Workspace (Gmail, Calendar, Drive, Sheets, Docs, Tasks, People, YouTube)
- ✅ Microsoft 365 (Outlook, Teams)
- ✅ Apple Services (iCloud Drive, Contacts, Calendar)
- ✅ Development Tools (GitHub, Linear, Notion, Slack)
- ✅ Communication (Telegram, WhatsApp, Discord)
- ✅ Productivity (Web search, file operations, scheduled tasks)

## How This Relates to OpenClaw

[OpenClaw](https://github.com/openclaw/openclaw) is a strong reference for the **shape** of a personal assistant: gateway, channels, skills, and file-backed workspace culture. Aquila reuses that **metaphor** (memory keys, skills, `final_answer` termination) but ships as a **Python (FastAPI) + Next.js** stack with its own **harness** goals: **leaner** context assembly on automated wakes, a **first-class** user context snapshot, and **metrics-friendly** agent traces in the database.

We do **not** claim channel-for-channel or feature-for-feature parity with OpenClaw's Node gateway; we **do** aim for **omni-channel** use (web, gateway, and integrations such as Telegram) through a **single** API and agent core.

## Success Metrics

### User Engagement
- Daily active users
- Agent interactions per user
- Task completion rates
- Feature adoption rates

### Technical Performance
- Response times (p50, p95, p99)
- Error rates and uptime
- Resource utilization
- API latency

### Business Impact
- Time saved on routine tasks
- Reduction in manual operations
- User satisfaction scores
- Feature request fulfillment

## Documentation Map

- **Memory mechanics** — [MEMORY.md](./MEMORY.md) and [AGENTIC_MEMORY.md](./AGENTIC_MEMORY.md) (canonical markdown, post-turn extraction)
- **Tunables** — [AGENT_SETTINGS.md](./AGENT_SETTINGS.md) (env vs per-user `agent_runtime_config`)
- **Operator / quota** — [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)
- **All providers** — [PROVIDERS.md](./PROVIDERS.md) (setup guides for Google AI Studio, Ollama, OpenAI, etc.)
- **Connector backlog** — [INTEGRATIONS_ROADMAP.md](./INTEGRATIONS_ROADMAP.md) (feature backlog, not a promise)
- **Skills** — [SKILLS.md](./SKILLS.md) (skill format and authoring guide)
- **Refactors** — [REFACTOR_PLAN.md](./REFACTOR_PLAN.md) (architectural cleanup plan)

## Conclusion

Agent Aquila represents a new approach to personal AI assistants—one that prioritizes user control, privacy, and extensibility while delivering powerful automation capabilities. By combining intelligent agent technology with a self-hosted architecture, it offers a compelling alternative to cloud-based solutions for users who value data sovereignty and customization.

The vision is to create a trusted digital companion that grows with you, learns your preferences, and helps you navigate the complexity of modern digital life—all while keeping you in complete control of your data and digital identity.
