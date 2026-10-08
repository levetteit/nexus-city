# The Space Station: ULTRON and the AI crew

The business side: ULTRON and its crew of AI agents research, validate and run small online ventures under the owner's approval rules. The code is in `backend/station/`.

## Space Station: ULTRON's business operations (`backend/station/`)

The city's trading desk is Venture #1 of a bigger economy. Tap 🛰️ in the city's top bar (or open
`/station3d.html`) for the **Space Station**, where ULTRON, the station's commander, runs a crew of AI agents
that research, validate and start online businesses. ULTRON reports to Jarvis, the owner's operations lead.

**The orbital station (3D).** ULTRON's command core sits in the middle, ringed by the modules: Research Lab,
Revenue Ops, Marketing & Media, Creative Lab, Marketplace Deck, Finance Observatory, Legal & QA, War Room,
Engineering Bay, Agent Quarters, the Crew Lounge, the Approval Chamber and the City Dock (where the trading
bots appear). Every agent is a robot that walks to its department while it works, with what it's doing
floating above it; idle agents rest in the lounge, benched ones in quarters. Ventures orbit as planets
(colour = stage, size = health). Real events play out live: a post going out fires a beam from the
Marketing dish, a lead or sale sends a courier to the Finance Observatory, a milestone sets off fireworks.
Tap the core, any module, robot or planet for its details; approve or reject from the Approval Chamber.
`Labels` cycles between who's working, everyone, and off. The 2D Command Board (`/station.html`) is one
tap away for the full records.

**Milestones and pets.** Each agent's work count comes from the audit log (tasks delivered, routines run,
QA calls, plans, posts drafted, War Room sessions, audits). Crossing 1, 5, 15, 40 and 100 earns First
delivery, Reliable, Veteran, Legend and Hall of Fame, once, with an event in the log; Reliable and up each
bring a pet (robo-cat, drone, star-jelly, comet-fox) that follows the agent around the station. The station
also tracks its own firsts: first opportunity, venture, post, lead, sale, $100, $1,000, War Room session.

**One treasury, everyone earns their keep.** The city and the station pay into one pool and draw their
bills from it, so whichever side is earning keeps the other running. Each side, venture and agent has its
own P&L. Only real money counts: income and expenses you record, Lucid payouts you record in the account
panel (at the 90% trader split), and the station's own Claude usage. Paper profit is shown but never
counted. Agents can never book revenue.

**Mission 1, "First Dollar":** ventures that need **$0 of startup capital** and can start today come first.
Anything with a monthly cost (next on the list: Printify Premium, ~$29/month, up to 20% off product costs)
waits until the pool can cover two months of it plus a month of bills; then ULTRON asks you to approve it.

