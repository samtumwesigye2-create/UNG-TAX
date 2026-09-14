# URA-PROMET

**Public Revenue Operations, Management & Electronic Taxation**

URA-PROMET is the revenue and taxation platform in the UNG ecosystem. It provides authenticated tax-return creation/read/calculation workflows, effective-dated Uganda resident PAYE calculations, NSSF calculations, corporation-tax calculation, advanced-integration capability reporting, health endpoints, restricted CORS, and Railway startup configuration.

## Canonical identity

The operational and user-facing system name is **URA-PROMET**. Existing repository, API paths, environment-variable names, and deployment identifiers may remain unchanged where renaming them would break compatibility, but they are implementation details rather than the product identity.

## 2026 Uganda rules

Resident PAYE is effective-dated. Payroll dated 2026-07-01 or later uses the Income Tax (Amendment) Act, 2026 bands documented in `HANDOFF.md`; earlier payroll preserves the legacy schedule.

NSSF uses 5% employee + 10% employer contributions. Corporation tax currently uses 30% of chargeable income.

As of 2026-09-06, URA's PAYE webpage still displays the legacy pre-July-2026 schedule, so it must not be used to override the effective-dated 2026 amendment for payroll dated 2026-07-01 or later. See `HANDOFF.md` for source notes and the effective-date record.

## Production safety

Live filing transmission is intentionally disabled until official tax-authority credentials, schemas and current jurisdiction/year rules are verified. Non-resident 2026 PAYE is also intentionally disabled until separately verified. Do not commit local databases, encryption keys or secrets.

## Next production integration

Continue PostgreSQL-backed persistence, replace local auth with UNG-JANUS when integration is ready, publish lifecycle events through UNG-PULSAR, and enable authority connectors only after acceptance testing.
