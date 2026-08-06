# 📚 Documentation Index

All project documentation lives in this folder. `CLAUDE.md` stays at the repo
root because Claude Code reads it as project instructions.

**Last reviewed:** 01 August 2026

---

## Start here

| Doc | What it covers |
|---|---|
| [QUICK_START.md](QUICK_START.md) | Fastest path to a running system |
| [STARTUP_README.md](STARTUP_README.md) | Startup scripts and service orchestration |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System overview, the three services, module map, **supply-chain data flow**, performance notes |
| [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) | Every table, live row counts, **Tijori tables**, read-size limits |
| [CHANGELOG.md](CHANGELOG.md) | What changed and when |

## Data & analysis

| Doc | What it covers |
|---|---|
| [FINANCIAL_DATA_SOURCES.md](FINANCIAL_DATA_SOURCES.md) | Where each number comes from, including the Tijori supply-chain source |
| [THREE_SERVICES_AWARENESS.md](THREE_SERVICES_AWARENESS.md) | How the Flask backend, Next.js frontend and Graphify relate |
| [GRAPHIFY_STATUS.md](GRAPHIFY_STATUS.md) | Knowledge-graph build status and coverage |

## Trading costs

| Doc | What it covers |
|---|---|
| [COST_SYSTEM_SUMMARY.md](COST_SYSTEM_SUMMARY.md) | High-level overview of the cost engine |
| [COST_API_INTEGRATION.md](COST_API_INTEGRATION.md) | Cost API endpoints and payloads |
| [COST_AUTOMATION_GUIDE.md](COST_AUTOMATION_GUIDE.md) | Automated scraping of broker charges |
| [COST_SYSTEM_DEPLOYMENT.md](COST_SYSTEM_DEPLOYMENT.md) | Deploying and verifying the cost system |

## Frontend

| Doc | What it covers |
|---|---|
| [FRONTEND_SETUP_GUIDE.md](FRONTEND_SETUP_GUIDE.md) | Next.js frontend setup |
| [RUN_INDIVIDUAL_SERVICES.md](RUN_INDIVIDUAL_SERVICES.md) | Running each service on its own |

## Reference

| Doc | What it covers |
|---|---|
| [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) | Implementation notes and decisions |
| [SYSTEM_DELIVERED.md](SYSTEM_DELIVERED.md) | Delivered-scope record |
| [README_INDEX.md](README_INDEX.md) | Older index, kept for history |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common failures and fixes |
| [compliance_analysis.md](compliance_analysis.md) | Regulatory/compliance review |

---

## Conventions

- **Build, never destroy.** See `CLAUDE.md` at the repo root — deletions need
  explicit double confirmation.
- **Nothing hardcoded.** Operational behaviour lives in the `config_settings`
  table and is editable from the dashboard's Settings tab.
- **Config reads are memoized** (30s). Use `get_configs()` /
  `get_configs_prefix()` rather than calling `get_config()` in a loop.
- **Batch DB reads.** Preload into a dict before a loop; never query per item.
- **Large tables take limits.** See the read-size table in `DATABASE_SCHEMA.md`.
