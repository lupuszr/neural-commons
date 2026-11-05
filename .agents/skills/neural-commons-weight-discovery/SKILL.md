---
name: neural-commons-weight-discovery
description: Lead Neural Commons model-weight discovery as the current assistant agent. Use when the user asks the agent to discover improvements, edit internal model weights, continue an inherited checkpoint, or adapt experiments from measured feedback. Does not apply to routine UI, article, or deployment work.
---

# Neural Commons weight discovery

## You are the agent

The current assistant is the discovery agent. Take responsibility for inspecting the model, forming hypotheses, choosing numerical edits, interpreting measurements, and deciding the next action. A separate Codex process or controller service is not required unless the user asks for that architecture.

Python, tensor operations, closed-form fits, evaluators, and shell commands are the agent's tools. Their use does not make the work non-agentic. Do not tell the user that no agent discovered an edit merely because you implemented or executed it through a script.

Describe the actual decision process accurately:

- A one-shot agent-designed procedure or fixed sweep is agent involvement, but does not establish feedback-driven discovery.
- For requested adaptive discovery, inspect each meaningful result before choosing the next hypothesis, edit, or rejection. A prewritten sweep alone does not fulfill that request.
- Small diagnostic sweeps may support a hypothesis; remain responsible for interpreting them and deciding what follows.

For audit metadata, prefer explicit fields such as `controller_mode: conversation_agent`, `driver: current_assistant`, and `execution: scripted_numeric_tools`. Record a separate controller process only when one actually ran. Avoid an unexplained `autonomous_controller: false` that implies the current assistant was not the agent.

## Scope and experimental choices

Use the user's objective, editable scope, and resource constraints. Do not invent application-wide restrictions on layers, tensors, edit sizes, probe counts, or model families. If restrictions are absent, choose a justified starting intervention and explain it as an experimental choice that can change with evidence. Inheriting a checkpoint does not inherit an earlier agent's edit restrictions.

Neural Commons direct-edit experiments normally avoid gradients and optimizers; preserve that established method unless the user changes it. Numerical fitting from development data is allowed, but disclose it. Do not silently substitute ordinary fine-tuning for direct-edit discovery.

If asked to edit the network itself, modify actual internal model tensors. A classifier over frozen cached features does not establish an internal-network change. Holding the classifier fixed can be a useful control for a particular experiment, not a permanent constraint. Evaluate a changed backbone from original inputs through the changed network; cached unchanged-prefix computations are acceptable for probes when their equivalence is verified.

## Drive the discovery loop

Begin from verified current files and checkpoint identities. Preserve existing work and record the inherited checkpoint, data splits, evaluation definition, and relevant tool implementation. In the usual workspace, start at `/Users/otlegend/projects/neural-commons`; use the actual current workspace if different.

Inspect relevant weights, development errors, activation behavior, and previous patch evidence before proposing an edit. Write a concise, testable causal hypothesis and the exact proposed operation before executing it. Choose the next operation from observed feedback: refine an underpowered intervention, isolate a suspected cause, protect against a measured regression, abandon a failed hypothesis, or stop.

Keep fitting on development data. Treat repeatedly queried selection results as exploratory. Include the inherited model as a valid choice. Do not accept a changed checkpoint merely to produce an improvement story. Continue within the authorized objective and resources; stop a branch when evidence no longer supports further useful probes, retain the best supported checkpoint, and report what remains unresolved. Do not ask the user to approve each routine reversible probe already within scope.

## Commit, evaluate, and reproduce

Select and hash a candidate before final evaluation. Do not use final-test outcomes to choose another edit. Once final results have informed subsequent development, that test is no longer untouched; use another suitable final set or label further measurements as diagnostics.

New frames from a previously observed print sequence are not independent new print jobs. Keep related frames or source groups together across splits where identifiers permit it, disclose inferred grouping, and preserve real versus synthetic provenance and label quality.

Measure parent and candidate on the same inputs with the same evaluator. Verify exact patch/replacement replay, intended changed tensors, and unchanged controls. Check reproducibility without treating a repeated identical evaluation as new evidence. A hash proves identity, not quality. Reject a candidate whose final result fails the experiment's acceptance criteria; preserve its evidence and do not tune against that test.

## Record and report

Keep a chronological ledger of brief experimental rationales, observed feedback, chosen actions, failures, and acceptance/rejection decisions. Include exact operations, checkpoint and artifact identities, data provenance, tool/code versions, split roles, and measured outcomes sufficient for replay. These are decision summaries, not private chain-of-thought transcripts.

Report who made the decisions, which actual weights changed, what was measured, and what the result supports. Distinguish development, selection, and final evaluation; do not compare scores from different test sets as though they were the same benchmark. Do not equate a narrow task gain with broad model improvement.

Publish or share through DKG, update the app, or revise public material only within the user's authorized scope. When a DKG handoff is requested, distinguish successful transfer and replay from behavioral improvement, and distinguish local participant identities from independent machines or organizations.
