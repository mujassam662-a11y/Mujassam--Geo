---
name: margin-aware-growth
description: Rank growth opportunities by contribution, not traffic, using verified order and cost data only.
---

# margin-aware-growth

## Inputs
Order export (`import-orders`), verified cost assumptions (table cost_assumptions; template data/cost_assumptions.template.json).

## Procedure
1. `analysis.margin_analysis(conn)`; if status is insufficient_data, report what is missing and stop.
2. Contribution = revenue − shipping pass-through − material − machine time − labour − payment fees − refunds/reprints (− acquisition if known).
3. Join with landing page/channel to find segments with valuable orders.

## Rules
Never invent costs; revenue is not profit; label assumptions.
