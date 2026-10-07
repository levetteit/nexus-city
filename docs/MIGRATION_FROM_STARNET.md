# Migrating from StarNet to Nexus City

The project was called **StarNet** ("Starnet City") and is now **Nexus City**. The rename is
**backward-compatible**: a deployment configured under the old name keeps working with no changes. This page lists
what changed, what was deliberately kept, and how to finish the move when convenient.

**Do you need to do anything right away?** No. Every existing `STARNET_*` variable, session cookie, Stripe payment
link, TradingView alert and the live URL keep working.

---

## 1. What changed

| Area | Before | After |
|---|---|---|
| App name (page titles, home-screen app name, headers, notifications, Basic-auth realm, API title) | Starnet City / StarNet | **Nexus City** |
| AI agent prompts (trading desk, crew rules, research, War Room) | "StarNet Space Station", "Starnet City" | "Nexus City Space Station", "Nexus City" |
| Storefront name default (`STORE_NAME`) | "StarNet Studio" | "Nexus City Studio" (set `NEXUS_STORE_NAME` to choose your own) |
| Seeded trading venture `V-001` | "Starnet City Trading Desk" | "Nexus City Trading Desk" (renamed once at startup and written to the audit log as `venture.renamed`) |
| Environment variables | `STARNET_<NAME>` | `NEXUS_<NAME>` (the old names still work; see §2) |
| Stripe metadata written on new payment links | `starnet_venture`, `starnet_product` | `nexus_venture`, `nexus_product` (the webhook reads both) |
| Session cookie | `starnet_auth` | `nexus_auth` (the old cookie is still accepted, so no one is logged out) |
| Browser `sessionStorage` key for the intro | `starnet_intro` | `nexus_intro` (the full intro plays once more) |
| TradingView feed script | `tradingview/starnet_feed.pine`, indicator "Starnet feed" | `tradingview/nexus_city_feed.pine`, indicator "Nexus City feed" |
| Push notification tag, User-Agent strings, multipart boundary, push contact | `starnet…` | `nexus…` |

## 2. Environment variables: compatibility behaviour

All settings are read through `backend/env.py`:

```text
env("PASSWORD")  →  NEXUS_PASSWORD  if set
                 →  else STARNET_PASSWORD   (deprecated, still honoured)
                 →  else the default
```

- **`NEXUS_*` wins** when both names are set.
- At startup the app logs which deprecated `STARNET_*` names are still in use. It logs names only, never values:
  `settings: 3 deprecated STARNET_* name(s) still in use, rename to NEXUS_*: STARNET_FEED_SECRET, …`
- **Not renamed:** third-party names: `ANTHROPIC_API_KEY`, `ANTHROPIC_ADMIN_KEY`, `STRIPE_API_KEY`,
  `STRIPE_WEBHOOK_SECRET`, `PRINTIFY_API_TOKEN`, `PRINTIFY_SHOP_ID`, `ETSY_KEYSTRING`, `ETSY_SHARED_SECRET`,
  `PINTEREST_APP_ID`, `PINTEREST_APP_SECRET`, `PINTEREST_SANDBOX`, `RENDER_EXTERNAL_URL`, `PORT`.

### Deprecated names and their replacements

Each one is `STARNET_<NAME>` → `NEXUS_<NAME>`:

