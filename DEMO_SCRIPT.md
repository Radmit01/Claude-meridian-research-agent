# 5-Minute Demo Video Script — Meridian Research Pack System

Target runtime: 4:45–5:00. Each section below has a suggested timestamp,
what to show on screen, and narration you can read almost verbatim. Practice
once with a timer before recording — trim the narration (not the screen
capture) first if you're running long.

Record your screen at 1080p+ with the terminal font large enough to read.
Do the live run (Section 3) in a terminal window you've already resized and
cleared, so viewers aren't watching you resize windows.

---

## 0. Before you hit record

- Make sure `output/Q1_Regulatory_and_Compliance_Exposure.md`,
  `output/Q2_Prior_Relationship.md`, and
  `output/Q3_Full_Pre_Engagement_Research_Pack.md` already exist from a
  recent successful run (you have all three).
- Have those three files open in an editor tab, ready to flip to.
- Have `src/coordinator.py` and `ARCHITECTURE.md`'s diagram open in another
  tab/pane for Section 2.
- Run `python check_env.py` once beforehand so you know auth is live and
  won't 401 mid-recording.
- Decide which question you'll run **live** on camera. Recommended: **Q1**
  (narrowest question — fastest end-to-end runtime, lowest risk of eating
  your 5 minutes waiting on a model call). Q2 and Q3 are shown as
  already-generated evidence of breadth, not re-run live.

---

## 1. Introduce the use case (~0:00–0:35)

**Screen:** Your face / title slide, or the repo's README.md top section.

**Narration:**

> "This is my submission for Use Case 2: a multi-agent research system.
> The scenario is pre-engagement research — before a consulting team starts
> work with a client, someone has to read everything available about them
> and produce a structured research pack: what we know, where sources
> disagree, and where we simply don't have evidence.
>
> I built that as an agentic pipeline against a fixed 28-document corpus
> about a fictional client, Meridian Financial Group — a mix of client
> documents, external press and regulatory material, and our own prior
> engagement records, as Word, Excel, and PDF files. The system answers
> three fixed research questions and, for each one, produces a research
> pack with four mandatory sections: Findings, Conflicts and
> Reconciliation, Coverage Gaps, and Sources Consulted — every claim cited
> back to an exact document and section."

---

## 2. Architecture, workflow, agents, and tools (~0:35–2:00)

**Screen:** `ARCHITECTURE.md`'s pipeline diagram, scrolled into view. Point
at each stage as you name it (cursor or screen annotation).

**Narration:**

> "The coordinator runs a fixed pipeline, not a freely-improvising agent —
> I made that choice deliberately: the brief's output shape is itself
> fixed, so there's nothing to gain from letting a model replan the steps
> at runtime, and a fixed pipeline is far easier to test and debug stage by
> stage.
>
> Six subagent roles run in sequence, with real work parallelized inside
> that sequence:
>
> First, **Triage** opens all 28 documents — cheaply, metadata only — and
> classifies each as readable, empty, or failed, plus a relevance score
> against the question. That happens up front for every document, every
> time, so the Sources Consulted table is always complete and honest, even
> when only a few documents end up deeply analyzed.
>
> Second, **Retrieval** picks the subset worth deep analysis for this
> specific question — broader for the full pack, narrower for a single
> targeted question.
>
> Third, **Document Analysis** is where the real reading happens — it runs
> in parallel, batched a handful of documents per call, and extracts
> structured findings with exact citations, never full raw text passed
> forward.
>
> Fourth, a dedicated **Conflict Detection** agent — a fifth role beyond
> the brief's minimum of four — because I read this corpus end to end
> during design and found it has a real embedded contradiction that only
> shows up when you cross-reference multiple sources. I didn't want that
> buried inside a general synthesis step.
>
> Fifth, **Synthesis** organizes findings into sections and derives
> Coverage Gaps. And sixth, **Recommendations** runs in parallel with
> Synthesis and turns the findings into forward-looking, cited engagement
> focus areas for the team — every recommendation has to trace back to a
> real citation, or it gets dropped rather than invented.
>
> The one deliberately *non*-agentic step is final rendering: the four
> mandatory sections are assembled by plain Python, not a seventh model
> call, specifically so the exact required format and citation syntax
> never depend on model unpredictability. A deterministic citation
> validator then fuzzy-matches every citation in the output against what
> was actually extracted from that document, so a fabricated or malformed
> citation gets caught before the pack is considered final.
>
> One infrastructure note: this organization doesn't issue plain API keys —
> every model call goes through an internal gateway authenticated with
> Microsoft Entra ID, which the SDK picks up through environment variables
> at process start."

