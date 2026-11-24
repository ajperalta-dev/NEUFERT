# Vercel multi-service deployment

The Vercel project root is the repository root (`./`).

- `app` is public at `/`. Its runtime Next.js Route Handler forwards `/api/*` unchanged through `NEUFERT_PIPELINE_URL`.
- `pipeline` is an internal Python/FastAPI container. CPU PyTorch and the exact existing multilingual-e5-small model revision are installed during the container build.
- `state` is an internal Express service in `cloud-state/`. The pipeline calls it through `NEUFERT_STATE_URL`. It stores collections and manual review state in private Vercel Blob, using conditional ETag writes to prevent concurrent overwrites.

Vercel injects both bindings at runtime. Do not set their URL variables manually. No `NEXT_PUBLIC_*` variables contain service URLs or storage credentials. Browser calls remain same-origin `/api/...`; neither backend has a direct public rewrite.

## Data included in GitHub

Run `python -m pipeline.prepare_deployment` before updating the deployed book data. It creates `pipeline/deployment-data/` with all extracted images, prepared OCR/word coordinates, fichas, reports, a SHA-256 asset manifest, and a gzip-compressed consistent SQLite backup (including the committed WAL contents). Docker restores SQLite into writable instance-local storage and accesses the immutable assets from its image. The local `data/` directory stays ignored, along with `.env*`, model caches, temporary files, dependency folders and `.vercel/`. No API keys or logs are included in the deployment data.

Model weights are downloaded from the original upstream model at the revision in `deployment-data/model.json`, then used offline at runtime. The embedding model, dimensions and vector format are preserved. Local installation continues to use the existing Python ingestion requirements; the container uses `requirements-runtime.txt` plus CPU PyTorch.

## Durable user data

The private store `neufert-state` is linked to this project. Vercel injects `BLOB_READ_WRITE_TOKEN`; never commit it. Production, preview and development use separate state paths. Each mutable request loads current remote state, applies its operation, and saves only if the remote ETag still matches. A conflict returns 409; an unavailable state store returns 503. Failed writes are not reported as successful. On a new environment, state starts from the book snapshot until its first successful write.

This is a personal library: collections are shared within each deployment environment. The public API gateway does not implement per-user authentication.

## Checks and deployment

```powershell
node --test app/tests/services-proxy.test.mjs cloud-state/server.test.js
npm --prefix app run typecheck
npx vercel dev --local
npx vercel --prod --yes
```

The service orchestrator requires a Docker daemon to run the container locally. On ordinary local startup without service bindings, the API proxy uses `NEUFERT_API_URL` or `http://127.0.0.1:8000`. In Vercel it fails with 503 when its binding is absent, instead of attempting loopback.

References: https://vercel.com/docs/services , https://vercel.com/docs/services/bindings , https://vercel.com/docs/functions/runtimes/container .
