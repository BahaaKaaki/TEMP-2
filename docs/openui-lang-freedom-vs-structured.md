# Freedom vs. Structure — a concrete comparison

> Hand-authored sandbox for `feat/openui-investigation`. Same input deliverable
> (`temp1.md`: a 5-peer "comparable-company benchmark") rendered three ways, to make
> the constraint↔freedom trade-off tangible. All programs follow the OpenUI Lang spec
> (root first, positional args, camelCase, every variable referenced). Verified
> reference-complete by inspection; a real parser check belongs in the eval harness.
>
> Decision in force: **structured freedom** — deterministic for recurring known fields,
> creative latitude for viz/layout/long-tail.

The headline finding is at the bottom (§4) — read it first if short on time.

---

## Artifact A — Structured (post-P0): per-section, consistent

Two sibling sections (Microsoft, NTT). **Note they are structurally identical** —
snapshot Card → facts Table (strategy/restructuring as rows) → slide `TagBlock` →
insights Card → org `TreeView`. Only the *data* differs.

**Microsoft**
```text
root = Stack([snapshotCard, factsCard, slideTags, insightsCard, orgCard], "column", "l")
snapshotCard = Card([snapshotHeader, snapshotDescription], "card")
snapshotHeader = CardHeader("Microsoft", "Technology")
snapshotDescription = TextContent("Global technology peer with a cloud and AI transformation agenda and centralized corporate functions.")
factsCard = Card([factsHeader, factsTable], "card")
factsHeader = CardHeader("Microsoft details")
factsTable = Table([factField, factValue])
factField = Col("Field", ["Geography", "Span of control", "Strategy", "Restructuring impact"], "string")
factValue = Col("Value", ["Global (HQ in Redmond, Washington)", "CEO oversees 14 direct reports", "Empower every person and organization to achieve more [6].", "Centralized Cloud + AI leadership with strong functional governance [6]."], "string")
slideTags = TagBlock(["6", "32"])
insightsCard = Card([insightsHeader, insightsList], "card")
insightsHeader = CardHeader("Insights")
insightsList = MarkDownRenderer("- Broad functional footprint with strong cloud and AI emphasis [6].\n- Operating model balances product innovation with centralized control [6].", "clear")
orgCard = Card([orgHeader, orgTree], "card")
orgHeader = CardHeader("Organization tree")
orgTree = TreeView({name: "CEO", attributes: {type: "Top Role", holder: "Microsoft CEO", span_of_control: "14 direct reports"}, children: [{name: "Microsoft Cloud + AI group", attributes: {type: "Corporate Function/BU"}}, {name: "Finance", attributes: {type: "Corporate Function/BU"}}]}, "Microsoft organization tree")
```

**NTT** (same shell, different data)
```text
root = Stack([snapshotCard, factsCard, slideTags, insightsCard, orgCard], "column", "l")
snapshotCard = Card([snapshotHeader, snapshotDescription], "card")
snapshotHeader = CardHeader("NTT", "Telecommunications / IT Services")
snapshotDescription = TextContent("Large global telecom and services peer with a structured group model and clear functional hierarchy.")
factsCard = Card([factsHeader, factsTable], "card")
factsHeader = CardHeader("NTT details")
factsTable = Table([factField, factValue])
factField = Col("Field", ["Geography", "Span of control", "Strategy", "Restructuring impact"], "string")
factValue = Col("Value", ["Global / Japan HQ", "Group CEO oversees 4 functional L1 areas", "Advance digital transformation across business activities [4].", "New structure consolidates strategy, technology, R&D, and finance [4]."], "string")
slideTags = TagBlock(["31"])
insightsCard = Card([insightsHeader, insightsList], "card")
insightsHeader = CardHeader("Insights")
insightsList = MarkDownRenderer("- Group structure centered on strategy, technology, R&D, and finance [4].\n- New organizational structure scheduled for June 2021 [4].", "clear")
orgCard = Card([orgHeader, orgTree], "card")
orgHeader = CardHeader("Organization tree")
orgTree = TreeView({name: "GROUP CEO", attributes: {type: "OpCo", holder: "Group CEO", span_of_control: "4 direct reports"}, children: [{name: "Corporate strategy planning"}, {name: "Technology planning"}, {name: "Research and development planning"}, {name: "Finance and accounting"}]}, "NTT organization structure")
```

