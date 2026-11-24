# askFrancis

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

A self hosted teaching platform with AI assisted tools for course material and study support.
Developed in the KIS project at Institut für Interaktive Systeme (ISy), Technische Hochschule Lübeck.
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

`.env` needs two values, both preset in `.env.example`:

```dotenv
ADMIN_EMAIL=admin@example.org
ADMIN_PASSWORD=adminpw
```

Open `http://localhost:3000` and log in with `admin` / `adminpw`. Without any login, set only
`AUTH_DISABLED=true` instead, then everybody on this machine is admin.

## Development setup

Same `.env` as above, plus these two lines:

```dotenv
COMPOSE_PATH_SEPARATOR=:
COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml
```

Then:

```bash
docker compose up -d
cd frontend && npm install && npm run dev
```

The backend reloads on every change.

| What | Address | Login |
|---|---|---|
| askFrancis | `http://localhost:3000` | `admin` / `adminpw` |
| API docs | `http://localhost:8000/docs` | |
| Langfuse | `http://localhost:3001` | `admin@example.org` / `admin123` |
| Adminer | `http://localhost:8081` | PostgreSQL, server `postgres`, user `askf`, password `askf-local-dev` |
| MinIO | `http://localhost:9001` | `minioadmin` / `minioadmin` |

## Production

`.env` on the server:

```dotenv
ADMIN_EMAIL=admin@your-domain.org
ADMIN_PASSWORD=<own password>
ASKF_SECRETS_KEY=<long random string, set once, never change>
POSTGRES_PASSWORD=<own password>
S3_ENDPOINT=https://<your S3>
S3_ACCESS_KEY=<key>
S3_SECRET_KEY=<secret>
S3_BUCKET=<bucket>
```

HTTPS, pick one:

```dotenv
# 1. askFrancis gets the certificate itself, the domain must point to this server.
AUTO_HTTPS=true
DOMAIN=askfrancis.example.org
```

```dotenv
# 2. Your own proxy in front of askFrancis, forwarding to 127.0.0.1:3000.
AUTO_HTTPS=false
```

Start or update:

```bash
bash deploy/start.sh
```

## AI providers

The repository ships no API keys. Providers are added at runtime under **Admin → AI**, and every
feature is routed to a model there. Any OpenAI compatible endpoint works, for example Ollama at
`http://host.docker.internal:11434/v1`.

## License

Apache 2.0, Copyright 2026 Technische Hochschule Lübeck.
See [LICENSE](LICENSE), [NOTICE](NOTICE), [AUTHORS](AUTHORS) and [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt).
