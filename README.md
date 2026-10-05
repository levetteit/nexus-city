# Starnet City

A live 3D "trading city": each Python bot is a **worker** living in its own
building and trading options on one underlying. When a worker is in a trade its
building fires a light beam into the sky. When it closes a trade, gold coins (or
red ones) roll down its road to **The Vault** in the middle of town.

![city](docs/city.png)

## Run it

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
# open http://localhost:8000
```

`STARNET_TICK_SECONDS=0.1 uvicorn backend.main:app` runs the market 10× faster.

- **Click a building** to open that worker's card: strategy, open position, recent trades, and a button to send it home or put it back on shift.
- **Click the vault** for today's payroll.

## How it's built

```
backend/
  market.py      simulated intraday prices (trend/chop regimes) + Black-Scholes 0DTE option pricing
  broker.py      PaperBroker: fills with spread + fees. Implement buy/sell/mark to go live
  bots/base.py   the worker lifecycle: scanning → in_trade → off_duty / stopped
  bots/strategies.py  EMA cross, VWAP trend, RSI dip/rip, range breakout
  config.py      who lives in the city + their risk limits
  engine.py      ticks the market and every bot, builds the snapshot
  main.py        FastAPI: WebSocket /ws, REST /api/state, /api/bots/{id}/{on|off}
frontend/
  city.js        Three.js scene: buildings, beams, halos, roads, coins, bloom, labels
```

### Worker rules (every bot)

| Rule | Default | Effect |
|---|---|---|
| Profit brake | per bot, e.g. $1,800 | stops trading for the day once it's up this much ("off duty") |
| Max daily loss | per bot, e.g. $700 | stops trading for the day ("sent home") |
| Take profit / stop loss | +35% / −20% of premium | exits the option |
| Time stop | 25 min | exits stale trades |
| End of day | 5 min before close | flattens everything |

### Add a worker

```python
# backend/bots/strategies.py
class MyBot(Bot):
    strategy_name = "my idea"
    def signal(self, u, market):
        return "call" if u.history[-1] > u.history[-10] else None

# backend/config.py
(MyBot, BotConfig(id="my-bot", name="MY BOT", underlying="SPY", district="LAB", color="#ff00aa")),
```

The city lays itself out automatically for however many workers you register.

## Going live (read this first)

Everything runs on **simulated prices with a paper broker**. To trade for real
you'd swap `Market` for a live data feed and `PaperBroker` for a broker API
(Alpaca, Tradier, IBKR all support options). Paper trade for a long time first:
0DTE options lose value fast, and the spread and fees count against every trade.
Run the simulation a few times and you'll see most of these simple strategies
lose money once those costs are in.
