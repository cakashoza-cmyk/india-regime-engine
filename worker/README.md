# Optional: Cloudflare Worker trigger for "Fetch latest"

Default path needs no server: the button opens a prefilled GitHub issue (`fetch:<state>|<city>|<ind>`), and
`.github/workflows/fetch-note-issue.yml` builds the note (owner/collaborators only, skips if the note is <6 h old).

Use this Worker only if you want one-tap fetch for people without GitHub access.

1. Cloudflare dashboard → Workers → Create → paste `fetch-worker.js`.
2. Create a KV namespace, bind it as `RL`.
3. Variables: `REPO=cakashoza-cmyk/india-regime-engine`, `ALLOW_ORIGIN=https://cakashoza-cmyk.github.io`.
4. Secret `GH_TOKEN`: fine-grained PAT, only this repo, permission Actions: Read and write. Never paste it in chat or the repo.
5. Put the Worker URL in `data/fetch_config.json` → `"worker_url": "https://<name>.<you>.workers.dev"`.

Limits: 1 fetch per pick per 6 h, 30 per day overall. Each note costs about 25 DeepSeek calls at most.
