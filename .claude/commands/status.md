# /project:status -- Agent Status Dashboard

Check the current state of all agents and pending work.

## Steps

1. Read `agents/STATUS.md` for context percentages
2. Read each agent's SHARED.md for open TODOs:
   - `agents/ui/SHARED.md`
   - `agents/rendering/SHARED.md`
   - `agents/reversing/SHARED.md`
3. Check git log for recent commits and which agents pushed
4. Summarize:
   - Each agent's context level and last activity
   - Open P0/P1/P2 issues per agent
   - Pending CL entries or boundary violations
   - Recommended next actions
