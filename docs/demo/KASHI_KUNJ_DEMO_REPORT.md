# Kashi Kunj Demo Pack — Final Delivery Report

Date: 2026-08-19 · Branch: `claude-development` (uncommitted) · No product code changed
Scope: client-meeting demo pack for **Sparkbuild Construction — Kashi Kunj** project
on the ICE platform. Everything below was verified against a running stack
(`docker compose up`), not assumed.

---

## A. Packaging & safety (1–4)

1. **Seed module exists and is self-contained**: `backend/app/demo/kashi_kunj.py`
   — `seed / verify / reset / reseed / smoke`. Zero edits to product code
   (`app/api`, `app/models`, `app/services`, `app/main`, frontend untouched).
2. **Safety guards hold**: module refuses to run when `ENVIRONMENT=production`;
   `seed`/`reseed` additionally require `ICE_KASHI_DEMO=true`; the demo password
   comes from `ICE_KASHI_DEMO_PASSWORD` and is never hard-coded in source.
3. **Idempotency proven**: `seed` run twice (and reseed after reset) creates no
   duplicates — all idempotency checks are keyed off the DB.
4. **Reset is scoped**: removes ONLY Kashi-owned rows (4 `kashi.*@example.com`
   users, the project and all children, named demo vendors). Direct-DB deletes
   are used because the product intentionally exposes no delete endpoints.
   Full `reset` → `reseed` cycle executed successfully.

## B. Seeded demo data (5–17)

5. **Bootstrap admin ensured** (Pankaj Sen / `Pankaj1234@gmail.com`) via a
   direct-DB write only when no admin exists — no product path bypassed at seed time.
6. **Four demo users** created: admin, site supervisor, procurement manager,
   client (`kashi.*@example.com`), each with the correct role.
7. **Project `PRJ-2026-0001` "Kashi Kunj"** — ACTIVE; start 2026-01-11,
   target end 2027-03-12; budget ₹90,00,000.
8. **Access control exercised**: supervisor and client assigned to the project;
   verify proves the client receives 403 on purchase orders, inventory, and
   billing milestones (`assert_can_view_project` working as designed).
9. **16 tasks** in a valid dependency chain — no cycle; FTS invariant
   `successor.start >= predecessor.end + 1` holds for every edge.
10. **Task dates engineered deliberately**: only "Internal Plaster" is planned
    early (day 196 vs predecessor end day 215), producing exactly **one**
    schedule-shift event instead of synthetic alert spam.
11. **8 daily site logs** (append-only module) with real-format entries.
12. **5 vendors** seeded (named demo vendors, clearly fictional in docs).
13. **10 inventory items**; immutable `stock_movements` ledger is the source of
    truth and `quantity_on_hand` running totals are consistent with it.
14. **5 purchase orders covering every lifecycle state**: received,
    partially_received, approved, pending_approval, rejected.
