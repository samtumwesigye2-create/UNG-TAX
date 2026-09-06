# UNG-TAX 2026 Rule Handoff

## Effective-dated resident PAYE

The service uses two resident PAYE schedules:

- Before 2026-07-01: legacy schedule currently displayed on the URA PAYE webpage.
- From 2026-07-01: Income Tax (Amendment) Act, 2026 schedule, effective from 1 July 2026.

Monthly resident bands from 2026-07-01:

- UGX 0–335,000: nil
- UGX 335,001–410,000: 20% of excess over UGX 335,000
- UGX 410,001–485,000: UGX 15,000 + 25% of excess over UGX 410,000
- UGX 485,001–10,000,000: UGX 33,750 + 30% of excess over UGX 485,000
- Above UGX 10,000,000: UGX 2,888,250 + 40% of excess over UGX 10,000,000

The 2026 amendment was assented to on 20 August 2026 but commences on 1 July 2026, so July/August payroll may require reconciliation.

## NSSF

Mandatory NSSF contribution used by the calculator:

- employee: 5% of gross monthly wage
- employer: 10% of gross monthly wage

## Corporation tax

The service currently uses a 30% corporation tax rate on chargeable income.

## Source notes

Verified 2026 references:

- Kampala Associated Advocates, “KAA TAX ALERT – Income Tax (Amendment) Act 2026”, published 24 Aug 2026: https://www.kaa.co.ug/kaa-tax-alert-income-tax-amendment-act-2026/
- NSSF Uganda membership guidance: https://www.nssfug.org/about-us/membership/
- Uganda Revenue Authority corporation tax guidance: https://ura.go.ug/en/corporation-tax/

Important warning: as of 2026-09-06, the URA PAYE webpage still displays the pre-July-2026 bands. It is retained only as the historical schedule source and must not override the effective-dated 2026 amendment for payroll dated 2026-07-01 or later: https://ura.go.ug/en/domestic-taxes/paye-rates/

## Safety / production status

- Live URA filing transmission remains disabled.
- Non-resident 2026 PAYE is intentionally disabled until separately verified.
- Do not commit `tax_filing.db`, `secret.key`, credentials, authority tokens, or encryption material.
- Future production work should move persistence to PostgreSQL, replace local auth with UNG-JANUS, publish lifecycle events through UNG-PULSAR, and enable authority connectors only after contract/credential acceptance testing.
