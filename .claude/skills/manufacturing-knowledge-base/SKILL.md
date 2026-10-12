---
name: manufacturing-knowledge-base
description: Record real Mujassam print jobs (material, machine, sliced weight/time, issues, fixes, results, permission) and turn permissioned ones into guides and case studies.
---

# manufacturing-knowledge-base

## Procedure
1. Fill `data/knowledge_base/print_jobs.template.csv` (one row per real job). publication_permission: none | internal_only | anonymised_public | public_with_photos.
2. `python -m geo import-jobs file.csv`.
3. Content may use only `registry.publishable_jobs(conn)`; never customer files, names or confidential geometry.
4. Measurements are observations of one job, not engineering specifications; phrase them that way.

## Output
Content opportunities: `[{job_ids, topic, question answered, evidence, permission}]`
