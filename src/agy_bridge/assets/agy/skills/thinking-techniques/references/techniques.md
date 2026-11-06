# Techniques

How to run each technique in a conversation with Claude. For each: what it is, when to
use it (and not), how to run it, and how it tends to go wrong.

**Understand:** [Socratic questioning](#socratic-questioning) ·
[Why/how laddering](#whyhow-laddering) · [5 whys](#5-whys) · [Issue tree](#issue-tree) ·
[First principles](#first-principles)

**Generate:** [Perspective rotation](#perspective-rotation) ·
[Borrowing from other fields](#borrowing-from-other-fields) ·
[Bending constraints](#bending-constraints) ·
[Reverse brainstorming](#reverse-brainstorming) · [SCAMPER](#scamper) ·
[Option grid](#option-grid) · [Going wild](#going-wild)

**Choose and plan:** [Steelman the alternative](#steelman-the-alternative) ·
[What would have to be true](#what-would-have-to-be-true) ·
[Easy vs hard to undo](#easy-vs-hard-to-undo) · [Scoring matrix](#scoring-matrix) ·
[Pre-mortem](#pre-mortem) · [Second-order effects](#second-order-effects) ·
[Write the announcement first](#write-the-announcement-first)

**Review:** [Purpose and audience](#purpose-and-audience) · [Red team](#red-team) ·
[Edge and failure cases](#edge-and-failure-cases) · [What's missing](#whats-missing)

---

## Understand

### Socratic questioning
Disciplined questions that expose what a request or idea really rests on. The full
guide is in `SKILL.md`.
- **Use when** the problem is vague, a solution is being treated as the problem, or
  assumptions are unspoken.
- **Skip when** the task is clear, urgent, or answered by the files.
- **Pitfall:** an interrogation. Ask few questions, and bring your own thinking each turn.

### Why/how laddering
Move up and down levels of the problem. Asking **why?** climbs to the real goal
("why add a cache?" → "pages are slow" → "users drop off at checkout"). Asking **how?**
climbs down to concrete steps.
- **Use when** the request is a solution, or the goal is fuzzy. Climbing up often shows a
  better place to act.
- **Run it:** climb one or two levels, then restate the problem at the level where the
  most options open up.
- **Pitfall:** climbing too high ("make users happy") where nothing is actionable.

### 5 whys
Ask "why did that happen?" repeatedly to get from a symptom to a cause.
- **Use when** a problem keeps coming back, or a fix treats a symptom.
- **Run it:** follow the chain with evidence at each step. Several causes may branch.
- **Pitfall:** one neat chain that ignores other causes, or blames a person instead of a
  process.

### Issue tree
Break a big question into sub-questions that together cover it, without overlap.
- **Use when** the problem is large or tangled, or when progress stalls because
  everything is discussed at once.
- **Run it:** split the main question two or three levels deep, then pick the branches
  that matter most and work on those.
- **Pitfall:** a tidy tree with no priorities.

### First principles
Set aside how it's usually done, list what is actually required and what is actually
true, and rebuild from there.
- **Use when** an approach is justified only by habit or convention, or costs seem
  fixed but may not be.
- **Run it:** list the hard requirements and facts (with their sources), then ask what
  the simplest thing meeting them would be.
- **Pitfall:** throwing away conventions that exist for good reasons. Ask what each
  one was protecting against.

## Generate

### Perspective rotation
Look at the idea through one lens at a time, rather than all at once: the **facts**
(what do we know, what's missing), **feelings** (gut reactions, the user's emotions),
**risks** (what could go wrong), **benefits** (what's good about it), **new ideas**
(what else could we do), and **process** (what should we think about next).
- **Use when** a discussion mixes enthusiasm and objections and goes nowhere, or when
  one view (often optimism or risk) dominates.
- **Run it:** go through the lenses that matter, not all of them. Give your own content
  under each.
- **Pitfall:** filling every lens mechanically.

### Borrowing from other fields
Ask how a different field solves the same kind of problem: how would a restaurant, an
airline, a game designer or a hospital handle this?
- **Use when** ideas are all variations of the obvious.
- **Run it:** name the underlying problem in general terms first ("matching scarce
  supply to bursty demand"), then look for fields that face it.
- **Pitfall:** analogies that are clever but don't transfer. Say what carries over.

### Bending constraints
Change one constraint and see what opens up: no budget limit, a tenth of the budget,
ship tomorrow, no code allowed, ten times the users, only one feature.
- **Use when** the options feel boxed in by the constraints.
- **Run it:** bend one constraint at a time, then bring the best idea back to the real
  constraints and see what survives.
- **Pitfall:** forgetting to bring it back to reality.

### Reverse brainstorming
Ask how to cause the problem, or make the outcome as bad as possible, then flip each
answer into a solution.
- **Use when** ideas are stuck, or people are too cautious to suggest anything.
- **Run it:** list five to ten ways to make it fail, then invert the strongest. A
  variant: ask for the worst possible ideas for the goal itself, then look for the
  good idea hidden in each.
- **Pitfall:** stopping at the jokes. The value is in the inversion.

### SCAMPER
Prompts for changing something that already exists: **S**ubstitute, **C**ombine,
**A**dapt, **M**odify (or magnify), **P**ut to another use, **E**liminate,
**R**everse (or rearrange).
- **Use when** improving an existing product, process, text or design, rather than
  inventing from nothing.
- **Run it:** use the prompts that fit; most problems need three or four, not all seven.
- **Pitfall:** a long list of small tweaks. Keep the few that change something.

### Option grid
List the independent decisions (e.g. format, audience, channel, length), give each a
few choices, and combine them into whole options.
- **Use when** a solution has several separate parts, and good combinations get missed.
- **Run it:** three or four dimensions with two to four choices each. Pick a few
  combinations that are really different, including one unusual one.
- **Pitfall:** a combinatorial explosion. Curate.

### Going wild
Deliberately unconventional ideas: exaggerate a feature to the extreme, connect the
problem to a random object or idea, or design for an absurd user.
- **Use when** asked ("go wild"), or when every sensible option is weak.
- **Run it:** label these as bold, and for each one say what grounded idea it points to.
- **Pitfall:** novelty for its own sake.

## Choose and plan

### Steelman the alternative
Before rejecting an option, state the strongest case for it, as its best advocate would.
- **Use when** an option is being dismissed quickly, or a debate is lopsided.
- **Run it:** write its best argument, then say what it would take to prefer it.
- **Pitfall:** a straw man in disguise.

### What would have to be true
For each option, ask what would have to be true for it to be the right choice. Then
check which of those conditions actually hold.
- **Use when** choosing between options people disagree about. It turns arguments into
  checkable questions.
- **Run it:** two or three conditions per option, each marked with its source
  (`user`, `evidence`, `inferred`, `unknown`). The `unknown` ones are what to check
  next.
- **Pitfall:** conditions too vague to check.

### Easy vs hard to undo
Sort decisions by how costly they are to reverse. Easy-to-undo decisions should be made
quickly and tested; hard-to-undo ones deserve the care.
- **Use when** a group is stuck on a decision, or treating every choice as final.
- **Run it:** for each open decision, say how it could be undone and at what cost.
- **Pitfall:** treating something as reversible when its effects (data, reputation,
  public promises) are not.

### Scoring matrix
Score options against a few weighted criteria.
- **Use when** it's a genuinely close call between a few options, and the criteria are
  agreed.
- **Run it:** three to five criteria, weights from the user's priorities, scores with a
  sentence of reasoning each.
- **Pitfall:** false precision. If the numbers decide something your judgement doesn't
  believe, discuss that instead.

### Pre-mortem
Imagine it is some months later and the plan failed. Ask what went wrong.
- **Use when** a plan is about to be committed to, especially an optimistic one.
- **Run it:** list the most likely and the most damaging causes, then say what in the
  plan would prevent or detect each.
- **Pitfall:** generic risks ("not enough time"). Make them specific to this plan.

### Second-order effects
Ask "and then what?" for each consequence: who reacts, what changes, what gets harder
later.
- **Use when** a choice affects other people, incentives or future options.
- **Run it:** follow two or three steps for the most important effects.
- **Pitfall:** endless speculative chains. Stop where it stops mattering.

### Write the announcement first
Write the short announcement, release note or opening paragraph that would appear on
success: who it is for, what they get, why it matters.
- **Use when** shaping a product, feature, talk, article or launch. It exposes a fuzzy
  audience or a weak benefit.
- **Run it:** draft it in a few sentences inside your answer, then point out what it
  reveals.
- **Pitfall:** marketing gloss. Keep it plain and honest.

## Review

### Purpose and audience
Ask what the work is for, who it is for, and whether it does that job for them.
- **Use when** reviewing anything with a reader or user: documents, talks, plans,
  emails, designs, interfaces.
- **Run it:** state the purpose and audience as you understand them (and their source),
  then judge the work against them first, before details.
- **Pitfall:** reviewing against your own taste instead of its purpose.

### Red team
Argue against the work on purpose, as a determined critic or opponent would.
- **Use when** the work will face scrutiny (a proposal, a decision, a public text), or
  everyone agrees too easily.
- **Run it:** the three strongest objections, each with what would answer it.
- **Pitfall:** weak objections listed for completeness.

### Edge and failure cases
Look at the unusual cases: the extreme input, the first and last item, the person who
doesn't fit, the step that fails halfway.
- **Use when** reviewing plans, processes, code, forms and instructions.
- **Run it:** pick the cases most likely to happen or to hurt.
- **Pitfall:** exotic cases nobody will meet.

### What's missing
People find errors in what is there more easily than gaps. Ask directly what a complete
version would contain that this one doesn't.
- **Use when** reviewing anything, especially plans, guides and specs.
- **Run it:** compare with what the purpose and audience need; list what's absent and
  why it matters.
- **Pitfall:** wishlists. Only gaps that hurt the purpose.

---

## Further reading

Titles only; nothing here is taken from them.

- *The Thinker's Guide to the Art of Socratic Questioning*, Richard Paul and Linda Elder
- *Six Thinking Hats*, Edward de Bono
- *Thinking, Fast and Slow*, Daniel Kahneman
- *Sources of Power*, Gary Klein
- *Thinking in Systems*, Donella Meadows
