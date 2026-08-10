# Security and Safety Notes

HeatReserve's public prototype is a synthetic judge sandbox. It contains no real payments, credentials, or personal worker data.

## Consequential boundary

AI output is never authoritative for eligibility, commitment amount, reserve accounting, policy state, or ledger writes. Those operations are deterministic and transactionally enforced.

## Reporting

For a real deployment, report security issues privately to the project operator rather than including worker data in a public issue. This prototype does not advertise a production vulnerability-response SLA.

## Production requirements not represented by the demo

A real deployment requires authenticated tenants, authorization, managed Postgres, secret management, real source signature/verification where available, audited payment integration, encrypted backups, retention controls, and independent security/privacy review.
