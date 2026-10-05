# The shared review process

One diagram, shared by both hosts (owner R7). Nodes navigate; the rules live in `review-rules.md` and are referenced by
anchor. Host skills adapt invocation syntax only.

```mermaid
flowchart TD
  S[Scope and resolved roster — R-ROSTER] --> P[Prepare and preflight — R-PREPARE]
  P --> D[Native or wrapper dispatch — R-CONTAIN]
  D --> C[Collect terminal results — R-TERMINAL]
  C --> V[Validate identity and integrity — R-BIND]
  V --> L[Leader verifies findings — R-VERIFY]
  P -->|failure| X[Diagnose — the four rules below]
  D -->|failure| X
  C -->|failure| X
  V -->|failure| X
  X -->|unchanged inputs: failed leg only — R-RETRY| D
  X -->|preparation retry or changed basis| P
  L -->|in-scope correction: full roster again — R-REREVIEW| P
  L -->|design defect or unresolved conflict — R-STOP| O[Owner decision boundary]
  L -->|every selected leg explicitly approves current basis — R-AGREE| E[Record outcome and verify evidence export]
  L -->|no verifiable progress or resource limit: not agreed — R-STOP| E
  X -->|stop after diagnosis: not agreed| E
  O -->|retain evidence and stop| E
  E --> K[Clean eligible owned disposable resources — R-CLEANUP]
```

## Failure diagnosis — the same four rules at every step

<a id="R-DIAG"></a>

1. Check whether skill instructions, examples or interface discovery are ambiguous or incomplete before attributing a
   failure to a leader mistake.
2. Inspect the actual invocation and the deterministic implementation; distinguish an instruction or call defect, an
   infrastructure defect, a provider or transient failure, and an unconfirmed cause, using evidence. Decide whether a small
   code check or composition step prevents recurrence; do not create a framework by default.
3. Preserve and validate findings from the legs that succeeded, and do the in-scope correction work even if another leg
   failed to run. When an existing or approved design is shown defective, stop implementation, obtain independent
   read-only diagnosis from the other families, and brief the owner before changing that design.
4. After diagnosis, retry only the failed leg when source, prompts, criteria, roster, model, effort, route and review policy
   are unchanged (R-RETRY). Before dispatch exists, retry the corrected preparation step. Any correction to reviewed content
   or review conditions is a new bound basis and a complete full-scope review by the participating roster (R-REREVIEW);
   replacing a leg never relabels a failed round as approved.

Owner exceptions and stopped rounds retain their non-agreed machine outcome; only R-AGREE establishes agreement.
An item with no new evidence may stop while other verifiable corrections continue (R-STOP).

Failures keep their terminal evidence and an actionable next step. Repeated or conflicting findings that do not converge
go to leader analysis and the owner decision boundary (R-STOP), not to an automatic correction loop. Evidence export and
safe termination apply to failed and stopped work too; neither implies approval. Cleanup refuses when ownership, export
verification or a lifecycle precondition is unresolved (R-CLEANUP).
