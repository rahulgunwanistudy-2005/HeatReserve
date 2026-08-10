# Evidence Dossier

## Research question
What evidence supports the claim that output-paid outdoor workers may know heat is dangerous yet remain unable to reduce exposure because adaptation costs income, and what should HeatReserve build from that insight?

## A. Causal evidence: gig workers + timely liquidity
### Source
Chen, Hossain & Sekhri, *Liquidity Constraints and Real-Time Adaptation to Extreme Heat: Evidence from Gig Workers*; working paper and 2026 Ideas for India research explainer.

### What was studied
- Randomized controlled trial among **276 gig delivery workers in Delhi and Gurugram**.
- Peak heat season: May–June 2025.
- All workers received advance heatwave warnings tied to India Meteorological Department forecasts.
- Treatment workers additionally received **₹200 digitally at the start of each forecasted heatwave episode**.

### Reported results relevant to product mechanism
During heatwave weeks, warning-only workers reportedly:
- worked 0.8 fewer days;
- worked 1.2 fewer hours/day;
- completed 9.2 fewer deliveries;
- reported increased headache and fatigue symptoms.

Treatment workers reportedly experienced smaller reductions:
- 0.28 fewer workdays;
- 3.6 fewer deliveries;
- fewer heat-related symptoms;
- more shifting away from the hottest afternoon hours;
- greater use of cooled rest locations.

### Product inference
The product opportunity is not simply to improve heat awareness. Timely liquidity can relax an economic constraint that prevents adaptation.

### Important caveat
This is **external research**, not a HeatReserve outcome. The product may cite it as evidence for the mechanism but must never claim the same effect size.

## B. Why not worker-paid heat insurance as the main product?
The same research reports low willingness to prepay for hypothetical heat insurance / guaranteed heatwave benefits, including among workers who experienced the cash transfer. The authors interpret this as consistent with tight liquidity constraints.

### Product decision
HeatReserve's default model is **sponsor-funded adaptation reserve**, not worker-paid insurance.

A future regulated insurer could use the operating layer, but the prototype should not pretend to be an insurance product or give legal/regulatory conclusions.

## C. Existing heat finance proves feasibility and constrains novelty claims
### WCS / SEWA / Climate Resilience for All / Swiss Re
Public sources describe a Women's Climate Shock and Insurance and Livelihoods initiative in India with parametric heat protection and cash support. Swiss Re reported that 92% of 50,000 enrolled at-risk workers received payments during 2024 heat triggers. CGAP describes a phase covering 50,000 women across 22 districts, with district-specific temperature thresholds and an additional cash support component.

### What this means for HeatReserve
**Do not claim:** “first heat-triggered payout,” “first heat insurance for informal workers,” or “nobody has done this.”

**Defensible novelty claim:** HeatReserve prototypes a transparent adaptation operating layer that combines:
- sponsor-funded reserve policy;
- official-warning episode construction;
- individualized tool-grounded adaptation planning;
- explicit separation of AI and financial authority;
- immutable evidence snapshots;
- cryptographically tamper-evident SHA-256 Decision Receipts;
- fixed-budget impact/fairness allocation;
- replayable evaluation.

## D. Occupational heat guidance shapes safety language
NIOSH states that occupational heat stress depends on environmental heat, metabolic heat, clothing/PPE and other factors. It recommends WBGT when possible; Heat Index is useful as a screening alternative, but neither weather number alone is sufficient to guarantee worker safety. Work-practice controls include rest, hydration and rescheduling work.

### Product decisions
- Never output “safe to work.”
- Say “lower-exposure time window” or “lower modeled heat burden.”
- Prefer official warnings for financial qualification.
- Use hourly weather primarily for relative planning.
- If WBGT-quality inputs are unavailable, label the simplified proxy.
- Always show limitations and emergency escalation guidance separate from schedule planning.

## E. SDG mapping
### SDG 8.8 — primary
UN target: protect labour rights and promote safe and secure working environments for all workers, including those in precarious employment.

HeatReserve contributes conceptually through worker heat-adaptation support, but a prototype does not directly change official occupational-injury indicators.

### SDG 13.1 — secondary
UN target: strengthen resilience and adaptive capacity to climate-related hazards and natural disasters.

HeatReserve operationalizes anticipatory adaptation at the worker/program level.

## F. Evidence hierarchy for the project
1. **Primary/official sources**: UN SDGs, IMD/DDMA, NIOSH/ILO, official competition materials.
2. **Research paper / research explainer**: causal trial.
3. **Program case studies**: Swiss Re/CGAP descriptions of implemented heat finance.
4. **HeatReserve measured evidence**: tests/benchmarks generated by the repository.
5. **HeatReserve simulations**: replayed hypothetical worker/fund outcomes.

Never let level 4 or 5 masquerade as levels 1–3.

## G. Sources
- OurPlanet.Rocks Devpost: https://ourplanetrocks.devpost.com/
- Gig-worker experiment explainer: https://www.ideasforindia.in/topics/environment/real-time-adaptation-to-heatwaves-among-urban-gig-workers
- SSRN working paper: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5985794
- Swiss Re WCS case: https://www.swissre.com/our-business/public-sector-solutions/insights/financial-solutions-for-women-workers-india.html
- CGAP SEWA case: https://www.cgap.org/research/publication/confronting-climate-and-health-nexus-lessons-self-employed-womens-association
- ILO Heat at Work: https://www.ilo.org/publications/heat-work-implications-safety-and-health
- NIOSH Heat Safety Tool: https://www.cdc.gov/niosh/heat-stress/communication-resources/app.html
- NIOSH Workplace Recommendations: https://www.cdc.gov/niosh/heat-stress/recommendations/
- UN SDG 8: https://sdgs.un.org/goals/goal8
- UN SDG 13: https://sdgs.un.org/goals/goal13
