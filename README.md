# PinchFast Memory

AI project manager memory and decision microservice.

This service is the "brain" of an AI project manager that bridges founders and
their engineering teams. It ingests conversations (founder chats, Slack messages
relayed from the main Django backend), extracts structured facts into a
per-organization knowledge graph with vector search, and exposes retrieval,
people, project, and report endpoints that the Django backend calls to give the
PM agent its memory and decision support.

## Architecture

```
Django backend (Slack relay, PM agent) ──HTTP (X-API-Key)──> kgmemory
                                                                │
   ┌────────────────────────────────────────────────────────────┴───────────┐
   │ FastAPI API (auth, rate limit, metrics)                                 │
   │  /memory/ingest   /context/search   /people   /projects   /reports     │
   └────────┬───────────────────────────────────────────────────────────────┘
            │ SAQ enqueue
            ▼
   ┌────────────────────┐    ┌──────────────────┐    ┌─────────────────────┐
   │ SAQ Worker         │───>│ OpenAI-compat LLM │───>│ FalkorDB (per org)  │
   │ ingest / report    │    │ + embeddings      │    │ graph + vector idx  │
   └────────────────────┘    └──────────────────┘    └─────────────────────┘
            │                                                ▲
            ▼                                                │
   ┌────────────────────┐    ┌──────────────────┐           │
   │ Redis (queue+rate) │    │ Postgres (orgs,  │           │
   └────────────────────┘    │  users, API keys)│───────────┘
                             └──────────────────┘  graph_name = org_<hex>
```

### Multi-tenancy

Each SaaS organization gets its own FalkorDB graph (`org_<uuid_hex>`), so facts,
people, and projects are hard-isolated per tenant. API keys (SHA-256 hashed) are
issued per org and required on every memory/context/people/project/report
endpoint via the `X-API-Key` header.

### Memory pipeline

1. `POST /memory/ingest` enqueues a SAQ job.
2. Worker chunks the message, calls the LLM to extract atomic facts
   (`subject predicate value` + topics/entities/kind/sentiment/due_date).
3. Facts are embedded, deduplicated (deterministic UUIDv5 + cosine ≥0.92),
   superseded when single-valued slots change, and written to the org graph
   with bridge edges to `Topic`, `Entity`, `Person`, `Project`, `Task`,
   `Episode` nodes plus a vector index on `Fact.embedding`.
4. `POST /context/search` runs hybrid retrieval: LLM intent → parallel vector
   ANN + graph traversal + recency → optional LLM associative rerank → rendered
   prompt context for the PM agent.

### Decision support

- `GET /people/{name}` returns a person's facts and a reliability score derived
  from commitment / status_update / performance facts they stated.
- `GET /projects/tasks/{task_id}/recommendations` matches a task's required
  skills against people's skills and ranks candidates by coverage.
- `POST /reports/` enqueues an LLM-composed founder report (weekly / status /
  risk / founder_summary) in the org's preferred language.

## Tech stack

- Python 3.14, FastAPI, Pydantic v2, Tortoise ORM + Aerich (Postgres)
- SAQ + Redis (async job queue), FalkorDB (graph + vector), OpenAI-compatible
  LLM/embeddings, Prometheus metrics, structlog/rich logging
- uv package manager, ruff + mypy, pytest, Docker + docker-compose

## Quick start

```shell
just setup                 # uv sync, copy .env, migrate
just work                  # api + worker + redis + falkordb
# or
just compose-up            # full stack via docker compose
```

Create an org and an API key (auth via fastapi-users JWT):

```shell
just create-user           # admin user
# POST /orgs/ then POST /orgs/{id}/api-keys  ->  returns raw key
```

Use the raw key on subsequent calls:

```shell
curl -H "X-API-Key: pfm_..." -H "Content-Type: application/json" \
  -d '{"message":"I will ship the auth module by Friday","speaker":"Dave","speaker_role":"engineer"}' \
  http://localhost:8001/memory/ingest
```

## Project layout

```
kgmemory/
  core/         config, logger, metrics, redis, rate_limit, auth (fastapi-users)
  db/           Tortoise config + base models
  orgs/         SaaS orgs + API keys (Postgres) + X-API-Key auth dependency
  graph/        FalkorDB client, per-org graph selection, schema/indexes
  llm/          OpenAI-compatible LLM + embeddings clients, lenient JSON, prompts
  memory/       fact schema, extraction, dedup/supersede, ingest, repository, routes, tasks
  contextengine/ hybrid retrieval (intent, dense, traversal, rerank) + routes
  people/       person profiles, skills, reliability scoring + routes
  projects/     project/task tracking, skill-match assignment + routes
  reports/      LLM report generation + async tasks + routes
  users/        fastapi-users (template, kept)
  services/     email (template, kept)
  main.py       FastAPI app wiring (CORS, metrics, lifespan, routers)
  worker.py     SAQ worker settings
  health.py     /health and /health/ready (Postgres, Redis, FalkorDB)
```

## Configuration

See `.env.template` for all options. Key groups: LLM, embeddings, FalkorDB,
ingestion tuning, context engine weights, rate limiting, SES email.
