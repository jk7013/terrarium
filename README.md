# Terrarium

Terrarium is an independent retrieval runtime.

It is not a Jido-internal module. Jido is one API client that calls Terrarium for retrieval context. Other services should be able to integrate through the same API contract.

## Current Recovery Status

This repository candidate was reconstructed from the currently running Docker container:

```text
terrarium-app:/app
```

and supplemented with ingestion/debug scripts that only existed in the Jido runtime snapshot:

```text
pg_ingest_law_article.py
build_law_dev_small.py
run_retrieval_debug.py
```

Do not treat older runtime snapshots as canonical source. After this recovery, the intended flow is:

```text
git repo -> docker image build -> terrarium-app container
```

No production or local fix should be applied by editing the running container directly.

2026-07-08 operations update:

- `terrarium-app` is now running from this repository via `docker compose -p docker up -d --build`.
- `terrarium-pgvector` keeps the existing `docker_terrarium_pgdata` volume.
- Both app and database ports are bound to `127.0.0.1`.
- The previous runtime containers were preserved as `terrarium-app-runtime-backup-20260708` and `terrarium-pgvector-runtime-backup-20260708`.
- A pre-replacement database dump was saved under the Jido workspace backup directory.

## Local Setup

1. Copy `.env.example` to `.env`.
2. Fill secrets in `.env`.
3. Start the services.

```bash
docker compose up -d --build
```

The Dockerfile uses `requirements.lock.txt`, recovered from the running container with `pip freeze`.
Keep `requirements.txt` as the human-readable dependency intent, and update the lock file only after testing a rebuilt image.

The compose file intentionally uses the existing external Docker resources:

```text
network: docker_default
volume:  docker_terrarium_pgdata
```

This keeps Jido and Terrarium on the same local Docker network while preserving the existing Terrarium database.

Terrarium API:

```text
http://127.0.0.1:9000
```

The app exposes:

```text
GET  /
GET  /health
POST /api/retrieve
POST /api/query
GET  /api/models
```

## Jido Integration Boundary

Jido should call Terrarium only through HTTP APIs, primarily:

```text
POST /api/retrieve
```

Terrarium should not depend on Jido database tables or Jido workflow internals.

Current internal profile access still uses `X-Jido-Internal`. This should be renamed later to a client-neutral internal header, such as `X-Internal-Client`, after Jido is updated at the same time.

## Safety Notes

- Do not commit `.env`.
- Rotate any OpenAI key that was previously visible through Docker container env inspection.
- Bind local development API and DB ports to `127.0.0.1`, not `0.0.0.0`.
- Keep law-specific retrieval as a domain path, not as the identity of the whole service.
