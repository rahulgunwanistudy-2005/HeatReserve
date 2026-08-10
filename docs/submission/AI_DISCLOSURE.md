# AI Disclosure

## Runtime AI
HeatReserve uses an AI model only for **constrained adaptation planning and explanation**.

The model receives typed JSON context containing:
- hourly condition facts from verified replay snapshots;
- worker schedule constraints;
- verified cooling locations only.

It returns a structured plan. A deterministic verifier rejects unsupported locations, invalid times, hard-constraint violations and prohibited safety claims. If the model is unavailable or invalid, the product uses a deterministic fallback planner.

### AI does not
- determine whether a heat episode qualifies;
- determine worker financial eligibility;
- set the commitment amount;
- mutate reserve balances;
- execute payments;
- make medical diagnoses;
- certify a time as safe.

## Build-time AI
The project may be developed with AI coding/review agents, including the models named by the team. Before submission, list the exact models/tools actually used and describe their roles truthfully, e.g. architecture review, coding assistance, test generation, copy review.

Do not claim a model was used if it was only planned.

## Prompt disclosure
Include the runtime planner prompt in the repository and link it from the README. Keep secrets/API keys out of prompts and repo.

## Measurable AI outcomes
Report only actual evaluation results, such as:
- structured-output parser/schema-gate results;
- hard-constraint violation rate;
- unsupported-location rate;
- burden-score change vs deterministic fallback;
- latency;
- fallback rate.
