# ClawWrap

Spec-first control plane for typed, policy-enforced outbound message routing.

Every agent-initiated send (email, WhatsApp, Slack, SMS) routes through ClawWrap's gate, which validates targets, applies policies, and logs verdicts before dispatch.

## Features

- **Outbound gate** — 5-stage pipeline: resolve → verify → approve → execute → audit
- **Policy enforcement** — allowlists, rate limits, channel restrictions per target
- **Two routing modes** — shared (context_key + audience → target) and direct (recipient_ref → adapter resolver)
- **15+ handler implementations** — email, WhatsApp DM/group, Slack, SMS, target resolution
- **Database-backed audit trail** — PostgreSQL with Alembic migrations
- **Spec-first contracts** — YAML wrapper and policy specifications
- **Conformance auditing** — verify all outbound paths comply with declared policies

## Installation

```bash
pip install clawwrap
```

## Quick Start

```bash
# Initialize database schema
clawwrap init

# Run Alembic migrations
clawwrap migrate

# Validate a wrapper spec
clawwrap validate specs/outbound-email.yaml

# Show dependency graph
clawwrap graph specs/outbound-email.yaml

# Run a wrapper
clawwrap run specs/outbound-email.yaml

# Audit conformance
clawwrap conformance audit
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `init` | Initialize database schema |
| `migrate` | Run Alembic migrations |
| `validate` | Validate wrapper/policy specs |
| `graph` | Show DAG of dependencies |
| `run` | Execute a wrapper run |
| `apply` | Apply policies and handlers |
| `conformance` | Check conformance to specs |
| `handler` | Manage handler definitions |
| `legacy` | Authority/ownership operations |

## Architecture

```
Agent → outbound.submit(context_key, audience, channel)
         ↓
    ┌─────────────────────────┐
    │  ClawWrap Gate          │
    │  1. Resolve target      │ ← targets.yaml
    │  2. Verify identity     │ ← live checks (JID, email, channel)
    │  3. Apply policy        │ ← outbound-policy.yaml
    │  4. Dispatch            │ ← channel handler (email, WhatsApp, Slack)
    │  5. Audit log           │ ← PostgreSQL + YAML verdicts
    └─────────────────────────┘
```

## Configuration

**targets.yaml** — outbound routing addresses:
```yaml
retreat_staff:
  whatsapp:
    jid: "120363...@g.us"
  email:
    address: "team@example.com"
  slack:
    channel: "#ops"
```

**outbound-policy.yaml** — allowlists and checks:
```yaml
channels:
  email:
    enabled: true
    rate_limit: 50/hour
  whatsapp:
    enabled: true
    require_verification: true
  slack:
    enabled: true
```

## Using with ClawSpec

[ClawSpec](https://github.com/austinmao/clawspec) provides contract-first QA for ClawWrap handlers. Test that your outbound gate routes correctly, applies policies, and logs verdicts:

```bash
pip install clawspec
clawspec run --scenario outbound-gate-smoke
```

ClawSpec's trace-aware assertions can verify the full gate pipeline:
```yaml
then:
  - type: tool_sequence
    expected: ["target_resolve", "jid_verify", "outbound_submit"]
    mode: ordered
  - type: no_span_errors
```

## Using with ClawScaffold

[ClawScaffold](https://github.com/austinmao/clawscaffold) manages ClawWrap handler lifecycle. When adopting or creating new handlers:

```bash
pip install clawscaffold
clawscaffold adopt --name outbound/email-send --source src/clawwrap/adapters/openclaw/handlers/email_send.py --kind skill
```

## Related Projects

- **[ClawSpec](https://github.com/austinmao/clawspec)** — Contract-first QA for OpenClaw skills and agents
- **[ClawScaffold](https://github.com/austinmao/clawscaffold)** — Spec-first target lifecycle manager
- **[OpenClaw](https://github.com/austinmao/openclaw)** — Local-first AI agent framework

## Development

```bash
git clone https://github.com/austinmao/clawwrap.git
cd clawwrap
pip install -e ".[dev]"
pytest
```

## OpenClaw Suite

Part of the OpenClaw open-source toolchain:

| Package | Description | Repo |
|---------|-------------|------|
| **ClawPipe** | Config-driven pipeline orchestration engine | [austinmao/clawpipe](https://github.com/austinmao/clawpipe) |
| **ClawSpec** | Contract-first QA for skills and agents | [austinmao/clawspec](https://github.com/austinmao/clawspec) |
| **ClawWrap** | Outbound message routing and policy enforcement | [austinmao/clawwrap](https://github.com/austinmao/clawwrap) |
| **ClawAgentSkill** | Agent and skill discovery, security scanning | [austinmao/clawagentskill](https://github.com/austinmao/clawagentskill) |
| **ClawScaffold** | Agent and skill scaffolding and lifecycle management | [austinmao/clawscaffold](https://github.com/austinmao/clawscaffold) |

## License

MIT
