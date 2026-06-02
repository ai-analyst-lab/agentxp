# Review — "Maya," the senior engineer who already built this

Reviewed: Module 10 ("The presentation layer"), against README, Module 4, and
Module 9. Standard: O'Reilly technical book — clear, economical, example-first,
no purple prose, no over-bolding for drama. Prior review covered Modules 0–8;
its single biggest finding was cross-module redundancy plus tell-don't-show tics.
This review applies the same lens to the newest module.

## Verdict

This is the best-built module in the curriculum, and it's the one I'd send a new
hire to first if I wanted them to *get* the system's spine in one sitting. The
content is right: the axiom is correctly identified as the whole design, the
pure/impure split is the true load-bearing decision and it's named as such, the
walkthrough traces real line numbers, and the labs are genuine break-its (tamper
the sidecar, watch six formats degrade; try to make an adapter lie and find the
type system won't let you). Lab F is a clean, well-scoped extension. The
back-references to Module 4 are mostly done *correctly* — pointing rather than
re-deriving — which is exactly the fix the last review asked for everywhere else.

But it has not learned the last review's lesson about its *own* internal
economy. The module restates its single axiom — "a renderer that does arithmetic
is a second source of truth in disguise" — at least six times in near-identical
prose, three of them inside the first 60 lines. It carries three `> **Aha —**`
callouts where one is load-bearing and the other two are restating the axiom in
a box. It over-bolds for drama in the Why section the way Module 4 did. And it
reintroduces the exact tell-don't-show tic the last review killed — "You just
proved the proof is welded to the polish" in Lab 10b is verbatim the "You just
proved tampering is detected" pattern that was the worst line in Module 4.

The two-spine ASCII map earns its space — it's the one place the reader sees
both spines meeting at `report.json`, and it's information, not decoration. Keep
it. The redundancy is all *prose*, not structure.

Net: ship it after cutting the intra-module axiom restatement from six to two,
collapsing the three Ahas to one, de-bolding the Why section, and deleting the
"you just proved" line. These are ~30 minutes of edits and they take the module
from a strong A− to the O'Reilly bar. This is the closest any module has come.

## Intra-module redundancy register

Unlike Modules 0–8, the redundancy here is mostly *within* Module 10, not across
modules — which means it's cheaper to fix and entirely the author's to own.

### R1 — The axiom ("a renderer that does arithmetic is a second source of truth")
Stated in full, or near-verbatim, **six** times — three within the first 60 lines:
- L33–38 — the first `> **Aha —**` ("report.json is the only source of truth …
  A renderer that does arithmetic is a second source of truth in disguise").
- L43–46 — consequence 1, "Numbers are formatted exactly once," restates it.
- L54–60 — the *second* `> **Aha —**` ("the split … is the load-bearing design
  decision") restates the pure-formatter half again.
- L123–125 — "Every other file is forbidden from formatting a number … that's
  the rule."
- L156–159 — "That's not laziness — it's the axiom encoded in the *type*."
- L479–483 — teach-back item 1 restates it in full a sixth time.
Plus README L108 (aha #8) states it canonically. The reader meets the same
sentence three times before reaching the walkthrough. State it once in the prose
(L33–38), let the *type* observation (L156–159) and the *lab* (10c) demonstrate
it, and cut the L43–46 and L123–125 restatements to a clause.

### R2 — The pure/impure split
Explained in full **four** times:
- L40–52 — the two numbered consequences.
- L54–60 — the second Aha, in full again ("Formatting must be pure … verification
  must be impure …").
- L62–66 — the "two surfaces" analogy paragraph touches it a third time.
- L484–487 — teach-back item 2, in full.
The numbered list (L40–52) is the right home and it's good. The L54–60 Aha is a
boxed restatement of the list immediately above it. Cut the box; the list already
made the point, and the README's aha #9 is the durable home for the one-liner.

### R3 — "Proof travels with polish, inseparably" / welded-together
- L47–52 — consequence 2.
- L60 — "what lets polish and proof both be true at once."
- L173–176 — the ViewBundle docstring quote (correct, load-bearing — keep).
- L384 — "You just proved the proof is welded to the polish" (the tell, see V1).
- L435–436 — Lab F step 2 ("Proof travels with polish, even in plain text").
- L486–487 — teach-back item 2.
README aha #9 is the canonical home. This is fine *as a motif* if each instance
is doing work; L60 and L384 are not — they're echoes.

### R4 — RenderStatus three-state explanation
This one is mostly *well* handled — it's explained once in the walkthrough
(L185–202), tied back to Module 4 by reference rather than re-derivation (good),
and the teach-back (L488–492) appropriately asks the reader to reproduce it. The
only trim: the L198–202 Aha restates the L185–194 bullet list's content ("any
'can't check' demotes … collapsing those two is how trust dashboards lie") right
after the bullets said it. Keep the bullets, cut the Aha to its first sentence or
fold it into the DRAFT/UNVERIFIABLE bullets. Do *not* re-explain RenderStatus
beyond this — the back-ref to Module 4 is exactly right.

### R5 — Lab F vs Module 9
**Not a duplication — and it correctly says so.** Lab F (L415–471) opens "This is
the Module-9 move applied to the presentation layer" and adds a *text* adapter,
where Module 9 Lab A adds a *warehouse* adapter to a different Protocol
(`BaseAdapter`, five methods, SQL layer) vs this layer's `FormatAdapter` (two
methods, render). The "predict the blast radius first" frame is deliberately
shared and named as shared. The closing lesson (L463–471) — "the breadth of the
work matches the breadth of the dependency" — is the *same proportion lesson* as
Module 9 Lab C's "breadth of the guardrail matches the breadth of the blast
radius" (09 L186). That's a reused theme, correctly attributed ("exactly the
proportion Module 9 taught"). This is how cross-module reference *should* look.
No cut needed; if anything it's the model the rest of the curriculum should copy.

## Voice tics (tell-don't-show + drama-bolding)

### V1 — "You just proved …" (L384) — the exact tic the last review killed
> You just proved the proof is welded to the polish — there is no format that
> shows the verdict while hiding the broken receipt.

This is verbatim the Module 4 L164 pattern ("You just proved tampering is
detected") that the prior review called the worst telling-not-showing line in the
course. The lab output *is* the proof: the reader just watched md stamp the
admonition, card strike the ribbon, json carry `draft_unverified`, and every
format exit 2. Let it stand. Rewrite to state the mechanism, not narrate the
reader's achievement: "No format can show the verdict while hiding the broken
receipt — the receipt and the number arrive in the same `ViewBundle`."

### V2 — Drama-bolding in the Why section
The Why section bolds for emphasis the way Module 4 did, and the prior review
flagged that pattern repo-wide:
- L19 "**once the answer exists, how do you show it …**" — bolding a rhetorical
  question.
- L26–28 "a lie that *looks* fine" — italic-for-drama.
- L51–52 "**both arrive in the same object.**" — bolded button.
- L33–38 and L54–60 — the Aha boxes are themselves fully bolded, which is double
  emphasis (boxed *and* bold). Reserve bold for terms-of-art on first use
  (`ReportVM`, `ViewBundle`, `distill()`, `RenderStatus`, `DRAFT_UNVERIFIED`),
  strip it from adjectives and rhetorical questions. An O'Reilly copyedit cuts
  ~50% of the bold here.

### V3 — Three Ahas where one is load-bearing
The module has three `> **Aha —**` callouts (L33, L54, L198) in the body plus two
more in the labs (L278, L291, L321 — that's *five* in the labs section). The
README's aha index (L93–109) already names the two canonical insights for this
module (#8 arithmetic-is-a-second-source, #9 polish-and-proof-same-object) and
says they're "marked inline with a `> **Aha —**` callout in the module where they
land." So the contract is *two* inline Ahas, matching the two index rows. The
module ships ~five. Either the index is wrong or the module over-marks. Keep the
two that match the index (the arithmetic one and a polish-and-proof one); demote
the rest to plain prose or a normal callout. An Aha that fires five times stops
being an Aha.

### V4 — Minor
- L139, L177 — "(Same discipline as `_sample_pct`.)" / "just forwards" — fine,
  economical.
- L308 "a PNG is a photograph of an HTML page that was itself a pure render of
  the VM" — good, earned, keep.
- L463 "the easiest extension in the system" — Module 9 L83 also calls its
  adapter "the easiest extension in the system." Two modules can't both own the
  superlative. Module 10 should say "as cheap as Module 9's adapter, for the same
  reason" rather than re-claim the title.

## Specific cuts (priority order)

1. **Delete the L54–60 second Aha box (R2).** It restates the numbered list
   directly above it. The list is the home. This is the single biggest prose cut.
2. **Cut the axiom from six statements to two (R1).** Keep L33–38 (first
   statement) and L156–159 (axiom-as-type). Reduce L43–46 to "formatted once by
   `distill()`" and L123–125 to "no adapter formats a number — Lab 10c proves it."
   Drop the teach-back's full re-statement to a pointer.
3. **Rewrite L384 to remove "You just proved …" (V1).** State the mechanism.
4. **Collapse the inline Ahas to the two the README index names (V3).** Demote
   L198–202 and the lab-section Ahas (L278, L291, L321) to plain callouts or prose.
5. **De-bold the Why section (V2).** Strip bold from L19, L51–52, and the bolded
   bodies of the Aha boxes; keep it on terms-of-art first-use only.
6. **Trim R4's L198–202 Aha to one sentence** (the bullets already carry it).
7. **Resolve the "easiest extension" superlative collision with Module 9 (V4).**
8. **Leave the two-spine map, Lab F, and the Module-4 back-refs alone.** They're
   the model. Don't touch them.
