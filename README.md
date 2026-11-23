# KIS

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

A self hosted teaching platform with AI assisted tools for course material and study support.
Developed at Institut für Interaktive Systeme (ISy), Technische Hochschule Lübeck.
Website with screenshots: [kis-thl.de](https://kis-thl.de)

Runs entirely on your own infrastructure. No data leaves it unless you configure an external
provider.

## Features

- Translation of documents
- Slide decks from an outline
- Screencasts from PPTX
- Podcasts from source material
- Pages from source material
- Transcription, text to speech, summaries, images
- Study assistant: chat with citations and learning tools
- Info assistant with its own document index
- Admin for accounts, rights and AI providers

## Stack

- Frontend: Next.js 15, React 19, TypeScript, Tailwind 4, next-intl (DE/EN)
- Backend: FastAPI, Python 3.11, Celery, Redis
- Data: PostgreSQL 16 with pgvector, S3 compatible storage
- System tools: FFmpeg, LibreOffice, poppler-utils

## Requirements

- Docker and Docker Compose v2
- Node.js 20+, only for the development setup below

## Run it locally

```bash
cp .env.example .env
docker compose up -d
```

Open `http://localhost:3000` and log in with `admin` / `adminpw`.

## Development setup

For working on the code, the frontend runs from the Next.js dev server instead of the container.
Add these two lines to `.env`:

```dotenv
COMPOSE_PATH_SEPARATOR=:
COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml
```

Then:

```bash
docker compose up -d
cd frontend && npm install && npm run dev
```

Adds backend reload, Adminer and Langfuse. API docs: `http://localhost:8000/docs`.

## Further settings

`.env.example` holds only what every installation sets. Everything below has a default and goes
into `.env` only to change it.

| Setting | Default | Purpose |
|---|---|---|
| `ADMIN_USERNAME` | part of `ADMIN_EMAIL` before the @ | login name of the admin |
| `SESSION_SECRET` | derived from `KIS_SECRETS_KEY` | signs the session cookies |
| `MODULES` | `aia,tools` | modules this installation runs, needs a restart, locally the workers of both start anyway |
| `ACCOUNT_CREATION_ENABLED` | `false` | unlocks invitations, access codes and accounts created by hand |
| `AUTH_DISABLED` | `false` | no login at all, local use only |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `kis`, `kis-local-dev`, `kis` | database account |
| `DATABASE_URL` | built from the three above | database connection |
| `S3_ENDPOINT`, `S3_BUCKET` | `http://minio:9000`, `kis` | object storage |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY` | `minioadmin` | object storage account, also used by the local MinIO |
| `WEB_CONCURRENCY` | cores minus one, at most 8 | backend processes |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | empty | tracing, in development `LANGFUSE_HOST=http://kis-langfuse:3000` |
| `HPC_LOGIN` | empty | SSH login for the `hpc` profile |

A real installation changes at least `POSTGRES_PASSWORD` and the two `S3_` keys.

## AI providers

The repository ships no API keys. Providers are added at runtime under **Admin → AI**, and every
feature is routed to a model there. Any OpenAI compatible endpoint works, plus DeepL.

Speech and local models run outside the stack and are reached by base URL, for example Ollama at
`http://host.docker.internal:11434/v1`.

The study assistant works best with a large context window, we run it with 128k tokens. A smaller
model works too, KIS measures its window and sizes the context to fit.

### Study assistant with Ollama

The study assistant also runs on local models. Tested only on a MacBook Pro M5 Max with 64 GB,
using `gemma4:31b-mlx` for chat and `qwen3-embedding:4b` for embedding. Smaller chat models often
claimed the answer was not in the sources. A chat answer took 9 to 34 seconds.

## License

Apache 2.0, Copyright 2026 Technische Hochschule Lübeck.
See [LICENSE](LICENSE), [NOTICE](NOTICE), [AUTHORS](AUTHORS) and [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt).
