# PGR KuroBBS Auto Sign-in

[中文](README.md)

Schedule PGR Daily Supply claims and KuroBBS check-in, browsing, liking, and sharing tasks with Docker Compose. Supports multiple accounts. Supply rewards are sent to each linked character's in-game mailbox.

Unofficial project, not affiliated with or endorsed by KURO GAMES. “Punishing: Gray Raven” and “KuroBBS” identify the supported services; trademarks belong to their respective owners.

## Setup

Requires Docker, Docker Compose, and a PGR character linked in the KuroBBS app.

Before use, check your account authorization and whether the platform permits automation. A working API does not imply permission. Automated check-ins, likes and reward claims may trigger anti-abuse measures or account restrictions. The GPL licenses this project's code, not platform access or trademark use.

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

## Email notifications (optional)

Enable IMAP/SMTP in QQ Mail settings and generate an authorization code. Copy `config/mail.example.json` to `config/mail.json`, set `enabled` to `true`, and fill in the sender, authorization code, and recipient (which can be yourself). Uses QQ Mail's encrypted SMTP; no mail server setup is needed.

Build the updated image and send a test email without running sign-in tasks:

```sh
docker compose build
docker compose run --rm pgr-sign python app.py --test-email
docker compose up -d
```

Each completed run sends one summary with every account's success or failure. Emails exclude Tokens and character details. Keep your authorization code private. Changes apply on the next run; set `enabled` to `false` to disable notifications. If the scheduled email does not arrive, check the service and email delivery; a stopped service cannot send alerts itself.

> For Tokens obtained from the app, set `source` to `ios` or `android`, matching the original request header. If the configuration cannot be read, check file permissions; the container user has UID `10001`.

Modified from [Kuro-autosignin](https://github.com/mxyooR/Kuro-autosignin), licensed under [GPL-3.0-only](LICENSE), without warranty. See [NOTICE](NOTICE) for attribution and modification details.
