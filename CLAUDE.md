# DataMate 2026 — Claude Code Project Instructions

## Project mission
Develop a competitive, reproducible agent for **Zalo AI Challenge 2026 — DataMate**. The agent answers Vietnamese natural-language questions over business CSV, Excel, and SQLite data, or correctly reports insufficient evidence. The team consists of **five developers, including one team lead**. Claude Code is an engineering assistant; the team lead approves the specification, architecture, work allocation, and final integration.

## Authoritative context
1. Read **`COMPETITION_BRIEF.md`** before proposing specifications, architecture, implementation plans, or evaluation changes. It contains the supplied competition requirements, scoring details, submission format, schedule, and a clearly identified supplement from the official Docker guide.
2. Treat the organizers' latest official rules and Docker guideline as higher priority if a verified discrepancy is discovered. Explicitly report any discrepancy; never silently rewrite a requirement.
3. At runtime, **the active split's `rulebook.md`, `calendar.csv`, and actual business files** determine business logic and schemas. Never hard-code the example rules or training data schemas as universal.
4. Differentiate **verified requirement**, **observed repository/data fact**, **assumption**, and **proposed engineering choice** in specifications and recommendations.

## Non-negotiable competition constraints
- Submitted inference must run **entirely offline**, without Claude, external APIs, downloads, or any network traffic. Claude and Claude Code may be used only during development and other permitted preparation activities.
- All inference models combined (LLMs, embedding models, rerankers, classifiers, including all MoE parameters) must total **at most 15 billion parameters**, even if loaded separately. Original model weights must have been publicly released **before 2026-10-26**, with licenses permitting their use. Verify, document, and count each model before selection.
- Do not train on public/private test data, collect test answers, hard-code answers, or key behavior to `question_id`/`business_id`. Do not add human-in-the-loop inference.
- Read `/data` as **read-only**. The submitted image must run `/code/predict.sh` without arguments and write `/result/submission.jsonl` and per-question logs under `/result/logs/`.
- Follow exact answer types and normalization rules. Distinguish `unanswerable` (data cannot support an answer) from `abstain` (agent declines to answer). The metric gives **+1 correct, 0 abstain, -1 wrong**.
- Plan for **six hours total** on **2 × RTX 5090 (32 GB each)**, **512 GB RAM**, with matching **CUDA 12.8+** support. The **uncompressed `docker save` image must be at most 100 GB**.
- Prioritize determinism and the organizers' reproducibility bound **`|PA(uploaded) - PA(rerun)| <= 0.03`**. Record factual, per-question inference logs including `id`, final `answer`, `elapsed_ms`, actual generated `thinking` or `null`, and executed `code`/`output` when applicable. Never fabricate logs.
- Respect the **2026-11-16 23:59 GMT+7** final solution deadline and subsequent frozen-solution private-test requirements.

## Engineering approach and decisions
- **Do not assume an architecture has already been approved.** Evaluate options using correctness, generalization to unseen business types, developer effort, measurable training-validation performance, runtime, model/license restrictions, and implementation risk.
- First inspect what is actually present: repository structure, data samples if available, rulebook, calendar, existing tests, and machine constraints. If files are absent, identify gaps instead of inventing their content.
- During **specification/planning requests, do not implement production code or modify unrelated files**. Produce inspectable documents with measurable acceptance criteria, explicit interfaces, dependencies, risks, and decisions requiring team-lead approval.
- For a five-person plan, propose clearly owned workstreams and nonoverlapping file/module ownership, while recording shared interface contracts, integration milestones, testing responsibilities, and a critical path. Do **not** preassign individual names or invent team capabilities.
- Make incremental, testable changes after plan approval. Prefer small changes reusing existing project conventions. Never claim a command, test, benchmark, or Docker run succeeded unless it actually ran; include the command and outcome.
- No destructive operations, credential exposure, external data uploads, unexpected dependency installation, or pushes/deployments without explicit authorization. Use branches and pull requests; let the lead approve changes affecting shared interfaces.

## Language and communication
- Write **all specifications, plans, reviews, task assignments, code comments, and developer-facing documentation in original, professional English**. Do not translate from Vietnamese drafts.
- Keep Vietnamese question strings, source data labels, accepted answer forms, and competition-specific terms exactly where needed for correctness. Never strip Vietnamese diacritics in the string-matching procedure.
- Be precise, candid, and concise. Cite relevant repo paths or competition-brief sections for design decisions. Surface unresolved questions and label hypotheses rather than hiding uncertainty.

## Claude Pro efficiency
- Keep work scoped: inspect relevant files before loading large directories; use short references to `COMPETITION_BRIEF.md` instead of repeatedly pasting the entire brief.
- Prefer a capable general-purpose coding model for bounded implementation tasks; reserve deeper reasoning and expensive subagent work for architecture, tricky bugs, and consequential reviews when available in the subscription.
- Avoid unnecessary parallel agents and repeated full-repository scans. Use fresh sessions for independent tasks and context compaction for long-running work. Track available quota and avoid accidental pay-as-you-go/API billing.
- Do not create large numbers of speculative project files. Generate the specification, plan, architecture, interface definitions, or issue list only when requested; the team lead decides which artifacts become official.