**Verdict:** ✅ scannable, predictable, easy to compare peers, lossless, brand-coherent,
near-zero render-error risk. ⚠️ can feel templated; doesn't exploit data-specific viz
opportunities.

---

## Artifact B — Maximal freedom: per-section, creative (what a loosely-prompted LLM does)

Same two sections, but the model is free. **Note they now look nothing alike.**

**Microsoft** — Slide header + KPI stat cards + strategy callout + insights accordion
```text
root = Stack([msSlide, statsRow, strategyCallout, insightsAccordion, orgCard], "column", "l")
msSlide = Slide("Microsoft", ["Cloud + AI is a standalone L1 pillar [6]", "CEO span: 14 direct reports"], "Global technology peer relevant to an AI-first restructuring.", "Technology", "title-content")
statsRow = Stack([spanStat, geoStat], "row", "m")
spanStat = Card([spanLabel, spanValue], "sunk")
spanLabel = TextContent("Direct reports", "small")
spanValue = TextContent("14", "large-heavy")
geoStat = Card([geoLabel, geoValue], "sunk")
geoLabel = TextContent("HQ", "small")
geoValue = TextContent("Redmond, WA", "large-heavy")
strategyCallout = TextCallout("info", "Strategy", "Empower every person and organization to achieve more [6].")
insightsAccordion = Accordion([insightsItem])
insightsItem = AccordionItem("insights", "Insights", [insightsList])
insightsList = MarkDownRenderer("- Broad functional footprint with strong cloud and AI emphasis [6].\n- Balances product innovation with centralized control [6].", "clear")
orgCard = Card([orgHeader, orgTree], "card")
orgHeader = CardHeader("Organization")
orgTree = TreeView({name: "CEO", attributes: {holder: "Microsoft CEO"}, children: [{name: "Cloud + AI"}, {name: "Finance"}]}, "Microsoft org")
```

**NTT** — CardHeader + Steps + stat grid (a completely different shell)
```text
root = Stack([nttHeader, transitionSteps, factsGrid, orgCard], "column", "l")
nttHeader = CardHeader("NTT", "Telecommunications / IT Services")
transitionSteps = Steps([step1, step2])
step1 = StepsItem("Advance digital transformation", "Resolve social issues via DX across business activities [4].")
step2 = StepsItem("Restructure (June 2021)", "New structure consolidates strategy, technology, R&D, and finance [4].")
factsGrid = Stack([geoCard, spanCard], "row", "m")
geoCard = Card([geoLabel, geoVal], "sunk")
geoLabel = TextContent("Geography", "small")
geoVal = TextContent("Global / Japan HQ", "large-heavy")
spanCard = Card([spanLabel, spanVal], "sunk")
spanLabel = TextContent("Direct reports", "small")
spanVal = TextContent("4", "large-heavy")
orgCard = Card([orgHeader, orgTree], "card")
orgHeader = CardHeader("Group structure")
orgTree = TreeView({name: "GROUP CEO", children: [{name: "Corporate strategy planning"}, {name: "Technology planning"}, {name: "R&D planning"}, {name: "Finance and accounting"}]}, "NTT structure")
```

**Verdict:** ✅ individually richer/more "designed" (KPI stats, slide framing, steps).
⚠️ **but**: Microsoft uses Slide+Accordion+Callout while NTT uses Header+Steps+stat-grid
— a client comparing peers now reads two different layouts; insights are hidden behind a
click in one and not the other; the "14" / "4" KPI stats look great but **risk dropping
the other facts** unless every field is also kept somewhere lossless. This is exactly the
inconsistency we measured in `temp2.md` — pretty in isolation, worse for the actual task.

**Key point:** within a *single section*, "freedom" mostly buys variety + risk, with
limited UX upside, because there isn't much creative headroom in one company's facts.

---

## Artifact C — The real ceiling: whole-deliverable comparison dashboard

