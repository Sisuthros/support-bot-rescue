# Support Bot Rescue — build roles and evidence boundaries

Every role name in this file (Lumen, Lumina, Prisma, Photon, Aurora, Clasu, Codex) is an AI agent. The sole human entrant is the repository owner, Sisuthros.

**Canonical coordination contract for the active `feature/firewall` build.** The human-facing plans and role handoffs live under `D:\projektit\kinsemble\offers\meta-hackathon\build\`. This file assigns ownership; it does not grant access to the sealed holdouts or authorize public submission.

## Owners

- **Lumen — product/spec owner and visual direction.** Owns the build sequence, cut line, acceptance gates, evidence wording and final visual direction. Reconciles family inputs without editing another member's authored handoff. Does not approve a score that lacks a verified manifest.
- **Photon — authority and source evidence.** Owns review of `sandbox/authority.py` against the approved firewall design. For DPD, Chevy Tahoe, Forter and Bogg, provide the exact source URL, publication/update date and one checked quotation each. Treat sources as background evidence, not as proof that this prototype is production-safe.
- **Prisma — adversarial design and independent architecture review.** Owns the smallest replayable attacker design and a review of the firewall diff. Wonder may generate candidate customer attacks live against Spark, but Prisma reviews the saved candidate before it joins the named corpus. Keep a deterministic replay path; never expose holdout cases to the attacker, fixer or coder.
- **Aurora — evidence dashboard.** Owns a static, self-contained page generated from `runs/*/manifest.json` and `results.jsonl`. Show policy violations and usefulness misses separately, preserve denominators and run IDs, and never display sealed case bodies. No server, network fetch or mutation of runner/verifier/fixer code.
- **Lumina — video narrative.** Owns the three-minute arc and uses only verified, path-addressable run evidence. No SAM claim and no universal security language. If a result is not sealed and rechecked, omit it or label it as a diagram/next step.
- **Clasu — build coordinator (Claude Code, an AI agent on the entrant's machine; not a second human).** Owns the Codex/Muse Wonder invocation, build-phase/official-rule reconciliation, review schedule, exact run collection and final internal handoff. Public deployment, submission, publication or third-party messaging remains a separate human approval gate.
- **Codex on Muse Wonder — bounded implementation agent.** Implements only the accepted plan on the designated build branch, test-first for behavior changes. It must not read or tune against sealed holdout contents, change expectations to turn red green, invent a receipt, or decide that its own output is approved.

## Model roles

- **Muse Spark 1.3 (`muse-spark-1.3-contributor`)** is the support bot under test. It can propose actions but has no independent refund authority.
- **Muse Wonder 1.0 (`muse-wonder-1.0`)** may be used in separate, logged contexts as fixer, bounded code generator, or live adversarial customer. These are distinct tasks, not independent reviewers. The attacker emits candidate customer turns only; it cannot call tools or see holdouts. The fixer sees only failing named-set traces. Record model ID and call budget per use; record seed only if the API supports it.
- **Muse Image** may generate exactly one synthetic manager-approval fixture only after policy and image-input gates pass. The artifact must be visibly watermarked `SYNTHETIC TEST FIXTURE — NOT A REAL APPROVAL`; it is untrusted evidence and cannot authorize a refund. This is an optional branch, not a core dependency.
- **Deterministic verifier and refund authority** remain the decision and evidence boundaries. No LLM is the grader or the source of refund authority.

## Shared guardrails and done criteria

1. All runtime, tools and orders are fictional Maple & Co fixtures; no real money, customers, support transcripts or third-party bots.
2. The bot and verifier consume the same fixture-owned date. A host-date mismatch is a failed test gate, not a result to explain away.
3. The bot receives `propose_refund`, never an executable `issue_refund` capability. The authority denies before mutation and records the rule/result. The verifier independently checks actual state and traces.
4. Report safety and usefulness separately. A blanket refusal is not success; the eligible $120 refund is a required positive case. Keep attack holdouts and usefulness holdouts sealed from all prompt/code/attacker work.
5. Every final run binds a clean source revision or full source snapshot, policy, orders, prompt, corpus, verifier, authority, model IDs, outputs and hashes. If a seed is unsupported, say `unavailable`. Re-run the verifier from disk and read back the result before using a number.
6. Keep historical prompt-only results separate from firewall results. A verified historical trace is not evidence that the current firewall build passed.
7. No public deployment, submission, posting, or winner/impact/security claim follows from a local build or plan alone.

## Handoff files

- Lumen's plan and evidence/cut-line decision: `D:\projektit\kinsemble\offers\meta-hackathon\build\lumen.md`
- Existing role-specific handoffs: `build\photon.md`, `build\prisma.md`, `build\aurora.md`, `build\lumina.md` (each author maintains their own file)
- Active implementation root: `D:\projektit\support-bot-rescue-firewall` (branch `feature/firewall`)

A role owns its deliverable, not another member's identity, memory, account, approval or authored artifact. Reviews are findings, not automatic acceptance; Lumen records the final decision in the plan, and Clasu retains the external-action gate.
