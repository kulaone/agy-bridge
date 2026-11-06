# Principles for reviewing a design

Ten lenses. Pick the ones that matter for the design in front of you. Each has the
ideas behind it, questions to ask, and warning signs that something is off.

1. [Problem and drivers](#1-problem-and-drivers)
2. [Structure and boundaries](#2-structure-and-boundaries)
3. [Data](#3-data)
4. [Failure](#4-failure)
5. [Operations](#5-operations)
6. [Security and privacy](#6-security-and-privacy)
7. [Change over time](#7-change-over-time)
8. [Scale, performance and cost](#8-scale-performance-and-cost)
9. [People and teams](#9-people-and-teams)
10. [AI and LLM features](#10-ai-and-llm-features)

---

## 1. Problem and drivers

A design is only good or bad relative to what it must achieve. Settle that first.

**Ideas**
- **Quality attributes compete.** Availability, latency, consistency, cost,
  simplicity, security, ease of change: you can't maximise them all. A design should
  say which few it puts first.
- **Hard constraints vs preferences.** "Must run on-prem for a regulator" shapes
  everything; "we'd like Kubernetes" may not. Treat them differently.
- **Today's problem vs tomorrow's.** Design for the load and features you can see
  coming with evidence, not for every possible future.

**Ask**
- If you could guarantee only three qualities, which three, and why those?
- Which requirements are hard, and which are preferences? Who set them?
- What does success look like in numbers: users, requests, data size, latency,
  uptime, budget?
- What is explicitly out of scope?
- What happens if a key assumption turns out to be wrong?

**Warning signs**
- No goals, or goals that can't be checked ("scalable", "robust", "modern").
- Every quality marked as important.
- A solution described before the problem.
- Growth numbers missing, or orders of magnitude beyond any evidence.

## 2. Structure and boundaries

How the system is divided decides how hard it is to change, test and run.

**Ideas**
- **Boundaries follow change.** Put together what changes together and for the same
  reason; separate what changes for different reasons or at different speeds.
- **Dependencies point toward what's stable.** Business rules shouldn't depend on
  frameworks, databases or UIs; the details should depend on the rules. Volatile
  parts should depend on stable ones, not the other way around.
- **No cycles** between modules or services. A cycle turns two parts into one that
  can't be changed, tested or deployed alone.
- **High cohesion, low coupling.** A module should do one coherent job, and know as
  little as possible about the inside of others.
- **Start together, split with a reason.** A well-structured single deployable (a
  modular monolith) is cheaper to build and run than services. Split when parts truly
  need different scaling, release cycles, reliability or ownership.
- **Structure should show the domain.** A newcomer should see what the system does
  from its top-level parts, not just which framework it uses.

**Ask**
- What does each component own, and what is it not allowed to know?
- Which components must change together for a typical feature? Are they separate?
- Why separate services here, rather than modules in one deployable? What does the
  split buy, and what does the network between them cost?
- Which way do the dependencies point? Are there cycles?

**Warning signs**
- A "shared" or "common" module everything depends on and everyone changes.
- Services that must be deployed together, or share a database table.
- A feature that needs coordinated changes in many components.
- Layers that only pass calls through.
- A distributed design for a small team and modest load, with no stated reason.

## 3. Data

Data outlives code. Mistakes here are the hardest to undo.

**Ideas**
- **One source of truth** for each piece of data, with a clear owner. Copies are
  caches or projections, and the design says how they are kept up to date.
- **Choose consistency on purpose.** Strong consistency is simpler to reason about;
  eventual consistency buys availability and scale at the cost of stale reads and
  conflict handling. Say which applies where.
- **Operations should be safe to repeat** (idempotent) wherever messages can be
  delivered twice or requests retried, which in a distributed system is everywhere.
- **Schemas will change.** Plan how: additive changes, versioned formats, migrations
  that run while the old code is still live.
- **Know the access patterns** before choosing a store: read/write ratio, query
  shapes, size, growth, retention.

**Ask**
- For each important entity: where does it live, who may write it, and who reads
  copies of it?
- What happens if two writers update the same record at once?
- What happens if a message is processed twice, or not at all?
- How will the schema change next year without downtime?
- How long is data kept, and how is it deleted?

**Warning signs**
- Two services writing the same data.
- A distributed transaction or dual write (database + queue) with no plan for partial
  failure.
- "We'll add an index later" for a query on the main path.
- No retention or deletion story for data that grows forever.
- A new database technology chosen without an access pattern that needs it.

## 4. Failure

Every part will fail. The design decides whether a failure is a blip or an outage.

**Ideas**
- **Every remote call needs a timeout**, a decision about retries (with backoff and a
  limit), and a plan for when it still fails.
- **Contain the blast radius.** One slow dependency or bad tenant shouldn't take down
  everything: isolate pools, queues and limits.
- **Degrade gracefully.** Decide what the system still does when a dependency is
  down: serve cached data, queue work, turn off a feature.
- **Push back under overload.** Bounded queues, rate limits and load shedding beat
  falling over.
- **Plan for partial failure.** Half-finished multi-step operations need a way to
  finish, retry or roll back.

**Ask**
- What happens when each dependency is slow? Down? Returning errors?
- What is the worst single failure, and what does the user see?
- How does the system recover after an outage: does a backlog of retries make it
  worse?
- How is a half-done operation detected and repaired?

**Warning signs**
- Remote calls with no timeouts, or retries without limits or backoff.
- A long chain of synchronous calls where any link failing fails the whole request.
- A single component every request depends on, with no plan for its outage.
- "It won't fail" said about anything with a network in between.

## 5. Operations

A design that can't be deployed, observed and fixed at 3 a.m. isn't finished.

**Ideas**
- **Observability is designed in**: logs, metrics and traces that answer "is it
  working, and if not, where?", with alerts on what users feel.
- **Deploys should be routine and reversible**: small, frequent, with a quick
  rollback and a way to release gradually (feature flags, canaries).
- **Migrations run alongside live traffic**: expand, migrate, then contract; never a
  big-bang switch that can't be undone.
- **Configuration and secrets** are managed, not baked into builds.

**Ask**
- How will you know it's broken before users tell you?
- How do you roll back a bad release? How long does it take?
- How is the data migrated from the current system, and can it be reversed halfway?
- Who gets paged, and what will they have to work with?

**Warning signs**
- No mention of monitoring, or only of infrastructure metrics.
- A cut-over that has to happen all at once, with no way back.
- Manual steps in the deploy.
- A new piece of infrastructure nobody on the team has run before.

## 6. Security and privacy

Easier to design in than to bolt on.

**Ideas**
- **Know the trust boundaries**: where data crosses from less trusted to more trusted
  (users, partners, the internet, other teams' services). Validate and authenticate
  there.
- **Least privilege**: each component, person and token gets only the access it
  needs.
- **Secrets** are stored in a secret manager, rotated, and never logged.
- **Think like an attacker** briefly for each boundary: who could pretend to be
  someone else, tamper with data, deny having done something, read what they
  shouldn't, overload it, or gain more rights than intended?
- **Collect less personal data**, keep it for less time, and know where it all is.

**Ask**
- What are the entry points, and who can reach each one?
- How are callers authenticated and authorised, including service-to-service?
- What is the worst thing a compromised component could do?
- What personal or sensitive data is stored, where, for how long, and who can see it?
- Which regulations apply?

**Warning signs**
- "Internal network, so no auth needed."
- Broad shared credentials, or admin rights for convenience.
- Sensitive data in logs, URLs or analytics.
- No plan for deleting a user's data.

## 7. Change over time

The design will be wrong about something. Make that cheap.

**Ideas**
- **Know which decisions are hard to undo** (data models, public APIs, core
  technology, vendor lock-in) and spend your care there. Easy-to-undo decisions
  should be made quickly.
- **Keep options open** when it's cheap: defer a decision until you know more, if
  deferring costs little.
- **Contracts need versions.** Public APIs and event formats should change in a
  backward-compatible way, with a plan for retiring old versions.
- **Build vs buy**: build what makes you different; buy or use open source for the
  rest, and weigh the cost of depending on it.
- **Check the design keeps its promises**: automated checks (tests on dependencies,
  performance budgets in CI, architecture rules) stop it eroding.

**Ask**
- Which decisions here would be expensive to reverse? Are they made with enough
  evidence?
- What decision could be put off, and what would that cost?
- How will the API or event format change without breaking consumers?
- What does depending on this vendor or library commit you to?
- How will you notice if the structure starts to erode?

**Warning signs**
- A one-way decision made casually, or a two-way one debated for weeks.
- Clients that must all upgrade at once.
- A custom build of something a mature product already does well.
- Heavy indirection added "in case we change it later" with no likely change.

## 8. Scale, performance and cost

Rough numbers catch most problems before any code exists.

**Ideas**
- **Estimate.** Requests per second, data size, growth, peak vs average. Order of
  magnitude is enough to spot a design that can't work, or one built for ten times
  the need.
- **Set budgets** for the paths that matter: latency per request, per hop, per query.
- **Find the bottleneck.** There is always one; know where it is and how it moves as
  load grows.
- **Cost is a quality.** Estimate running cost, and how it grows with users and data.
- **Don't scale early.** Caches, sharding and queues add complexity; add them when
  the numbers call for it.

**Ask**
- What load is expected at launch, in a year, and at peak?
- What is the latency budget for the main user action, and where does it go?
- What is the first thing to break as load grows ten times?
- What will this cost per month, and per user?

**Warning signs**
- No numbers at all.
- A cache added to fix an unexplained slowness.
- An N+1 pattern across a network boundary.
- Costs that grow faster than usage, e.g. per-request calls to a paid API.

## 9. People and teams

Systems end up shaped like the teams that build them.

**Ideas**
- **Structure follows communication.** Boundaries that cut across team lines need
  constant coordination; boundaries that match teams let them work independently.
- **Fit the team's skills and size.** A design the team can't build, run or debug
  confidently is a risk, however elegant.
- **Watch the cognitive load.** Each team should be able to hold its part in its head.
- **Every component needs an owner** who will run it after launch.

**Ask**
- Which team owns each component? Does any component need several teams to change it?
- Has the team run this kind of technology before? Who will support it at night?
- How many new concepts or tools does this design ask the team to learn?

**Warning signs**
- A service per developer.
- A new language, database and platform introduced in one project.
- Components with no clear owner after launch.

## 10. AI and LLM features

Models are useful, slow, costly, and not always right. Design for that.

**Ideas**
- **Output varies.** The same input can give different answers. Design for checking,
  correcting or rejecting what the model returns, and keep a human in the loop where
  mistakes are costly.
- **Measure quality** with an evaluation set and regression checks, the way you would
  test code. "It looked good in the demo" isn't evidence.
- **Treat model input as untrusted.** Content from users, documents or the web can
  carry instructions (prompt injection). Limit what the model's output can trigger,
  and never let it widen its own permissions.
- **Plan for cost and latency**: tokens per request, caching, streaming, smaller
  models for easy cases.
- **Plan for the model failing**: timeouts, rate limits, provider outages, model
  versions changing behaviour. Know what the feature does without it.
- **Data**: know what is sent to the provider, whether it may be kept or used for
  training, and whether that's allowed.

**Ask**
- How will you know the model's answers are good enough, and stay good after a
  model update?
- What can a model's output cause to happen? Who checks it first?
- What happens if a document or user message contains instructions?
- What does one request cost, and what does it cost at expected volume?
- What does the user see if the model is down or slow?

**Warning signs**
- Model output passed straight to a shell, a database or another system.
- No evaluation set; quality judged by eye.
- An agent with broad tool access and no limits.
- Sensitive data sent to a provider without checking the terms.

---

## Further reading

For depth on these ideas, a few widely read books (titles only; nothing here is taken
from them):

- *Designing Data-Intensive Applications*, Martin Kleppmann
- *Fundamentals of Software Architecture*, Mark Richards and Neal Ford
- *Clean Architecture*, Robert C. Martin
- *Release It!*, Michael T. Nygard
- *Team Topologies*, Matthew Skelton and Manuel Pais
- *Building Evolutionary Architectures*, Neal Ford, Rebecca Parsons and Patrick Kua
