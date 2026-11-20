# Operations Research (ledgerx_research)

Decision support connected to the other LedgerX apps. It reads live data (items, BOMs, stock, work orders, sales orders,
purchase requests, prices) and recommends decisions in six areas. Nothing is posted automatically: the "Create ... (draft)"
buttons make draft documents that a person reviews and submits.

| Plan | Question answered | Method | Draft |
|---|---|---|---|
| Product Mix Plan | What to make to maximise margin with limited materials and workstation hours | Linear / integer programming (HiGHS), shadow prices | Production Plan |
| Reorder Plan | When and how much to order | ABC, EOQ, safety stock, reorder point, back-tested forecast | Material Request |
| Distribution Plan | Cheapest way to move one item between warehouses | Transportation LP with dual certificate | Stock Entry (transfer) |
| Route Plan | Delivery routes by vehicle capacity | Savings heuristic + exact order for up to 12 stops, lower bound and gap | none |
| Schedule Plan | Order of operations of open work orders | Best of 5 dispatch rules, lower bound and gap | none |
| Supplier Allocation Plan | Split a purchase need across suppliers | Exact MILP (capacity, MOQ, share, lead time, quality, budget) | Purchase Orders |
| Break Even Analysis | Units and revenue to cover fixed costs, target profit, margin of safety, risk of a loss | Closed form + sensitivity + seeded Monte Carlo | none |
| Investment Analysis | Is a project worth it | NPV, IRR (all roots), payback, profitability index, NPV risk | none |
| Make or Buy / Lease or Buy | Cheaper option and the switching point | Cost curves, present value | none |
| Profitability / Pricing | Who makes or loses money, best price, cost of a discount, dead stock | Pareto classes, elasticity fit, price optimum checked by grid search | none |
| Decision Review | How right were earlier plans | WAPE, bias, tracking signal | none |

Product Mix Plan also has **What-if** (scenarios re-solved from scratch, ranges where a bottleneck or margin stays valid)
and **Risk Simulation** (re-optimised draws with a fixed seed).

## How correct is it?
* Every result is re-checked by separate code before it is flagged **verified**: constraints hold, and for linear problems an
  optimality certificate (complementary slackness) holds.
* Product mix, supplier allocation and shipping are solved exactly: optimal **for the data and the model**.
* Routes and scheduling are heuristics: the result shows a lower bound and the gap, it does not claim to be optimal.
* A model is a simplification and wrong input gives a wrong answer: the "Read before using" list shows what was assumed.
* The pure-logic part has 113 automated tests (textbook problems, brute-force and independent-oracle comparisons).
  Database reads and draft creation need a real site and are not covered by those tests.

## Requirements
numpy and scipy (`./env/bin/pip install numpy scipy`), erpnext. See `docs/INSTALL.md`.
