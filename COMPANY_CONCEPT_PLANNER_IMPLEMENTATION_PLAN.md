# Company + Concept Query Planner Implementation Plan

Date: 2026-02-10
Owner: GPT Researcher query planning pipeline

## 1. Problem Statement

Current query planning over-indexes on the company entity and under-covers the concept/industry behind the entity.

Observed causes:
- Prompt hard constraints push all queries to include the entity identifier.
- Grounding logic force-prefixes entity anchors onto queries that do not include them.
- Query budget prioritizes identity + competitor lanes with no guaranteed concept lane.

Impact:
- Weak industry context and framework coverage.
- Poorer quality diligence questions for investment workflows.

## 2. Target Behavior

For company-research tasks, planning should intentionally cover:
1. Subject lane: company identity, product, financing, team, traction.
2. Concept lane: industry structure, technology paradigm, regulation, value chain, substitutes.
3. Intersection lane: company-vs-industry fit, moat, timing, adoption risk, relative positioning.

Hard outcomes:
- At least one concept-only query survives final grounding.
- Final query set is lane-balanced instead of entity-only.
- Entity disambiguation remains strict for subject/intersection lanes.

## 3. Scope

In scope:
- Query planning refactor in `gpt_researcher/actions/query_processing.py`.
- Prompt changes in `gpt_researcher/prompts.py`.
- New planner config fields in `gpt_researcher/config/variables/base.py` and `gpt_researcher/config/variables/default.py`.
- Tests in `tests/test_query_processing.py` and `tests/test_prompts_entity_disambiguation.py`.

Out of scope:
- Report writer template redesign.
- Retriever implementation changes.
- UI changes.

## 4. Design Overview

Use a two-stage planner:

Stage A: Subject + concept analysis
- Input: user query, parent query, context, report type.
- Output:
  - normalized subject anchors (domains, aliases),
  - concept facets (industry terms, technology terms, business-model terms, risk themes),
  - inferred user intention category,
  - lane budget.

Stage B: Lane-based query generation
- Generate queries in structured JSON:
  - `subject_queries`
  - `concept_queries`
  - `intersection_queries`
- Apply lane-aware grounding:
  - subject/intersection: entity anchor constraints enabled,
  - concept: no forced entity prefix.

Final merge:
- Merge by lane priority and configured budget.
- Preserve dedupe and max-iteration limits.
- Guarantee minimum concept coverage.

Cost model:
- Stage A uses `fast_llm_model`.
- Stage B uses `strategic_llm_model` and replaces the current single planning call.
- Net: +1 fast call per planning step (vs. current 1 call). Documented to avoid surprise.

## 5. Data Model Changes

Add planner-internal structures in `gpt_researcher/actions/query_processing.py`:
- `QueryLane` enum: `subject`, `concept`, `intersection`.
- `PlannedQuery` typed dict:
  - `query: str`
  - `lane: str`
  - `rationale: str | None`
- `SubjectConceptAnalysis` typed dict:
  - `anchors`
  - `concept_terms`
  - `intention`
  - `lane_budget`

Note: keep structures local to query processing first; move to shared module only if reused elsewhere.

## 6. Configuration Changes

Add new config keys.

In `gpt_researcher/config/variables/base.py`:
- `DUAL_LANE_QUERY_PLANNER: bool`
- `QUERY_LANE_BUDGET: Dict[str, int]`  (percent-like weights)
- `MIN_CONCEPT_QUERIES: int`
- `MIN_INTERSECTION_QUERIES: int` (optional, default 0)
- `USE_LLM_RECOMMENDED_LANE_BUDGET: bool` (advisory vs. override)

In `gpt_researcher/config/variables/default.py`:
- `"DUAL_LANE_QUERY_PLANNER": True`
- `"QUERY_LANE_BUDGET": {"subject": 40, "concept": 40, "intersection": 20}`
- `"MIN_CONCEPT_QUERIES": 1`
- `"MIN_INTERSECTION_QUERIES": 0`
- `"USE_LLM_RECOMMENDED_LANE_BUDGET": false`

Backward compatibility:
- If keys are missing, fallback to current behavior and defaults.
- Note: config loader supports dict via JSON strings; ensure env overrides use JSON (e.g., `{"subject":40,"concept":40,"intersection":20}`).

## 7. Prompt Changes

### 7.1 Analysis prompt
Add new prompt method in `gpt_researcher/prompts.py`:
- `generate_subject_concept_analysis_prompt(...)`
- Output strict JSON with:
  - `intention`
  - `subject_summary`
  - `concept_terms` (grouped by facet)
- `recommended_lane_budget`

### 7.2 Lane query generation prompt
Add new prompt method:
- `generate_lane_search_queries_prompt(...)`
- Requires JSON output with three arrays:
  - `subject_queries`
  - `concept_queries`
  - `intersection_queries`

Prompt constraints:
- Concept lane must not require company alias/domain in every query.
- Subject and intersection must remain disambiguated and verification-oriented.