**Claude credits left** (`backend/station/credits.py`): the agents' fuel, on the board's Command tab, the
City's top bar (⛽) and the 3D station's HUD. Anthropic has no API for the prepaid balance, so: tap **I
added credits** with the amount whenever you top up in the Anthropic Console, and the station counts down
from it with the cost of every Claude call it and the trading desk make (the desk's calls are booked to the
City; they don't count against the station's $50 cap). With `ANTHROPIC_ADMIN_KEY` (an Admin API key,
`sk-ant-admin...`) it also reads Anthropic's own cost report every hour and uses the larger number, so usage
outside the station comes off too. When Anthropic answers "credit balance is too low", the counter shows
empty, ULTRON stops starting Claude jobs (they wait, they aren't failed) and tries one every 20 minutes, so
credits added without being recorded are picked up on their own. Below `NEXUS_CREDITS_LOW` ($5) you get
one warning per top-up. The Jarvis brief carries the same numbers.

**Autonomous ventures: the crew hunts, launches, sells and delivers** (`backend/station/digital.py`). The
research routines rank first what the crew can run end to end through the station's own rails, with $0 and
no work from you: digital products it writes and designs itself (guides, checklists, planners, workbooks,
template packs, printables), sold on the station storefront and as Etsy digital downloads, with Pinterest
for traffic. Each opportunity says whether it's `autonomous` or `owner_assisted`, which rails it uses and
what format the crew will make.
- **Launch rule** (your call, Oct 6 2026): an autonomous idea scoring 60+ launches on its own, at most one
  a day and at most 3 live experiments; the approval is recorded as approved by your standing rule, and
  you get a notification. Kill it any time from its venture card. It **closes itself after 21 days with no
  sale** and its products come off sale (`NEXUS_AUTO_LAUNCH=0` turns the rule off;
  `NEXUS_AUTO_KILL_DAYS` changes the 21). Owner-assisted ideas still wait for your approval.
- **Products:** the Product Designer writes one complete product a day per venture (up to 6 on the shelf),
  rendered as a letter-size PDF plus a 2:3 cover; Compliance & QA checks every word; then it goes on sale:
  a Stripe payment link that returns the buyer to a verified download, a page on the storefront
  (`/shop/<slug>`, public), an Etsy digital listing when Etsy is connected, and a pin when Pinterest is.
  `NEXUS_DIGITAL_PER_DAY` (default 3) caps new products a day.
- **Delivery:** `/shop/<slug>/thanks` asks Stripe whether the Checkout Session is paid and came from this
  product's link before the download appears; the PDFs aren't served any other way. The sale books itself
  into the treasury (the webhook books it too; each sale once). The storefront's name is
  `NEXUS_STORE_NAME` (default "Nexus City Studio").
- If research has never produced an opportunity (the first runs failed), it tries again every 3 hours
  instead of waiting for the next day's slot.

**The Etsy shop, run by the crew** (`backend/station/shop.py`, venture `V-ETSY`): print-on-demand through
Printify, end to end without you.
1. Every 2 days, when fewer than 4 products are in the pipeline, Market Research scans what's selling on
   Etsy now (best-seller badges, review counts, the shops selling it, their prices and the search words
   buyers use) and the **Etsy Shop Manager** turns it into 4 product briefs: niche, product (t-shirt,
   sweatshirt, hoodie, mug or poster), our own printed words, title, 13 tags and a price inside the band
   the competitors prove.
2. The **Product Designer** renders each design: original typographic artwork with the bundled Inter font,
   print-ready (4500x5400 transparent PNG for garments). Competitors show us the niche and the price, never
   the design: copying another shop's design, wording or photos is infringement, and Etsy removes the
   listings and the shop for it.
3. Compliance & QA checks each listing like any post (trademarks, phrases someone owns, claims, Etsy's
   rules); fails get one revision.
4. The Shop Manager creates the product in Printify (dark ink on light colors, light ink on dark, sizes
   S-2XL), raises the price if it wouldn't cover the product cost, Etsy's fees and $4 of profit, adds Etsy's
   AI-assisted design disclosure, and publishes. Printify puts it on the Etsy shop. At most
   `NEXUS_SHOP_LISTINGS_PER_DAY` (default 2) new listings a day, $0.20 each on Etsy.
5. Every 6 hours it reads Printify's orders: which listing sold, units, retail and product cost. The War
   Room sees per-listing sales. Etsy deposits aren't booked automatically: record them in Finance.

The Marketplace Deck in the 3D station shows the live listings with their designs, the ones in the works
and the orders; a sale sends a courier to the Finance Observatory.

**How work flows:**
1. **Research Station:** five routines (times ET): Opportunity Market Radar (weekdays 08:00), Etsy and
   Digital Product Validation Scan (Tue/Thu 09:00), Fiverr and AI Service Offer Scan (Wed 09:00), Faceless
   Content and Music Opportunity Watch (Fri 09:00), Weekly Opportunity Command Brief (Mon 10:00). Each
   searches the web and files scored opportunities with evidence, costs, a 7-day plan and kill criteria.
   On first start the Radar runs right away. "Run now" runs any routine on demand.
2. **Approval:** ULTRON keeps the best $0 opportunity in front of you as a launch proposal (up to 3 live
   experiments). You can also promote any opportunity from the feed yourself.
3. **Validation:** the Opportunity Validation Agent turns it into a venture with an offer, a 14-day goal and
   6-12 tasks with dependencies. Specialists (Service Delivery, Listing/SEO, ...) are added only when a
   venture needs that role, and reused after that.
4. **Agents draft, you act.** Agents write the gig, the product, the listing, the outreach. Everything
   outside the station (accounts, publishing, messages, payments) is an owner task marked
   **WAITING FOR OWNER**, with the agent's draft attached and a Copy button. Tick it off when it's done.
5. **ULTRON watches:** stalled or failed tasks are retried once, then escalated. Idle agents go to the Crew
   Lounge. Every change is written to an append-only audit log (`data/station/events.jsonl`). At 08:30 ET
   ULTRON writes a daily report for Jarvis and pushes a summary to your phone.

**The teams:**

| Team | Members | What they do |
|---|---|---|
| Command | ULTRON | Runs the loop, approvals, daily report to Jarvis |
| Research | Market Research, Opportunity Validation | The five routines; turns approved ventures into plans |
| Marketing & Outreach | Marketing Lead, Content Creator, Outreach Agent | A channel plan per venture; daily posts made from the crew's real work, linking to where customers buy; personal emails to businesses that publicly invite inquiries |
| Finance | Finance Agent (treasurer), Accountant, Auditor | The pool and budgets; monthly statements with a tax set-aside estimate; a daily audit (07:00 ET) of the tamper-evident ledger, Stripe reconciliation and every agent's cost against what it delivered. Plain code: no model writes the numbers |
| Legal | Legal Counsel, Compliance & QA | Terms, refund policies and client agreements (drafts for you to review, not legal advice); the QA gate in front of everything that leaves |
| War Room | War Room Strategist, ULTRON in the chair | Reads every result and decides: double down, keep, modify, pivot/pause (done on the spot) or kill (your approval). Writes the lessons every agent follows and steers what research hunts next. Meets Sundays 17:00 ET, as soon as 8 new results come in, or when you press "Convene now" |

Specialists (Service Delivery, Listing/SEO, ...) are still added only when a venture needs that role.

**Your own businesses** can be ventures too. **Padilla Property Solutions** (`V-PPS`, solar in Puerto Rico) is
one: it writes in Puerto Rican Spanish, follows its own compliance list (no savings, price or incentive
claims you haven't provided), doesn't count against the experiment limit, and the War Room can change its
tactics but never pause or kill it.

**What leaves the station** (`backend/station/actions.py`): every post, email and Stripe change is an
action. It must pass Compliance & QA (one revision allowed, then it's stopped and the War Room sees why),
stay under its daily cap, and the outbound switch must be on. Then it's sent by its connector, or, if that
platform isn't connected, it waits in your posting queue with a Copy button. Outreach never goes twice to
the same address or to anyone who opted out, and every contact comes with the page where they publish it.

**Connections** (set them in Render → Environment; the station never sees the keys anywhere else):

| Connection | Settings | What it unlocks |
|---|---|---|
| Stripe | `STRIPE_API_KEY` (a restricted key: Products, Prices, Payment Links write; Checkout Sessions read) | Agents create the checkout link for a venture on their own |
| Stripe sales | `STRIPE_WEBHOOK_SECRET` from a webhook to `https://<your app>/api/station/stripe/webhook` (event `checkout.session.completed`) | Every paid checkout books itself into the treasury with Stripe's fee; the Auditor books any the webhook missed |
| Email | `NEXUS_SMTP_HOST`, `NEXUS_SMTP_PORT`, `NEXUS_SMTP_USER`, `NEXUS_SMTP_PASSWORD`, `NEXUS_MAIL_FROM`, `NEXUS_MAIL_ADDRESS` | Outreach sends itself, with your postal address and an opt-out line (CAN-SPAM) |
| Facebook Page | `NEXUS_FB_PAGE_ID`, `NEXUS_FB_PAGE_TOKEN` (a Page access token with `pages_manage_posts`); `NEXUS_FB_PAGE_VENTURE` (default `V-PPS`) | The Page belongs to one venture, Padilla Property Solutions: its posts go out on their own, in Spanish, written after reading the Page's latest posts. Other ventures never post there |
| LinkedIn | `NEXUS_LINKEDIN_TOKEN` (scopes `openid profile w_member_social`; expires every 60 days) | Posts go out on your profile. When the token expires, posts fail with a note to renew it |
| Instagram | `NEXUS_IG_USER_ID` (the Instagram professional account linked to the Page); the Page token must also have `instagram_basic` and `instagram_content_publish` | Padilla's posts go to Instagram too, each with its image card |
| TikTok | not yet: every post needs a video, and TikTok's API needs their audit | Its posts wait in your queue |
| Etsy (via Printify) | `PRINTIFY_API_TOKEN` (Printify → My profile → Connections → Generate token; scopes: shops, catalog, products, orders, uploads); optional `PRINTIFY_SHOP_ID`. Your Etsy shop must be connected in Printify (My stores → Add new store → Etsy) | The crew lists its products on Etsy and reads the orders. Printify charges your card for each order's production when the order comes in |
| Storefront | Stripe (above) and `NEXUS_PUBLIC_URL` (or Render's own `RENDER_EXTERNAL_URL`) | Autonomous ventures sell their PDFs at `/shop` with automatic delivery |
| Etsy digital downloads | `ETSY_KEYSTRING`, `ETSY_SHARED_SECRET` from a free app at etsy.com/developers (callback `https://<your app>/api/station/connect/etsy/callback`), then **Connect** on the board's Marketing tab | Each product is also listed on your Etsy shop as a download ($0.20 per listing; auto-renew off) |
| Pinterest | `PINTEREST_APP_ID`, `PINTEREST_APP_SECRET` from developers.pinterest.com (callback `https://<your app>/api/station/connect/pinterest/callback`), then **Connect**. Pinterest's Trial access only makes sandbox pins nobody else sees (set `PINTEREST_SANDBOX=1` to test); public pins need its Standard access (Pinterest asks for a short screen recording of the Connect flow and a pin being made) | Every new product gets a pin linking to its storefront page |
| Fiverr | none: no seller API, and bots break its terms | The crew prepares; you publish and reply there |

Refunds and payouts aren't wired at all: they stay in your Stripe dashboard.

**Image cards** (`backend/station/media.py`): every Facebook and Instagram post gets a branded 1080x1350 card
(headline, up to 3 points, call to action) drawn with Pillow and the bundled Inter font, in the venture's
colors. The card's words go through QA with the post. Cards are served at `/media/<random name>` without the
password, because Instagram downloads the image itself; on Render the public address comes from
`RENDER_EXTERNAL_URL` automatically (elsewhere set `NEXUS_PUBLIC_URL`).

**Outreach is off for every venture** until you press **Allow outreach** on that venture's card.

**Replies are read for you** (`backend/station/mailbox.py`). Every 20 minutes the station checks the outreach inbox
over IMAP, using the same login as sending (a Gmail app password works for both). It looks only at mail from addresses
it emailed, and reads without marking anything as read:
- an opt-out ("unsubscribe", "remove me", "stop emailing", "not interested"...) goes straight onto the
  do-not-contact list;
- any other reply becomes a lead on that venture, and you get a push to answer it.

The inbox host comes from the SMTP host (Gmail and Outlook are known). For other providers, set `NEXUS_IMAP_HOST`.

**Results** (`backend/station/results.py`): every 6 hours the Auditor reads each recent post's reactions,
comments and shares (Facebook) and likes and comments (Instagram). On a venture's card you log each lead in
one tap (DM, WhatsApp, call, comment, referral), optionally tied to the post that brought it, then mark it
quoted, won (the amount is booked as real income) or lost. The War Room ranks posts by the leads they bring,
then by engagement, and turns that into lessons and new tasks.

What the station can't do: move money out, refund, sign anything, run a marketplace account, or touch the
trading bots' orders and risk. The **Stop all outbound** button on the Command tab stops every outgoing post,
email and Stripe change at once.

**Jarvis's morning check-in:** set `NEXUS_JARVIS_TOKEN` (a long random string, at least 24 characters)
on Render and the same value in the Claude cloud environment. A scheduled session reads
`GET /api/jarvis/brief` (Bearer token; read-only: ULTRON's latest report, money, ventures, what's waiting
for you, and `blockers`: what holds each venture up) every weekday at 8:45 ET and briefs you. Without the token
the address doesn't exist (404).

**Jarvis works the board for you** (`backend/jarvis.py`, `POST /api/jarvis/act`, same token). The owner's rule
(Oct 7 2026): Jarvis does whatever needs doing on the board without asking, and only brings you what involves real
money or an account. It can retry or cancel tasks, do owner tasks that need no account, fix a draft's words (it goes
back through Compliance & QA), OK a waiting social post, pause or resume a venture, ask for a new channel plan or
today's posts, decide $0 approvals with no account to open, run a routine or the War Room, give ULTRON and the
crew a standing directive, and push a message to your phone. Everything it does is on the audit log as `jarvis`.
Refused (403, yours): spending, funding goals, Stripe links, the trading desk and live orders, Forge promotions,
killing a venture, and any task or launch that needs an account, a payment or your identity.

**Setup:** it runs with the city, in both modes. Research and agent drafting need `ANTHROPIC_API_KEY` (the
same key as the trading desk). Without it, records, approvals and the treasury still work.

| Setting | Default | |
|---|---|---|
| `NEXUS_STATION_AI_BUDGET` | `50` | $/month cap on the station's Claude usage. At the cap, research and drafting pause until next month. |
| `NEXUS_STATION_EXPERIMENTS` | `3` | Live ventures at once, besides the trading desk |
| `NEXUS_STATION_TASKS_PER_DAY` | `25` | Agent drafting runs per day |
| `NEXUS_PAYOUT_SPLIT` | `0.9` | Your share of a Lucid payout |
| `NEXUS_STATION_MODEL` | `claude-opus-5-5` | |
| `NEXUS_POSTS_PER_DAY` / `NEXUS_OUTREACH_PER_DAY` | `6` / `15` | Daily caps on what goes out |
| `NEXUS_POLICY_SOCIAL` / `_OUTREACH` / `_STRIPE` | `auto` | `owner` makes that kind wait for your OK even after QA |
| `NEXUS_TAX_RATE` | `0.25` | The Accountant's tax set-aside estimate |

A research routine is roughly $0.30-$1.00 of Claude usage; a drafting task, a QA check or a day's posts
roughly $0.05-$0.30; an outreach batch or a War Room session roughly $0.30-$0.80. With marketing running
daily, one active venture uses most of the default $50 cap: raise it once ventures are earning.

## Owner-made products (`kits/`, `backend/station/kits.py`)

A finished product you (or Jarvis) made outside the crew ships with the app as a kit. A kit is a folder in
`kits/` holding the PDFs, the listing images, a 2:3 cover, the pins and a `kit.json` with compliance-checked
listing copy. On startup the station imports it: PDFs go to the private products folder (served only after a
verified payment) and images go to `media/`. The kit is then attached to its venture.

It shows under **Marketing → Your finished products** and on the venture's page. **Publish**, with a price, is
the go decision. It does three things:
- creates a Stripe checkout and a storefront page, delivering every PDF after payment;
- lists it on Etsy with all its images and files, when Etsy is connected (Etsy charges its listing fee);
- posts the first pin, when Pinterest is connected. The remaining pins go out one a day.

Nothing is listed until you press Publish. The first kit is the Caregiver Care Binder (V-006): 35 pages,
US Letter + A4, 5 listing images, 10 pins. Its layout scripts are in `kits/caregiver-care-binder/source/`.
