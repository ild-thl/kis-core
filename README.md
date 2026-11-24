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
| KIS | `http://localhost:3000` | `admin` / `adminpw` |
| API docs | `http://localhost:8000/docs` | |
| Langfuse | `http://localhost:3001` | `admin@example.org` / `admin123` |
| Adminer | `http://localhost:8081` | PostgreSQL, server `postgres`, user `kis`, password `kis-local-dev` |
| MinIO | `http://localhost:9001` | `minioadmin` / `minioadmin` |

## Production

`.env` on the server:

```dotenv
ADMIN_EMAIL=admin@your-domain.org
ADMIN_PASSWORD=<own password>
KIS_SECRETS_KEY=<long random string, set once, never change>
POSTGRES_PASSWORD=<own password>
S3_ENDPOINT=https://<your S3>
S3_ACCESS_KEY=<key>
S3_SECRET_KEY=<secret>
S3_BUCKET=<bucket>
```

Plus one of the two ways to reach it over HTTPS, the login only works over HTTPS:

```dotenv
# Rented server: KIS runs Caddy, which fetches and renews the certificates itself.
PROXY=true
DOMAIN=kis.example.org
# Or behind the proxy of your data centre, which forwards to 127.0.0.1:3000 (default).
PROXY=false
```

Then start, and after every `git pull` restart:

```bash
bash deploy/start.sh            # also: restart, down
```

### Rented server (`PROXY=true`)

- An A record (and AAAA with IPv6) for every name in `DOMAIN` points to the server.
  Several names are separated by commas: `DOMAIN="example.org, www.example.org"`.
- Ports 80 and 443 are open (TCP, and UDP for 443), no other web server runs on the host.

### Behind your own proxy (`PROXY=false`)

What the data centre's proxy needs:

- Forward everything to `http://127.0.0.1:3000`, never straight to the backend.
- Pass on the `Host` header and set `X-Forwarded-Host`, `X-Forwarded-Proto` and `X-Forwarded-For`,
  otherwise uploads fail.
- Turn buffering off for responses, otherwise the chat answer arrives in one piece at the end.
- A body limit of 32 MB and a timeout of 60 s are enough, large files go to the bucket in parts.

### Both ways

- The bucket has to be reachable from outside, browsers upload large files straight to it
  in parts of 5 MB. A proxy in front of your own S3 (e.g. nginx before MinIO) has to accept
  requests of at least 5 MB, nginx allows only 1 MB without a setting.
- KIS adds the CORS rule for your domain to the bucket by itself, so the S3 key needs the
  right to change the bucket's CORS.
- The server needs internet access for AI providers, images and packages.

### Deploy button (optional)

The workflow **Deploy** in the Actions tab runs `deploy/deploy.sh` on the server: it checks free disk
and running jobs, pulls `main`, builds while the site keeps running, restarts the app and waits for
an answer with status 200. The repository on the server has to be on `main` and able to `git pull`.

1. Create a key pair only for this and add the public key to `~/.ssh/authorized_keys` of the
   server user, locked to the script:
   `command="/path/to/repo/deploy/deploy.sh",restrict ssh-ed25519 AAAA… deploy`
2. Under **Settings → Secrets and variables → Actions** of the repository:

| Name | Kind | Value |
|---|---|---|
| `DEPLOY_SSH_KEY` | secret | the private key |
| `DEPLOY_TARGET` | variable | `user@host` of the server |
| `DEPLOY_KNOWN_HOSTS` | variable | output of `ssh-keyscan host` |
| `DEPLOY_ACTORS` | variable | GitHub logins allowed to start it, comma separated without spaces |

Without `DEPLOY_TARGET` the workflow is skipped.

## Further settings

Everything below has a default and goes into `.env` only to change it.

| Setting | Default | Purpose |
|---|---|---|
| `ADMIN_USERNAME` | part of `ADMIN_EMAIL` before the @ | login name of the admin |
| `MODULES` | `aia,tools` | modules this installation runs, needs a restart, locally the workers of both start anyway |

## AI providers

The repository ships no API keys. Providers are added at runtime under **Admin → AI**, and every
feature is routed to a model there. Any OpenAI compatible endpoint works, for example Ollama at
`http://host.docker.internal:11434/v1`.

## License

Apache 2.0, Copyright 2026 Technische Hochschule Lübeck.
See [LICENSE](LICENSE), [NOTICE](NOTICE), [AUTHORS](AUTHORS) and [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt).
