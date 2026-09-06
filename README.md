# UNG-TAX

Independent tax filing service for the UNG ecosystem.

Current build provides authenticated application wiring, return creation/read/calculation workflow, advanced-integration capability reporting, health endpoints, restricted CORS, and Railway startup configuration.

## Production safety
Live filing transmission is intentionally disabled until official tax-authority credentials, schemas and current jurisdiction/year rules are verified. Do not commit local databases, encryption keys or secrets.

## Next production integration
Migrate persistence to PostgreSQL, replace local auth with UNG-JANUS, publish lifecycle events through UNG-PULSAR, and enable authority connectors only after acceptance testing.