15. **Rejected PO carries a business reason** ("Rate above the approved Rs 450
    per can — please re-quote with Narmada or reduce quantity.").
16. **Movements ordered correctly**: PO receipts are recorded **before** manual
    consumption, so on-hand never goes negative and stock counts match the story.
17. **Financial storyline complete**: 6 manual job costs, 6 billing milestones
    (3 completed, 3 pending), 3 invoices (2 paid, 1 sent) issued through real
    milestone-completion → invoice-issue → mark-paid transitions.

## C. Verify results (18–28)

18. **`verify` = 42 checks, 42 PASS → "DEMO READY"** (exit 0).
19. Auth: login issues valid tokens; refresh session path works.
20. RBAC: supervisor/client see only assigned projects; admin/procurement see all.
21. Append-only: site logs and audit logs expose no update/delete endpoints.
22. **Financial auditability**: `budget_spent` (₹32,98,150) equals the job-cost
    ledger sum — the invariant the product guarantees.
23. Task FTS invariant validated programmatically for all dependencies.
24. Stock invariant validated: on-hand == ledger sum per item.
25. PO state machine: every transition used is one the API accepts.
26. Invoice lifecycle: draft → sent → paid transitions valid.
27. Health endpoint returns overall AMBER, timeline AMBER, budget GREEN with
    human-readable reasons.
28. No dependency cycle across the 16 tasks (verified via the task service).

## D. Demo narrative & health (29–30)

29. **Health story is discussion-worthy, not broken**: progress 47% vs 52% of
    schedule elapsed (SPI 0.91); 2 of 16 scheduled tasks overdue; 37% of budget
    spent vs 47% physical progress. Timeline AMBER / budget GREEN.
30. **48 notifications seeded** for a busy inbox:
    `po_submitted` 10, `po_approved` 9, `po_received` 9, `milestone_invoice_issued` 9,
    `task_schedule_shift` 3, `po_rejected` 3, `inventory_low_stock` 3,
    `project_assigned` 2. Only cement is low-stock (25 vs threshold 30) — a single,
    clean demo alert.

## E. Branding & deliverables (31–35)

31. **Sparkbuild branding captured** from the live site: logo
    `docs/demo/assets/sparkbuild-logo.png` (640×246 PNG), palette
    `#1A7EFB` / `#FFF200` / `#FF6900` / navy `#0F2A43`, and factual marketing
    claims (1000+ projects, 2 Lakh+ sq.ft., 9+ years, ISO certified).
    Site testimonial leftovers ("Brikly") deliberately **not** repeated.
32. **Reference doc** `docs/demo/KASHI_KUNJ_DEMO_REFERENCE.md` — every figure is
    the real seeded value (POs, invoices, items, health numbers); no invented data.
33. **Runbook** `docs/demo/KASHI_KUNJ_DEMO_RUNBOOK.md` — commands, env vars,
    demo password `Kashi@Demo26`, and failure fallbacks.
34. **Deck** `docs/demo/KASHI_KUNJ_STAKEHOLDER_PRESENTATION.pptx` — 15 slides,
    16:9, brand palette, logo on the title slide, speaker notes on all 15.
35. **Editable sources kept**: `KASHI_KUNJ_STAKEHOLDER_PRESENTATION.md` (15
    nontechnical slides) + `KASHI_KUNJ_PRESENTATION_NOTES.md` (speaker script,
    logistics checklist).

## F. Deck tooling (36–38)

36. PPTX is generated by `scripts/demo/generate_kashi_kunj_presentation.py`;
    `python-pptx==1.0.2` is pinned in a **separate** `scripts/demo/requirements.txt`
    and never enters backend/frontend dependencies.
37. Generated deck validated programmatically: 15 slides, 16:9
    (12192000×6858000 EMU), picture shape present on title, notes on every slide.
38. Demo password satisfies the platform policy (≥8 chars, uppercase, digit) and
    is documented only in the runbook.

## G. Copilot smoke (39–40)

39. **Read path works**: 5 prompts ("Tell me about Kashi Kunj", "Which tasks need
    attention?", "What is low in stock?", "Show open POs", "Management summary")
    each streamed real assistant replies over SSE (54–496 events per turn).
40. **HITL mutation smoke — inconclusive this run, not blocking**: the live model
    (gpt-oss-20b via groq) did not call the `create_task` tool, so no
    `approval_required` event fired. Mutations are enabled; the smoke now detects
    the approval event correctly (reads SSE `event:` frames) and would reject it
    so no rehearsal task is left behind. Nothing was created — demo stays pristine.

## H. Quality gates (41–43)

41. **Backend tests**: 462/462 pass when `ICE_AI_MUTATIONS_ENABLED=false`
    (CI-consistent). The 2 failures seen with mutations enabled
    (`test_assistant_api.py` asserting `read_only is True`) are env-dependent,
    pre-existing, and unrelated to this pack — all 7 assistant_api tests pass
    under the CI setting. Tests ran against throwaway `ice_test_db`; demo DB
    untouched.
42. **Static checks**: `ruff check app/demo/` — clean; `mypy` on the demo module —
    clean (pre-existing model-file errors are out of scope and not gated);
    `git diff --check` — clean; secret scan of `backend/app/demo`, `docs/demo`,
    `scripts/demo` — no key material, `.env` values, or private data found.
43. **Frontend**: `npm run build` OK (only a pre-existing chunk-size warning);
    `npm run lint` (oxlint) OK (1 pre-existing warning in `auth-context.tsx`).

## I. Open items & limitations (44)

44. **Open items / limitations**
    - Copilot **mutation** path (approve/reject of a proposed action) was not
      exercised end-to-end this run — live-model behavior; the smoke documents it.
    - `reset` performs direct-DB deletes by design (product has no delete APIs);
      it is scoped to Kashi-owned rows only and never truncates.
    - All people, vendors, and figures are **fictional demo data**, stated in the
      reference doc; nothing from `backend/.env` is in any deliverable.
    - Nothing has been committed or pushed — this pack awaits your review.

---

## Verdict

> **KASHI KUNJ DEMO PACK — READY FOR CLIENT MEETING.**
> Seed data is realistic and verified (42/42), the deck is branded and complete
> (15 slides + notes), documentation matches the live system, and all quality
> gates pass. The only not-fully-exercised surface is the Copilot mutation
> approval path, which is non-blocking and self-documented.