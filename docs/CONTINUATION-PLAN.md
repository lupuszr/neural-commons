# Sequential improvement across controllers

Policy revision after the recorded run: at the user's request, the current
selection and final minimum accuracy improvement is **0.2 percentage points**
(`0.002` on the 0–1 accuracy scale). Other constraints remain unchanged.
The text below preserves the original pre-search plan; the recorded candidate
passes the revised policy as documented in CONTINUATION-RESULTS.md.

Preserve the recorded AG News checkpoint (M1) and its original base (M0). A second
controller must start from M1, inspect the exact M0-to-M1 numerical diff and prior
hypothesis/results, then propose M1-to-M2 edits. It must not restart from M0 or
receive new final-test examples. Controller A requested GPT-6 Astra; controller B
will request GPT-6.1 Sol through the existing Codex login, without fallback.

Use two fresh local DKG participants. A imports and reevaluates the frozen first
experiment, publishes it, and B independently reproduces it. Only B's verified
received artifact store supplies the inherited checkpoint, old weights, patch,
session and evaluation to the continuation preparation. The controller receives
an ancestry summary and a bounded `inspect_diff` tool with exact before/after
values. Diff and handoff hashes join the pre-search commitment and DKG evidence.

The next proposal's base checkpoint ID must equal the prior proposal's candidate
checkpoint ID. Preserve the parent's inference artifact mapping so evaluation
configuration changes do not silently create a different checkpoint identity.
The new DerivedVersion points to that parent. Carry the previous proposal, spec,
patch and evaluation as hash-bound evidence, with authentication checked at DKG
receipt. This establishes a chain of artifacts, not just prose about ancestry.

Keep the same news prompt, four-label edit scope, BF16 storage and sentiment guard.
Use the pinned AG News source, exclude exact text from all previous development,
selection and final sets, then use fixed seeds 20261108/9/10. Take 64/class training
examples for development (256), the next 128/class for selection (512), and 250/class
from the remaining official test examples for final (1,000). Apply the same <=220
prompt-token filter, never a score filter. All subsets and policies are frozen
before controller output. No new final metrics may influence candidate choice.

Allow 20 attempts, at least 12, and 32 rounds. Select by accuracy then NLL then ID,
requiring at least one percentage point improvement over M1, non-worsening news
NLL and no sentiment accuracy/NLL regression (1e-6 NLL tolerance). Final acceptance
requires >=70% accuracy and >=1 percentage point improvement over M1 on the same
new final set, plus the same mandatory guard. Report paired changes and uncertainty.
A successful run is not guaranteed. A rejected attempt remains part of the record.

B publishes its second proposal and A independently reproduces it. Both evaluations
must agree exactly, and the inherited checkpoint/patch chain must reconstruct
byte-for-byte. Report M0, M1 and M2 scores on the same new final set when available;
do not compare scores from different test sets as if they measured incremental gain.
All services stop at the end. This remains two participants on one physical host;
no public-chain finality, broad model improvement or cross-host proof is implied.

Supplementary diagnostic recorded before the second final test: after freezing and
testing M2, score it once on the previous round's 1,000-example news final set and
compare with the recorded M1 result. This previously exposed set is not independent
and cannot influence selection or further edits. Preserve any regression; do not
retroactively change the precommitted acceptance policy.