Budget precedence:
- Default: use config `QUERY_LANE_BUDGET`.
- If `USE_LLM_RECOMMENDED_LANE_BUDGET=true`, Stage A budget overrides config.
- LLM budget is clamped to min values and normalized before allocation.

## 8. Query Processing Refactor

Implement in `gpt_researcher/actions/query_processing.py`:

1. Add `analyze_subject_and_concepts(...)`
- Calls Stage A prompt.
- Parses and normalizes structured JSON.
- Falls back to heuristic concept extraction if parsing fails.
- Cache Stage A outputs keyed by `(query, parent_query, report_type)` similar to `_TRANSLATED_QUERY_CACHE`.

2. Add `generate_lane_queries(...)`
- Calls Stage B prompt.
- Parses arrays by lane and normalizes each query.

3. Add lane-aware grounding:
- `ground_generated_queries(...)` accepts lane metadata or new wrapper:
  - `ground_lane_queries(...)`
- Anchor prefix injection disabled for concept lane.
- Identity/competitor injection only for subject/intersection lanes.

4. Update `generate_sub_queries(...)`
- If `cfg.dual_lane_query_planner` is enabled:
  - run Stage A + Stage B + lane merge.
- Else:
  - run legacy path unchanged.

5. Merge policy
- Allocate slots by lane budget and `max_iterations` using a deterministic rounding algorithm.
- Enforce `MIN_CONCEPT_QUERIES` if `max_iterations >= 2`.
- Enforce `MIN_INTERSECTION_QUERIES` if `max_iterations >= 3` (optional).
- If lane is empty, reallocate to next lane in priority order (subject → concept → intersection).

Rounding algorithm (deterministic):
1) Compute raw quota = `budget * max_iterations / 100`.
2) Take floor for each lane.
3) Distribute remaining slots by highest fractional remainder.
4) Apply min constraints (concept/intersection). If min forces overflow, subtract from the largest lane.

## 9. Test Plan

### 9.1 Unit tests in `tests/test_query_processing.py`

Add tests for:
- concept lane query is preserved without forced entity prefix.
- subject lane query gets anchor when missing.
- lane budget merge with `max_iterations=3/5/8`.
- malformed alias spillover does not leak into anchor prefix.
- Stage A or Stage B parse failure falls back safely.
- non-English prompt still supports translation and lane planning.
- lane budget rounding algorithm for small `max_iterations` values (2/3/4/5).
- min concept/intersection enforcement behavior.

### 9.2 Prompt tests in `tests/test_prompts_entity_disambiguation.py`

Add assertions that:
- lane prompts mention concept/industry analysis.
- constraints differ by lane (not all lanes forced to include entity).

### 9.3 Regression tests

Add one end-to-end mock test:
- Input: company + website + diligence workflow.
- Expect output mix includes at least one concept-only query.
- Mock Stage A response shape:
  - `{"intention":"due_diligence","concept_terms":{"industry":["neuromorphic","ai hardware"],"regulation":["export controls"]},"recommended_lane_budget":{"subject":40,"concept":40,"intersection":20}}`
- Mock Stage B response shape:
  - `{"subject_queries":[...], "concept_queries":[...], "intersection_queries":[...]}`
- Also test alias keys: `company_queries` and `industry_queries` map to subject/concept.

## 10. Logging and Debuggability

Add planner debug logs in `query_processing.py`:
- detected intention,
- extracted concept facets,
- lane counts before and after grounding,
- final lane allocation.

Use DEBUG level; do not log secrets.

## 11. Rollout Strategy

Phase 1:
- Ship behind `DUAL_LANE_QUERY_PLANNER` flag.
- Keep legacy path default fallback.

Phase 2:
- Enable by default after test baseline passes on representative prompts.

Phase 3:
- Remove legacy branch only after stable metrics and no regressions.

UI note:
- New config keys may surface in any settings UI that auto-reflects config. If so, keep defaults hidden unless explicitly exposed.

## 12. Acceptance Criteria

Functional:
- For company research prompts, final query set includes at least one concept-only query.
- No malformed long anchor strings from field spillover (e.g., `公司名称 ... - 官网 ...`).
- Subject identity verification query remains present.

Quality:
- Tests added and passing for both lane behavior and regressions.
- No decrease in existing disambiguation safeguards.

## 13. Implementation Sequence

1. Add config keys and defaults.
2. Add new prompt methods for Stage A/Stage B.
3. Implement analysis and lane generation functions.
4. Implement lane-aware grounding and merge policy.
5. Wire into `generate_sub_queries` behind feature flag.
6. Add tests and update failing snapshots.
7. Run focused tests, then full relevant test suite.

## 14. Risks and Mitigations

Risk: LLM returns malformed JSON.
Mitigation: strict parser + resilient fallback to heuristic planning.

Risk: Too many generic industry queries.
Mitigation: intersection lane quota and quality filters.

Risk: Reduced entity precision.
Mitigation: keep strict entity disambiguation for subject/intersection lanes.

Risk: Token/cost increase.
Mitigation: use fast model for Stage A and compact JSON schema; allow disabling Stage A via config if cost-sensitive.