The genuinely *best* UI for the user's goal ("compare these peers") isn't a prettier
section — it's a **cross-company view**: a ranked chart + comparison table up top, then
per-company detail in tabs.

```text
root = Stack([intro, spanChartCard, comparisonTableCard, perCompanyTabs], "column", "l")
intro = TextCallout("info", "Benchmark", "Five peers compared on structure and strategy [3][4][6][14][16].")
spanChartCard = Card([spanHeader, spanChart], "card")
spanHeader = CardHeader("Span of control", "CEO direct reports, ranked")
spanChart = HorizontalBarChart(["Microsoft", "Orange", "Telefonica", "AWS", "NTT"], [Series("Direct reports", [14, 14, 6, 4, 4])], "grouped", "Direct reports", "Company")
comparisonTableCard = Card([compHeader, compTable], "card")
compHeader = CardHeader("Peer comparison")
compTable = Table([companyCol, sectorCol, geoCol, spanCol])
companyCol = Col("Company", ["Microsoft", "AWS", "NTT", "Orange", "Telefonica"], "string")
sectorCol = Col("Sector", ["Technology", "Technology", "Telecom / IT", "Telecom", "Telecom"], "string")
geoCol = Col("Geography", ["US", "US", "Japan", "Europe", "Spain"], "string")
spanCol = Col("Direct reports", [14, 4, 4, 14, 6], "number")
perCompanyTabs = Tabs([msTab, nttTab])
msTab = TabItem("ms", "Microsoft", [msDetailCard])
msDetailCard = Card([msDetailHeader, msOrg], "card")
msDetailHeader = CardHeader("Microsoft", "14 direct reports")
msOrg = TreeView({name: "CEO", children: [{name: "Cloud + AI"}, {name: "Finance"}]}, "Microsoft org")
nttTab = TabItem("ntt", "NTT", [nttDetailCard])
nttDetailCard = Card([nttDetailHeader, nttOrg], "card")
nttDetailHeader = CardHeader("NTT", "4 direct reports")
nttOrg = TreeView({name: "GROUP CEO", children: [{name: "Strategy"}, {name: "Technology"}]}, "NTT org")
```
*(AWS, Orange, Telefónica tabs follow the same shape.)*

**Verdict:** ✅ this is the best fit for the user's actual intent — instant cross-peer
comparison, then drill-down. ❌ **our current pipeline cannot produce it.** Translation is
**per-section and independent** (`translate_deliverable_section_langs` fans out one LLM
call per `sections[i]` with no sibling context), so no single call can see all five
companies to build the chart/table — and its `Tabs` would collide with the frontend's own
section tab bar.

---

## 4. What this tells us (the headline)

1. **The biggest UX win is architectural, not prompt-loosening.** The "best" output
   (Artifact C) is blocked by the **per-section pipeline**, not by tight rules. Freedom
   *within* a section (Artifact B) mostly trades consistency for risk. So the lever isn't
   "let the LLM off the leash" — it's **give it a whole-deliverable view** (a comparison/
   overview pass) so it *can* be creative where creativity actually helps.
2. **Consistency is a feature for comparison-style deliverables.** Artifact A beats B for
   the real task (scanning peers), even though B is prettier per-section. P0 was right for
   recurring fields.
3. **A richer palette raises the ceiling.** Artifact C leaned on `HorizontalBarChart` +
   comparison `Table` — generic. Purpose-built components (a KPI/stat block, a peer-compare
   card, a timeline) would make whole-deliverable views genuinely great. Better building
   blocks > more rules.

### Recommended next steps (in priority order)
- **Add a whole-deliverable "overview" pass** (one extra LLM call that sees all sections
  and emits a comparison header: chart + table), rendered above the section tabs. This is
  where freedom pays off — and it's additive, low-risk.
- **Expand the component palette** with 2–3 deliverable-grade components (KPI/stat,
  peer-compare, metric-trend) and let the model choose among them freely.
- **Stand up the eval harness** to measure A/B/C-style variants on real inputs (generate →
  render → judge) so "best" is decided by looking, not arguing.
- **Keep P0** (structured per-field consistency) as the floor underneath all of it.
