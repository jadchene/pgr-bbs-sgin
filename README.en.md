# Scheduled KuroBBS community tasks

[中文](README.md)

Use Docker Compose to complete daily tasks in the Punishing: Gray Raven community: check in, view 3 posts, like 5 posts, share, and query coins. Completed tasks are skipped and results are checked against server-side task status. Multiple accounts run sequentially.

## Configure accounts

1. Sign in manually at the [KuroBBS website](https://www.kurobbs.com/pns/home/).
2. Open your browser's developer tools, select Network, and refresh. Copy the `token` request header from an authenticated request to `api.kurobbs.com`. You can also use an existing valid Token.
3. Copy `config/accounts.example.json` to `config/accounts.json` and replace the Token:

```json
[
  {"name": "account1", "token": "YOUR_TOKEN", "enabled": true}
]
```

Add an object for each account and use unique names. Optionally copy `devcode` and `distinct_id` from request headers; otherwise stable identifiers are generated from the account name. Expired Tokens must be replaced manually. The service does not log in or disable accounts automatically. Account changes are loaded before each run.

Tokens are stored in the local configuration and mounted read-only. Do not share the file or screenshots. Account files are excluded from Git and image builds. On Linux, container UID `10001` must be able to read the file; for example, use owner `10001:10001` and mode `600`, with a directory that this user can traverse.

## Deploy with Docker Compose

Run from the project root with Docker Engine and Compose v2:

```sh
docker compose build
docker compose run --rm pgr-sign python app.py --check
docker compose up -d
docker compose logs -f --tail=100
```

`--check` validates account and schedule configuration without making network requests or checking Token validity. By default, tasks run once at startup and then daily at **09:30 Asia/Shanghai**. Failures go to container logs; no notifications are sent.

To change the schedule, copy `.env.example` to `.env`:

```dotenv
TZ=Asia/Shanghai
SIGN_TIME=09:30
RUN_ON_START=true
```

`SIGN_TIME` uses 24-hour `HH:MM`; `TZ` is an IANA timezone. `RUN_ON_START=false` waits for the next scheduled time without catching up on missed runs. Apply environment changes with `docker compose up -d`.

Stop the service:

```sh
docker compose down
```

For a manual run, stop the scheduler first to avoid overlapping tasks:

```sh
docker compose stop pgr-sign
docker compose run --rm pgr-sign python app.py --once
docker compose up -d
```

Network failures and incomplete tasks are retried up to 3 attempts per account, 10 seconds apart. Expired Tokens are not retried. A failed one-off run exits nonzero. Replace the Token when logs report expiry; rerun manually after other failures. Do not run multiple instances for the same account.

## Data access

Runtime requests are restricted to community endpoints at `https://api.kurobbs.com`. HTTP redirects and environment proxies are disabled; TLS certificate verification remains enabled. Logs omit Tokens, request headers, and raw responses. The container runs as non-root, exposes no ports, and uses a read-only filesystem and configuration mount.

## License

Derived from Kuro-autosignin, retaining its [GPL-3.0 license](LICENSE).
