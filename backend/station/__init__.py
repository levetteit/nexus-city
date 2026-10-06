"""The StarNet Space Station: ULTRON's business operations, run alongside the trading city.

store.py     durable records (ventures, agents, tasks, approvals, opportunities, missions, routines)
             and the append-only event log every change is written to
economy.py   the treasury: real money in and out (owner-confirmed only), AI usage, budgets, runway
research.py  the Research Station's five routines (Claude + web search), zero-capital mandate first
crew.py      the agent roster and the task runner (agents draft; anything external waits for the owner)
ultron.py    the overseer: schedules routines, watches tasks and money, decides, reports to Jarvis

Nothing in the station can place trades, change the trading bots' risk, spend money or act on an
outside account. Those stop at an approval marked WAITING FOR OWNER.
"""