---

## 3. Live end-to-end run (~2:00–4:00)

**Screen:** Terminal, ready to run. Then the generated output file.

**Narration (while the run starts):**

> "Let's run it for real. I'll ask the narrowest of the three required
> questions — Meridian's regulatory and compliance exposure — so we see
> the full pipeline end to end without a long wait."

**Action:** Run it live:

```bash
python run_q1.py
```

**Narration (while it runs — the console prints a numbered step per stage
with timing, so narrate over that):**

> "You can see it stepping through each stage — triage classifying all 28
> documents, retrieval narrowing down to the relevant subset, document
> analysis running in parallel batches, then conflict detection and
> synthesis. The pipeline also has retry and backoff logic built in,
> because these model calls run over a real network gateway and can be
> slow or time out — the system retries rather than failing the whole run
> on one transient error."

**When it finishes, open the generated markdown file.**

**Narration (scrolling through `output/Q1_...md`):**

> "Here's the result. Every finding cites an exact document ID and section
> — never a filename, never just a page number. [Scroll to Conflicts and
> Reconciliation.] This is the embedded conflict I mentioned: the board was
> told remediation is substantially complete, but an external press report
> says four findings are still open. The system doesn't pick a side — it
> explicitly says the evidence doesn't support declaring a winner, and
> explains why: one source is an internal assertion, the other is an
> unconfirmed press report, and nothing in the corpus independently
> validates either. [Scroll to Coverage Gaps.] And here's the error
> handling: this corpus has a document, PV-06, that's a perfectly valid
> Word file but contains no extractable text at all — the system reports
> that distinctly from a file that fails to open, because those mean
> different things for how much to trust the rest of the pack. [Scroll to
> Recommended Engagement Focus Areas, then Sources Consulted.] And every
> one of the 28 source documents is accounted for here, with its read
> status, whether it was used or not."

**Action:** Briefly flip to the already-generated Q2 and Q3 files.

**Narration:**

> "The same pipeline answers the other two required questions the same
> way — prior relationship history here in Q2, and the full pre-engagement
> pack in Q3, which pulls in a broader set of documents and produces a
> correspondingly longer set of findings and recommendations."

---

## 4. Decisions, robustness, responsible design, and limitations
(~4:00–4:50)

**Screen:** Your face, or `DECISIONS.md` scrolled to a couple of the
numbered entries.

**Narration:**

> "A few decisions I want to call out. Citation checking is done by
> deterministic code, not another model call — I didn't want to ask an LLM
> to grade another LLM's citations, since that just adds a second place for
> hallucination to creep in. Conflicts are required to state a resolution
> basis even when that basis is 'unresolved' — the schema structurally
> prevents the system from quietly reporting 'no conflicts found' just
> because the evidence is messy. And failure handling distinguishes three
> different reasons a document might not contribute evidence — couldn't be
> opened, opened but empty, or opened but with content deliberately
> withheld — because the brief asks Coverage Gaps to say specifically why,
> not just that something's missing.
>
> For robustness, every stage's expected JSON shape is spelled out
> explicitly in that agent's prompt, with a defensive parser behind it that
> strips stray formatting the model might add anyway, so a single
> malformed response doesn't take down the whole run.
>
> Known limitations: relevance scoring in triage is model judgment, not a
> vector search — fine at 28 documents, wouldn't scale to a much larger
> corpus. And citation validation confirms a cited section genuinely
> exists in that document — it doesn't yet verify the claim's wording is
> truly supported by that section's content, which would need a further
> semantic check I've scoped as a next step rather than implemented here."

---

## 5. Close (~4:50–5:00)

**Narration:**

> "That's the system — a fixed six-role pipeline over a real 28-document
> corpus, with deterministic rendering and citation validation to keep the
> output format trustworthy, and explicit handling for exactly the two
> failure modes this corpus was designed to test. Thanks for watching."

---

## Timing cheat-sheet

| Section | Target length | Cumulative |
|---|---|---|
| 1. Use case | 0:35 | 0:35 |
| 2. Architecture/agents/tools | 1:25 | 2:00 |
| 3. Live run + output walkthrough | 2:00 | 4:00 |
| 4. Decisions/robustness/limitations | 0:50 | 4:50 |
| 5. Close | 0:10 | 5:00 |

If Section 3's live run takes longer than expected, trim narration in
Section 2 first (it's the most compressible) rather than cutting the
Coverage Gaps / Conflicts walkthrough in Section 3 — that's the part that
actually proves the system works, which is the reviewer takeaway for that
whole segment.
