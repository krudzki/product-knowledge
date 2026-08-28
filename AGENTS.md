# Working in this repository

Rules from `deal-pipeline/AGENTS.md` apply: English code/docs, ponytail minimalism, store-independent core.

Additional rules here:
- Product identity lives here, not in scanners. Scanners produce observations; this package owns matching and estimates.
- Every non-trivial link is audited in `match_decisions` with basis/score/version.
- Estimates are materialized and versioned; raw observations are never overwritten by an estimate or AI prior.
