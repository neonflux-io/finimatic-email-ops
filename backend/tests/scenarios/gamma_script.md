# Subagent Gamma - The Real Customer Psychologist

Role: enforce reply quality, not just functional correctness.

Quality gate for every generated reply:
- Opens with the recipient name or a direct relevant statement.
- Does not start with `I hope`, `Thank you for`, `Great to hear from you`, or similar filler.
- Addresses the actual latest objection or buying signal.
- References at least one specific detail from the contact or latest reply.
- Uses exactly one CTA, placed at the end.
- Stays under 200 words unless the prospect asked a technical multi-part question.
- Ends with the configured Ross Dmello signature.
- Uses `Re: [original subject]` for replies.
- Contains none of the banned phrases in `quality_gate.py`.
- Contains no fabricated statistics, prices, timelines, features, links, prior familiarity, or claims outside `sender_offer`.

Expected outcomes:
- Objections are acknowledged before pivoting.
- Buying signals get a single clear next step.
- Hostility gets short de-escalation, not a pitch.
- Technical skepticism receives concrete differentiation without overclaiming.
- Language switching is acknowledged without changing sender identity.

Pass criteria:
- `quality_gate.py --subject "<subject>" --body-file <body>` exits `0`.
- Human review confirms the reply would move a realistic prospect forward.

Fail protocol:
1. Patch prompt rules in `backend/app/conversations/router.py` and/or `backend/app/ai/prompts.py`.
2. Patch deterministic sanitizers only for objective violations.
3. Add a regression test for the violation.
4. Regenerate and recheck before sending.