| Group | Names |
|---|---|
| Application | `MODE`, `DATA_DIR`, `TICK_SECONDS`, `PUBLIC_URL` |
| Authentication | `PASSWORD`, `JARVIS_TOKEN` |
| Trading | `FEED_SECRET`, `WEBHOOK_SECRET`, `TRADERSPOST_WEBHOOKS`, `DESK_MODEL`, `FUNDED_DAILY_GOAL`, `FUNDED_DAILY_CAP`, `FUNDED_DAILY_STOP`, `FUNDED_KEEP_ROOM`, `NEWS_BEFORE`, `NEWS_AFTER`, `NEWS_AFTER_FOMC`, `NEWS_FLATTEN`, `PAYOUT_SPLIT` |
| AI station | `STATION_MODEL`, `STATION_AI_BUDGET`, `STATION_EXPERIMENTS`, `STATION_TASKS_PER_DAY`, `AUTO_LAUNCH`, `AUTO_KILL_DAYS`, `CREDITS_LOW` |
| Outbound policy and caps | `POLICY_SOCIAL`, `POLICY_OUTREACH`, `POLICY_STRIPE`, `POLICY_SHOP`, `POLICY_DIGITAL`, `POSTS_PER_DAY`, `OUTREACH_PER_DAY`, `SHOP_LISTINGS_PER_DAY`, `DIGITAL_PER_DAY` |
| Email | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`, `MAIL_ADDRESS`, `IMAP_HOST` |
| Social | `FB_PAGE_ID`, `FB_PAGE_TOKEN`, `FB_PAGE_VENTURE`, `IG_USER_ID`, `LINKEDIN_TOKEN`, `LINKEDIN_PERSON`, `META_GRAPH_VERSION` |
| Commerce | `STORE_NAME`, `STORE_EMAIL`, `SHOP_RESEARCH_HOURS`, `SHOP_MIN_PROFIT_CENTS`, `DIGITAL_EVERY_HOURS`, `DIGITAL_MAX_PER_VENTURE`, `TAX_RATE` |
| Notifications | `NTFY_TOPIC`, `VAPID_PRIVATE_KEY`, `PUSH_CONTACT` |

The deprecated names will be removed in a future major change. Nothing removes them today.

## 3. Kept on purpose (do not rename)

| Identifier | Why it stays |
|---|---|
| Render service name `starnet-city` | It sets the public address `starnet-city….onrender.com`. That address is registered as the Etsy and Pinterest OAuth redirect URI, the Stripe webhook endpoint, the TradingView alert URLs, the web-push subscriptions and the installed home-screen app, and it appears in image links of posts already published. Renaming the service breaks all of them at once. To get a branded address, add a **custom domain** in Render instead (see §5). |
| Render disk name `starnet-data` | A different disk name gives a new, **empty** disk: accounts, trades, the station's records, the audit log and the ledger would all be gone. |
| `STARNET_*` keys in `render.yaml` and the `Dockerfile` | If the service is managed from `render.yaml`, renaming a `generateValue` key makes Render generate a **new** secret. Because `NEXUS_*` takes priority, the TradingView alerts that hold the old secret would stop working. A `NEXUS_*` value in the Dockerfile would likewise override a `STARNET_*` value set on the host. |
| The `starnet:` salt inside the session cookie value | Changing it logs every browser out. It will be replaced when the cookie is hardened (security phase). |
| Reading `starnet_venture` / `starnet_product` in the Stripe webhook | Payment links created before the rename keep sending them. |
| Your existing TradingView alerts | An alert keeps the copy of the script it was created with, so the renamed indicator changes nothing for running alerts. Only recreate an alert if you update the script. |

## 4. Migration instructions (optional, any time)

### Rename variables on Render, one at a time
1. In Render → the service → **Environment**, add `NEXUS_<NAME>` with **exactly the same value** as `STARNET_<NAME>`.
2. Save and wait for the redeploy. Do this while the bots are flat, because a redeploy closes open positions.
3. Check the startup log: the name should no longer appear in the "deprecated STARNET_* name(s)" line.
4. Delete `STARNET_<NAME>`.

> ⚠ **Secrets:** for `FEED_SECRET` and `WEBHOOK_SECRET`, copy the value; don't let Render generate a new one.
> TradingView alerts send the existing value.

### Local `.env` files
Rename `STARNET_` to `NEXUS_` in your local `.env`. Both names work, so this can be done at any time.

### Home-screen app
The installed app picks up the new name the next time it is reinstalled. Push subscriptions are unaffected.

## 5. Getting a Nexus City web address (optional)

Add a custom domain in Render (Settings → Custom Domains) and set `NEXUS_PUBLIC_URL` to it. Then update:
- the redirect URI at Etsy and at Pinterest (`<domain>/api/station/connect/{etsy|pinterest}/callback`);
- the Stripe webhook endpoint (`<domain>/api/station/stripe/webhook`);
- the TradingView alert webhook URLs (`<domain>/api/feed`, `<domain>/api/tradingview`);
- re-enable phone alerts once from the app.

Keep the `onrender.com` address working until all of these are moved.

## 6. Breaking changes

None for existing deployments. For developers:
- tests now set `NEXUS_*` names (`tests/test_env.py` covers the `STARNET_*` fallback, the legacy cookie, legacy
  Stripe metadata and the venture rename);
- the TradingView script file moved to `tradingview/nexus_city_feed.pine`.
