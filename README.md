# Agent Aquila

Your self-hosted personal AI operations assistant with **broad connector surface**, **context-first automation**, and **lean tool execution**. Manage email, calendar, files, and more across Gmail, Calendar, Drive, Outlook, Teams, and other services while keeping control where it belongs: **your accounts, your keys, your machine**.

<img src="docs/branding/aquila-mascot.jpg" alt="Agent Aquila" width="138" style="display: block; margin: 0 auto;">

![telegram](https://www.readmecodegen.com/api/social-icon?name=telegram&size=32) ![gmail](https://www.readmecodegen.com/api/social-icon?name=gmail&size=32) ![googlecalendar](https://www.readmecodegen.com/api/social-icon?name=googlecalendar&size=32) ![icloud](https://www.readmecodegen.com/api/social-icon?name=icloud&size=32) ![whatsapp](https://www.readmecodegen.com/api/social-icon?name=whatsapp&size=32) ![github](https://www.readmecodegen.com/api/social-icon?name=github&size=32)

## What is Agent Aquila?

Agent Aquila is a **full-stack AI agent platform** that combines:

- **Intelligent Agent**: ReAct-based AI agent with tool calling capabilities
- **Multi-Service Integration**: Connect to Gmail, Calendar, Drive, Outlook, Teams, and more
- **Persistent Memory**: Long-term memory system that learns your preferences and context
- **Reusable Skills**: Markdown-based workflow playbooks for common tasks
- **Multi-Channel Support**: Web UI, Telegram bot, and extensible channel gateway
- **Proposal System**: User approval workflow for sensitive actions
- **Multi-User Support**: Admin controls and user management
- **Self-Hosted**: Complete control over your data and API keys

## Key Features

### 🦅 Intelligent Agent

- **ReAct Loop**: Reasoning + Acting cycle for complex task execution
- **Tool Calling**: 50+ tools across multiple service categories
- **Context-Aware**: Memory system provides personalized context
- **Scoped Tool Palettes**: Optimized tool selection for different scenarios

### 🔌 Service Connectors

- **Google Workspace**: Gmail, Calendar, Drive, Sheets, Docs, Tasks, People, YouTube
- **Microsoft 365**: Outlook (Graph mail), Teams
- **Apple Services**: iCloud Drive, Contacts, Calendar (CalDAV)
- **Development Tools**: GitHub, Linear, Notion, Slack
- **Communication**: Telegram, WhatsApp, Discord
- **Productivity**: Web search, file operations, scheduled tasks

### 🧠 Memory System

- **Canonical Storage**: Markdown-based memory files (MEMORY.md, USER.md, daily logs)
- **Semantic Search**: Vector-based memory retrieval with embeddings
- **Auto-Extraction**: Post-turn memory extraction from conversations
- **Consolidation**: Periodic memory consolidation and summarization

### 📋 Skills System

- **Gmail Triage**: Priority-based inbox management
- **Weekly Review**: Structured digest from email, calendar, and memory
- **Silence Sender**: Mute/spam management with filter rules
- **Custom Skills**: Easy authoring with markdown templates

### 🔒 Security & Control

- **OAuth 2.0**: Secure authentication for all connected services
- **Proposal System**: User approval required for sensitive actions
- **API Key Encryption**: Encrypted storage for AI provider credentials
- **Rate Limiting**: Configurable rate limits per user
- **Admin Controls**: User management and system settings

### 📱 Access Channels

- **Web UI**: Modern Next.js interface with real-time updates
- **Telegram Bot**: Chat with your agent via Telegram
- **Channel Gateway**: Extensible architecture for custom channels
- **API Access**: RESTful API for programmatic access

---

## Quick Start

### Docker Compose (Recommended)

```bash
# Clone the repository
git clone <repository-url>
cd agent-aquila

# Copy environment template
cp .env.example .env

# Start all services
docker compose up --build
```

1. Open <http://localhost:3002> — you'll be redirected to the **Create account** page
2. Register your first account (automatically becomes the **instance admin**)
3. Configure your AI provider in **Settings → AI**
4. Connect external services in **Settings → Connectors**  
   If Google or Microsoft refuse your redirect URL while you use a **private or Tailscale IP** in the browser, read **Google / Microsoft OAuth without a public domain** below—this is expected until you add a public HTTPS origin.

### Google / Microsoft OAuth without a public domain (Cloudflare quick tunnel)

This subsection is for people who run Agent Aquila at home (or only on Tailscale / a LAN) and **do not** have a normal domain or reverse proxy yet. If you already serve the app at `https://your-domain`, skip this and use that URL everywhere below instead of the tunnel.

#### What problem this solves

Signing in to Google or Microsoft from Aquila uses **OAuth**. After you approve access in the browser, Google or Microsoft **redirects your browser** to a URL on **your** installation (the “callback”). You must **register that exact callback URL** in Google Cloud Console / Azure.

Those consoles **do not accept** addresses like:

- `http://192.168.x.x:3002/…` (LAN)
- `http://100.x.x.x:3002/…` (Tailscale)

So if you only ever open Aquila with a private IP, you can use the app, but you **cannot** complete “Connect Google” / “Connect Microsoft” until you introduce **some HTTPS address that still reaches this same Docker stack** and that providers treat as a normal hostname.

**You do not need a monitor on the server.** You complete OAuth in a browser on your phone or laptop. The server stays headless.

#### What the optional tunnel does

The Compose file includes a small **Cloudflare Tunnel** sidecar (`cloudflared`) behind the profile `oauth-tunnel`. When you run it, Cloudflare gives you a temporary **`https://….trycloudflare.com`** URL that forwards traffic to the **frontend** container. From the internet’s point of view, your app has a public HTTPS origin—even though it still runs on your machine.

- **Pros**: No domain purchase, no DNS, works through NAT.
- **Cons**: A **quick tunnel** URL **changes** when the tunnel container is recreated. If it changes, you must update **Public URL** in Aquila and the redirect URIs in Google / Azure (or switch to a stable domain / [named Cloudflare tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/) later).

#### How to use it (step by step)

1. **Start the main stack** (if it is not already running):

   ```bash
   docker compose up -d --build
   ```

2. **Start the tunnel** (separate command; only starts `cloudflared`):

   ```bash
   docker compose --profile oauth-tunnel up -d cloudflared
   ```

3. **Read the public URL from the tunnel logs.** Cloudflare prints a line containing your hostname, for example `https://random-words.trycloudflare.com`:

   ```bash
   docker compose logs cloudflared
   ```

   Copy **only the origin**: `https://random-words.trycloudflare.com` (no path, no trailing slash).

4. **Register redirect URIs** in each provider (replace the origin with yours):

   - **Google** (OAuth client type **Web application** → **Authorized redirect URIs**):
     - `https://random-words.trycloudflare.com/api/v1/oauth/google/callback`
   - **Microsoft** (App registration → **Authentication** → **Redirect URIs**):
     - `https://random-words.trycloudflare.com/api/v1/oauth/microsoft/callback`

5. **Open Aquila in a browser** (you can use Tailscale or LAN as usual, or open the trycloudflare URL—either is fine for clicking around).

6. Go to **Settings → Connectors**:

   - In **Public URL**, paste the same origin: `https://random-words.trycloudflare.com`
   - Enter your Google / Microsoft client ID and secret, then **Save Google link** / **Save Microsoft link** so Aquila stores that origin.

7. Click **Connect Google** or **Connect Microsoft**. Your browser will go to the provider; after you approve, the provider will send you back to the **trycloudflare** callback, which reaches your stack and finishes the link.

8. **Keep the tunnel running** whenever you need to **connect or reconnect** OAuth (new tokens / revoked access). Day-to-day chat may keep working for a while with stored tokens, but reconnects always need the callback URL to work again.

#### If you outgrow the quick tunnel

For a URL that does not change on every restart, use a real domain with HTTPS (VPS + Caddy/Let’s Encrypt, or a **named** Cloudflare Tunnel with a hostname you control). Then set **Public URL** to that `https://…` origin and update the provider redirect URIs once.

### Manual Setup

For development or custom deployments:

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head

# Frontend
cd frontend
npm install
npm run dev
```

### Create Admin User

```bash
# Via Docker
docker compose exec backend python -m app.scripts.create_admin \
  --email admin@example.com --password yourpassword

# Or directly
cd backend
python -m app.scripts.create_admin --email admin@example.com --password yourpassword
```

## Service URLs

| Service | URL | Notes |
|---------|-----|-------|
| Web App | <http://localhost:3002> | Next.js frontend |
| API Docs | <http://localhost:8000/docs> | FastAPI Swagger UI |
| Postgres | `localhost:5433` | Database |
| Redis | `localhost:6379` | Job queue & caching |

## Architecture Overview

### Backend (FastAPI)

- **API Layer**: RESTful endpoints in `backend/app/routes/`
- **Services**: Business logic in `backend/app/services/`
- **Models**: SQLAlchemy ORM in `backend/app/models/`
- **Agent Core**: ReAct loop and tool dispatch in `backend/app/services/agent/`
- **Connectors**: External service clients in `backend/app/services/connectors/`
- **Worker**: Background job processing with ARQ

### Frontend (Next.js)

- **Pages**: Route handlers in `frontend/src/app/`
- **Components**: Reusable UI in `frontend/src/components/`
- **Features**: Feature-specific components in `frontend/src/components/features/`
- **API Client**: Type-safe API calls in `frontend/src/lib/api.ts`

### Key Systems

#### Agent Execution

- **ReAct Loop**: Reasoning + Acting cycle for complex tasks
- **Tool Dispatch**: 50+ tools across multiple service categories
- **Memory Integration**: Context-aware decision making
- **Proposal System**: User approval for sensitive actions

#### Memory System

- **Canonical Storage**: Markdown files in `data/users/<user_id>/memory_workspace/`
- **Vector Search**: pgvector-based semantic retrieval
- **Auto-Extraction**: Post-turn memory extraction from conversations
- **Consolidation**: Periodic summarization and cleanup

#### Connector System

- **OAuth 2.0**: Secure authentication flow
- **Token Management**: Automatic refresh and rotation
- **Multi-Account**: Support for multiple connections per provider
- **Error Handling**: Graceful degradation and re-auth prompts

## Configuration

### Environment Variables

Key environment variables (see `.env.example` for complete list):

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5433/aquila_db

# Redis
REDIS_URL=redis://localhost:6379

# AI Provider (choose one or configure in UI)
# OpenAI, Anthropic, Ollama, etc.

# Security
JWT_SECRET=your-secret-key
ENCRYPTION_KEY=your-encryption-key

# Features
REGISTRATION_OPEN=false
AGENT_HEARTBEAT_ENABLED=false
AGENT_CHANNEL_GATEWAY_ENABLED=false
```

### Per-User Settings

Users can configure:

- **AI Provider**: Multiple provider support with per-user API keys
- **Agent Behavior**: Rate limits, tool palettes, memory settings
- **Connectors**: OAuth connections to external services
- **Appearance**: Theme, language, timezone
- **Telegram**: Bot integration settings

## Development

### Backend Development

```bash
cd backend

# Run tests
pytest

# Run with coverage
pytest --cov=app

# Run specific test
pytest tests/test_agent_tools.py

# Database migrations
alembic revision --autogenerate -m "description"
alembic upgrade head
```

### Frontend Development

```bash
cd frontend

# Run dev server
npm run dev

# Run linting
npm run lint

# Build for production
npm run build
```

### Adding New Features

#### Add a New Tool

1. Define tool schema in `backend/app/services/agent_tools.py`
2. Implement handler in `backend/app/services/agent/handlers/`
3. Add dispatch entry in `backend/app/services/agent/dispatch.py`

#### Add a New Connector

1. Create client in `backend/app/services/connectors/`
2. Add OAuth flow in `backend/app/services/oauth/`
3. Create tool handlers for connector operations

#### Add a New Skill

1. Create `backend/skills/<skill-name>/SKILL.md`
2. Follow the skill template with frontmatter and steps
3. Test with agent via `load_skill` tool

## Documentation

- **[VISION.md](docs/VISION.md)** - Product vision and design philosophy
- **[MEMORY.md](docs/MEMORY.md)** - Memory system architecture
- **[AGENT_SETTINGS.md](docs/AGENT_SETTINGS.md)** - Agent runtime configuration
- **[SKILLS.md](docs/SKILLS.md)** - Skills system and authoring guide
- **[AGENTIC_MEMORY.md](docs/AGENTIC_MEMORY.md)** - Memory implementation details
- **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** - Common issues and solutions
- **[testing.md](docs/testing.md)** - Testing guide and patterns

## Safety & Security

### Default Safety Policies

- **Proposal System**: Sending/replying to emails requires user approval
- **Rate Limiting**: Configurable limits per user to prevent abuse
- **API Key Encryption**: All credentials encrypted at rest
- **OAuth Security**: Secure token storage and automatic refresh

### Tuning Safety Policies

Modify proposal tools in:

- `backend/app/services/agent_tools.py` - `_PROPOSAL_TOOLS`
- `backend/app/services/capability_registry.py` - Risk tiers

## Troubleshooting

### Common Issues

**Frontend 500 errors**: Check backend logs and ensure database migrations are complete

**OAuth failures**: Verify redirect URIs and app credentials in provider console

**Agent not responding**: Check AI provider configuration and API key validity

**Memory not working**: Ensure pgvector extension is installed in PostgreSQL

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for detailed solutions.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## License

[Your License Here]

## Support

- **Issues**: GitHub Issues
- **Documentation**: See `/docs` directory
- **Community**: [Your Community Link]
