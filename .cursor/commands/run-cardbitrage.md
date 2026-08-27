---
description: Run the Cardbitrage CK→TCG opportunities pipeline (fresh scrape, listings, enrich, load, HTML export).
---

# Run Cardbitrage pipeline

Run a full fresh Cardbitrage opportunities pipeline for this TCG repo. Do not wait for extra confirmation.

## Steps

1. **Ensure Docker is running.** If `docker info` fails, start Docker Desktop (`C:\Program Files\Docker\Docker\Docker Desktop.exe`) and wait until the daemon is ready (up to ~3 minutes). If it still is not ready, stop and tell the user.

2. **Start the pipeline in the repo root** with full permissions, in the background:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "pipeline\run_arbitrage_pipeline.ps1"
```

3. **Wait for completion.** Typical runtime is ~20–30 minutes (listings scrape is the long step). Poll until you see `CK arbitrage pipeline completed`, or failure (`failed with exit code`, `TCG mp-search listings failed`).

4. **If scrape_ck fails because Docker is down**, start Docker Desktop, wait until ready, and retry the same script once.

5. **On success**, report:
   - CK buylist row count
   - scrape candidate count
   - HTML path (`data/buylist/opportunities/cardbitrage_YYYY-MM-DD.html`)
   - opportunities loaded into Postgres
   - inventory CK refresh counts

Do not change pipeline code unless the user asked. Do not start a second pipeline if one is already running.
