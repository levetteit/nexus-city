# The City: the 3D world

What you see in the browser: the city, its weather, the bots' rooms and the station district. The code is in `frontend/` (vanilla ES modules and Three.js).

## The city

A live 3D "trading city": each Python bot is a **worker** living in its own
building and trading micro futures (**MNQ, MES, M2K**) with the **Andrew Macre
pointer strategy**. All workers share **one prop firm account** whose rules
(Lucid Trading, LucidFlex 50K by default) they're built to pass: first the
evaluation, then the funded stage. They watch every session from the 18:00 ET
open to the 16:45 ET flat deadline and take new entries in the **London,
NY AM and NY PM killzones**, aiming for **$600–$1,200 a day**. When a worker is in a trade its
building fires a light beam into the sky. When it closes a trade, gold coins (or
red ones) roll down its road to **The Vault** in the middle of town.

![city](city.png)

- **Click a building** to open that worker's card: strategy, open position, recent trades, and a button to send it home or put it back on shift.
- **Click the vault** for today's payroll.

## Market weather and skyline

The city's sky follows the market. Day and night follow the ET clock (dawn at 6, bright through the New York
session, golden hour at 4:30, night after 9). The weather follows volatility: the last 30 minutes of MNQ range
against the last day's — **storm** (lightning, heavy rain) at 1.8x or during a news hold, **rain** at 1.25x,
**fog** when the tape is dead (0.55x or less), clear otherwise. The chip next to the fuel gauge names it.
Each district's towers grow with its bot's best-ever profit (up to 1.8x at $16k), and the background skyline
grows with the account's profit. Preview any sky with `/?weather=storm&hour=13`.

## Streamer rooms

Tap any building to go inside: its bot is a little robot streamer at a desk,
with three monitors:

- **Chart**: its live 1m candles with the untapped FFVG/IFFVG zones it's
  watching, the current PROC box, its entry and the next-zone target.
- **P&L**: today, the open position, recent wins/losses, career earnings and
  progress to its next gadget.
- **Stream chat**: viewers reacting to every entry, add, win and loss.

Each bot has its own persona (handle, vibe, props and catchphrases in
`persona` in `config.py`) and shows how it feels: typing while it scans, a
"?" while it waits for MES to confirm, sweating in a losing trade, jumping with
arms up and coins flying on a win, hands on head under a rain cloud on a loss,
sunglasses when the day is locked in, slumped when the account stops it,
asleep when it's switched off. Its face is a little screen.

**The more a bot makes, the fancier its setup.** Gadgets unlock from its
best-ever lifetime earnings and are never taken back: RGB racing chair ($500),
4th monitor ($1k), hexagon LED wall ($2.5k), gold trophy + neon $ ($5k), wall
of screens ($10k), aquarium ($25k), gold-plated chassis ($50k), penthouse view
($100k). 💎 on a building's label shows how upgraded it is. In live mode,
lifetime earnings are saved in `data/paper_bots.json`.

![room](room.png)

## Skins and apparel (`frontend/skins.js`)

Every robot has its own look, in the city (standing in front of its building), in its streamer room and on
the space station: OG_Pointer in a backwards cap and chain, SixMinuteSage in a beanie and prayer beads,
SPX_Scout in glasses and a bow tie, SweepQueen with cat ears and neon shades, TheLookout in a visor and goggles;
ULTRON wears a commander's crest, QA a hard hat, the Auditor a monocle, and so on.

More apparel is **earned from real results and never taken back**:

| Trading bots (lifetime P&L high-water mark) | Station crew (milestones from the audit log) |
|---|---|
| $100 star pin · $1,000 gold shades · $5,000 gold chain + $ pendant · funded account: funded wings · $10,000 cape · $25,000 gold crown (and a gold chassis) · $50,000 gold jetpack | First delivery: star pin · Reliable: station scarf · Veteran: gold shades · Legend: cape · Hall of Fame: gold crown |

An earned item replaces the signature one in the same slot when it ranks higher. Tap **STATS** in a room (or
a crew member on the station) for its wardrobe: what it wears and what it can still earn.

## Payout shuttles (`frontend/shuttle.js`)

Real money in flies. The Space Station now hangs over the city (tap it to go aboard). When you record a Lucid
payout, a green shuttle lifts off from the vault and docks at the station's treasury; a store sale (Stripe,
Etsy) comes in as a gold shuttle. On the station the same flights run from the City Dock or the shop to the
Finance Observatory, whose panel keeps a shuttle log. Every flight is a ledger entry (`Treasury.flights()`):
costs and paper profit never fly. Preview with `?shuttle=payout` or `?shuttle=sale`.

## One world: the city and the station district (`frontend/world.js`)

Opening the app now starts with a title screen. **▶ PRESS START** flies the camera down from space into the world.
The Space Station's departments are buildings on a ring around the city, joined to it by roads: Research Lab,
Revenue Ops, Marketing & Media, Creative Lab, Marketplace Deck, Finance Observatory, Legal & QA, War Room,
Engineering Bay, Agent Quarters, Crew Lounge, Approval Chamber and City Dock.

The crew lives there. Every agent has a callsign, a handle, a vibe and lines of their own, set in `PERSONAS` in
`backend/station/crew.py`:

| | | | |
|---|---|---|---|
| ULTRON | SCOUT | VERA | LEDGER |
| HYPE | PIXEL | ECHO | TALLY |
| HAWK | BRIEF | GATE | GENERAL |
| MERCH | MUSE | | |

Each wears its skin and apparel from `skins.js`. Agents walk to their department's building when they have a task.
On their free time they roam the roads to the lounge, the park, the plaza or a friend's building, and say things
along the way.

Tap an agent for their card (job, status, what they're working on, milestones) and **🎥 enter their room**. It's
the same streamer room as the trading bots, with their current task and stats on the screens. Tap a building to
see who works there. Everything shown is live station data.

## Full-screen chart

In any bot's room, tap **CHART** to open a full-screen chart of what the bot sees:

- 1m, 3m, 6m or 15m candles, aligned to the clock
- The untapped FFVG and IFFVG zones (✓ marks a zone that has been tapped)
- The live PROC box
- Every pointer (small arrow) and PROC (big arrow) on the bot's timeframes
- The MES pointers that confirm entries, in the strip at the bottom
- Today's entries (yellow arrow), exits (✕ with P&L) and the open position with live P&L

Drag to scroll back, pinch or scroll to zoom, and double-tap to return to now.
The chart refreshes every 3 seconds.
