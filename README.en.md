# PGR KuroBBS Auto Sign-in

[中文](README.md)

Schedule PGR Daily Supply claims and KuroBBS check-in, browsing, liking, and sharing tasks with Docker Compose. Supports multiple accounts. Supply rewards are sent to each linked character's in-game mailbox.

## Setup

Requires Docker, Docker Compose, and a PGR character linked in the KuroBBS app.

1. Sign in to [KuroBBS](https://www.kurobbs.com/pns/home/). Open developer tools (F12), select Network, and refresh. Copy the `token` header from an authenticated request to `api.kurobbs.com`.
2. Copy `config/accounts.example.json` to `config/accounts.json` and enter your Token:

   ```json
   [
     {"name": "account1", "token": "YOUR_TOKEN", "source": "h5", "enabled": true}
   ]
   ```

   Add an object for each account, using unique names. Replace expired Tokens manually. Keep your account configuration private.

3. Start from the project directory and view logs:

   ```sh
   docker compose up -d --build
   docker compose logs -f --tail=100
   ```

Tasks run once at startup, then daily at **09:30 Asia/Shanghai**. Completed tasks are skipped.

## Schedule

Copy `.env.example` to `.env` and adjust as needed:

```dotenv
TZ=Asia/Shanghai
SIGN_TIME=09:30
RUN_ON_START=true
```

`SIGN_TIME` sets the daily execution time. Set `RUN_ON_START=false` to skip the startup run. Apply changes with `docker compose up -d`.

Stop the service: `docker compose down`.

> For Tokens obtained from the app, set `source` to `ios` or `android`, matching the original request header. If the configuration cannot be read, check file permissions; the container user has UID `10001`.

[GPL-3.0 license](LICENSE)
