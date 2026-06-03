# PPTX Template Authoring Guide

How to create PowerPoint templates for the workflow engine, and how to write LLM agent instructions that produce compatible output.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Placeholder Reference](#placeholder-reference)
3. [Template Patterns](#template-patterns)
   - [Pattern A: Simple Slides](#pattern-a-simple-slides)
   - [Pattern B: Variant Slides (Team Size Selection)](#pattern-b-variant-slides)
   - [Pattern C: Loop Slides (Repeat Per Person)](#pattern-c-loop-slides)
   - [Pattern D: Repeat Groups (Project Lists)](#pattern-d-repeat-groups)
4. [Combining Patterns (Full CV Example)](#combining-patterns-full-cv-example)
5. [Common Mistakes](#common-mistakes)
6. [Writing LLM Agent Instructions](#writing-llm-agent-instructions)
7. [Agent Instruction Templates](#agent-instruction-templates)

---

## Quick Start

1. Open your `.pptx` file in PowerPoint.
2. Type placeholders directly in text boxes using the syntax described below.
3. Upload the template in the workflow builder (agent node > "Generate Schema from Template").
4. The engine parses placeholders, generates a JSON Schema, and injects it into the agent's prompt.
5. When the user exports, the engine fills placeholders with the agent's structured output.

---

## Placeholder Reference

All placeholders use double curly braces. Whitespace inside is flexible.

### `{{ field_name }}`  -- Text substitution

Replaces the placeholder with a single string value.

```
{{ team_title }}
{{ item.full_name }}
{{ people.0.city }}
```

### `{{ field_name | description }}`  -- Text with hint

Everything after the pipe (`|`) is a free-text description passed to the LLM via the generated schema. It also marks the field as **required**.

```
{{ item.level | job title or rank }}
{{ item.city | office location and/or city }}
```

### `{{* field_name }}` -- Bullet array

Replaced by one bullet paragraph per item in a string array. Formatting (font, size, indent, bullet style) is cloned from the original paragraph.

```
{{* item.executive_summary | 2-3 bullets, 70-90 chars each }}
{{* item.relevant_experience | 3-5 bullets, 100-120 chars each }}
```

**Data expected:**

```json
"executive_summary": [
  "10+ years consulting in public policy",
  "Deep expertise in agriculture sector"
]
```

### `{{+ field_name }}` -- Repeat-group field

Marks the **title row** of a repeating paragraph group. Used together with `{{* }}` to define project-style blocks that repeat for each item in an array.

```
{{+ item.projects_left.title }}
{{* item.projects_left.bullets | 2-4 bullets }}
```

The engine detects that both placeholders share the same array root (`item.projects_left`), groups them, and repeats the entire paragraph block once per array element.

**Data expected:**

```json
"projects_left": [
  {
    "title": "Agricultural Due Diligence",
    "bullets": [
      "Assessed farm acquisition targets across GCC",
      "Evaluated crop yield data for 5 regions"
    ]
  },
  {
    "title": "Rural Sector Strategy",
    "bullets": [
      "Developed national rural development roadmap",
      "Advised ministry on subsidy reform"
    ]
  }
]
```

### `{{# name }}` / `{{/ name }}` -- Slide loop

Marks the **start** and **end** of a slide loop. Every slide between these markers is repeated once per item in the named array. Each slide must be on its own slide.

- `{{# people }}` goes on its own slide (the marker slide).
- `{{/ people }}` goes on its own slide (the end marker slide).
- Slides between them are the **loop body** -- they use `item.*` paths.
- Both marker slides are removed from the output.

### `{{@ name | count }}` -- Variant marker

Selects which slides to include based on the length of an array. Place one marker per variant slide. The engine keeps the variant matching the array length and discards the rest.

```
{{@ people | 5 }}   (on a slide designed for 5 people)
{{@ people | 4 }}   (on a slide designed for 4 people)
{{@ people | 3 }}   (on a slide designed for 3 people)
```

---

## Template Patterns

### Pattern A: Simple Slides

For templates with no repetition -- a fixed number of slides, each with known fields.

**Example:** A single-page executive summary.

```
Slide 1:
  {{ report_title }}
  {{ client_name }}
  {{* key_findings | 3-5 bullet points }}
```

**Generated schema:**

```json
{
  "report_title": { "type": "string" },
  "client_name": { "type": "string" },
  "key_findings": {
    "type": "array",
    "items": { "type": "string" },
    "description": "3-5 bullet points"
  }
}
```

No loops, no variants. Every slide is included in the output as-is.

---

### Pattern B: Variant Slides

Use when the same slide layout changes depending on data count (e.g., a team summary page that differs for 3, 4, or 5 people).

**Example:** Three variant versions of a team title slide.

```
Slide 1 (for 5 people):
  {{ team_title }}
  {{ people.0.full_name }}  {{ people.1.full_name }}  {{ people.2.full_name }}  {{ people.3.full_name }}  {{ people.4.full_name }}
  {{@ people | 5 }}

Slide 2 (for 4 people):
  {{ team_title }}
  {{ people.0.full_name }}  {{ people.1.full_name }}  {{ people.2.full_name }}  {{ people.3.full_name }}
  {{@ people | 4 }}

Slide 3 (for 3 people):
  {{ team_title }}
  {{ people.0.full_name }}  {{ people.1.full_name }}  {{ people.2.full_name }}
  {{@ people | 3 }}
```

**How it works:**

- If the data has 5 people, Slide 1 is kept, Slides 2-3 are discarded.
- If the data has 4 people, Slide 2 is kept, Slides 1 and 3 are discarded.
- If the data has 3 people, Slide 3 is kept, Slides 1-2 are discarded.
- If the count falls between variants, the nearest lower-or-equal variant is selected.
- If the count exceeds the maximum variant, the highest variant is used.

**Key rules:**

- The `{{@ }}` marker can be placed anywhere on the slide (e.g., a tiny text box in the corner). It is stripped from the output.
- On variant slides, use **indexed paths** like `people.0.full_name`, `people.1.city`, etc.
- These indexed paths are detected by the schema generator and folded into the array's item schema automatically.

---

### Pattern C: Loop Slides

Use when a set of slides should repeat once per item in an array (e.g., one CV detail page per person).

**Example:**

```
Slide 5 (loop start marker):
  {{# people }}

Slide 6 (loop body -- individual CV):
  {{ item.full_name }}
  {{ item.level }} | {{ item.city }}
  {{* item.executive_summary | 2-3 bullets, 70-90 chars each }}
  {{* item.relevant_experience | 3-5 bullets }}

Slide 7 (loop end marker):
  {{/ people }}
```

**How it works:**

- Slides 5 and 7 are **removed** from the output (they are just markers).
- Slide 6 is **copied once per item** in the `people` array.
- Inside the loop body, `item` refers to the current array element.
- If `people` has 5 entries, the output gets 5 copies of Slide 6.

**Key rules:**

- The loop start `{{# }}` and end `{{/ }}` must each be on their own dedicated slide.
- Loop body slides use `item.field_name` to reference the current element.
- You can have multiple body slides between the markers (e.g., a two-slide layout per person).
- Non-loop fields (like `team_title`) are also accessible inside loop body slides.

---

### Pattern D: Repeat Groups

Use when a section within a single slide should repeat for each item in a sub-array (e.g., a list of projects with title + bullets).

**Example (inside a loop body slide):**

```
{{+ item.projects_left.title }}
{{* item.projects_left.bullets | 2-4 bullets }}

{{+ item.projects_right.title }}
{{* item.projects_right.bullets | 2-4 bullets }}
```

**How it works:**

- The engine detects that `{{+ item.projects_left.title }}` and `{{* item.projects_left.bullets }}` share the root `item.projects_left`.
- It groups them into a "repeat span."
- For each object in the `projects_left` array, the title + bullets paragraph block is cloned.
- Formatting is preserved from the original paragraphs.

**Key rules:**

- `{{+ }}` starts a new repeat group row. `{{* }}` continues it.
- Both must share the same path prefix (the array root).
- The paragraphs must be **contiguous** in the same text frame -- no other content between them.
- The data must be an **array of objects**, where each object has the leaf fields (`title`, `bullets`).

---

## Combining Patterns (Full CV Example)

A complete CV template for 2-6 people uses all four patterns together.

### Template Structure

| Slide | Content | Pattern |
|-------|---------|---------|
| 1 | Team title (6 people layout) | Variant (`{{@ people \| 6 }}`) |
| 2 | Team title (5 people layout) | Variant (`{{@ people \| 5 }}`) |
| 3 | Team title (4 people layout) | Variant (`{{@ people \| 4 }}`) |
| 4 | Team title (3 people layout) | Variant (`{{@ people \| 3 }}`) |
| 5 | Team title (2 people layout) | Variant (`{{@ people \| 2 }}`) |
| 6 | Loop start marker | `{{# people }}` |
| 7 | Individual CV page | Loop body with repeat groups |
| 8 | Loop end marker | `{{/ people }}` |

### Variant Slides (Slides 1-5)

Each variant slide has:

- `{{ team_title }}` for the heading.
- Indexed person fields: `{{ people.0.full_name }}`, `{{ people.0.level }} | {{ people.0.city }}`.
- Summary bullets: `{{* people.0.team_summary | 3-4 bullets }}`.
- Relevant experience summary: `{{* people.0.relevant_experience_summary | 2 bullets }}`.
- A variant marker: `{{@ people | N }}` where N matches the number of people shown.

Variant slides only need placeholders for the people they display (e.g., the 3-person variant only references `people.0`, `people.1`, `people.2`).

### Loop Body (Slide 7)

Left panel (static section headings + bullet placeholders):

```
{{ item.full_name }}
{{ item.level }} | {{ item.city | office or/and city }}

Executive summary
{{* item.executive_summary | 2-3 bullets, 70-90 chars each }}

Relevant expertise
{{* item.relevant_experience | 3-5 bullets, 100-120 chars each }}

Prior experience
{{* item.prior_experience | 1-3 bullets, 70-90 chars each }}

Education
{{* item.education | 1-3 bullets, 70-90 chars each }}
```

Right panel (repeat-group project blocks):

```
{{+ item.projects_left.title }}
{{* item.projects_left.bullets | 2-4 bullets }}

{{+ item.projects_right.title }}
{{* item.projects_right.bullets | 2-4 bullets }}
```

### Output for 5 People

The engine produces 6 slides:

1. The 5-person variant team title (from Slide 2), filled with `people[0..4]` data.
2. Individual CV for person 1 (from Slide 7, loop iteration 1).
3. Individual CV for person 2 (from Slide 7, loop iteration 2).
4. Individual CV for person 3 (from Slide 7, loop iteration 3).
5. Individual CV for person 4 (from Slide 7, loop iteration 4).
6. Individual CV for person 5 (from Slide 7, loop iteration 5).

---

## Common Mistakes

### Wrong: Missing `item.` prefix inside loop body

```
{{* executive_summary }}        <-- WRONG inside a loop
{{* item.executive_summary }}   <-- CORRECT
```

Inside a `{{# }}` / `{{/ }}` loop, all fields must use `item.` to reference the current array element.

### Wrong: Using a different prefix than `item`

```
{{ person.full_name }}    <-- WRONG
{{ item.full_name }}      <-- CORRECT
```

The loop variable is always called `item`. Any other name is treated as a regular dotted path.

### Wrong: Placing loop markers on body slides

```
Slide 1:  {{# people }}  {{ item.full_name }}   <-- WRONG
```

The `{{# }}` marker must be on its **own dedicated slide** with no other content. Same for `{{/ }}`.

### Wrong: Non-contiguous repeat groups

```
{{+ item.projects.title }}
Some static text here         <-- BREAKS the repeat group
{{* item.projects.bullets }}
```

The `{{+ }}` and `{{* }}` paragraphs for the same array root must be **directly adjacent** in the same text box.

### Wrong: Mixing indexed paths across variants

If Slide 1 has `{{@ people | 5 }}`, it should only reference `people.0` through `people.4`. Do not reference `people.5` on a 5-person variant -- there is no sixth person.

### Wrong: Forgetting the pipe in variant markers

```
{{@ people 5 }}    <-- WRONG (no pipe)
{{@ people | 5 }}  <-- CORRECT
```

The count must follow a `|` pipe character.

### Watch: Description hints with special characters

Descriptions after `|` can contain any text except `}`. Keep them concise.

```
{{ item.city | office or/and city }}   <-- OK
{{* item.summary | 2-3 bullets }}      <-- OK
```

---

## Writing LLM Agent Instructions

The agent's system instructions control the quality and structure of the output. When a template is uploaded, the engine auto-generates a JSON Schema and injects it into the agent's prompt. Your instructions should complement (not repeat) the schema.

### What the schema already handles

The `| description` hints you put in placeholders (e.g., `{{* item.executive_summary | 2-3 bullets, 70-90 chars each }}`) are automatically injected into the JSON Schema as `description` fields. The LLM already sees those limits. **Do not repeat them in the agent instructions.**

Things the schema communicates automatically:

- Field names and nesting structure
- Data types (string, array of strings, array of objects)
- Required vs. optional fields
- Per-field description hints (bullet counts, character ranges)
- Array minItems / maxItems (from variant markers)

### What instructions should add

Focus on things the schema **cannot** express:

1. **Role and task context** -- what the agent is doing, what source data to use.
2. **Writing style** -- telegraphic fragments vs. full sentences, tone, no markdown.
3. **Cross-field constraints** -- total character budget across multiple fields (the schema only knows per-field limits).
4. **Content strategy** -- prefer breadth over depth, do not invent facts, maximize distinct projects, etc.

Note: citations (`[1]`, `[2]`) from KB searches are automatically stripped from deliverable data by the system prompt. You do not need to add "no citations" instructions -- the platform already distinguishes between chat responses (where citations are shown) and structured deliverable output (where they are omitted).

### Instruction Structure

A good agent instruction block has three sections:

```
1. Role and task context (1-2 sentences)
2. Style and cross-field constraints (things the schema cannot express)
3. Prohibited behaviors (citations, invented facts, markdown)
```

---

## Agent Instruction Templates

### Template 1: CV Portfolio (matches the full CV example above)

Copy and adapt the following for your workflow agent instructions:

```
You are a CV portfolio builder. Using the knowledge base, create structured
CV data for the requested team members.

STYLE:
- Use telegraphic style throughout: short fragments, no full sentences.
- Maximize the number of distinct projects per person. Do not collapse
  multiple projects into a single entry.
- Left panel total text (executive_summary + relevant_experience +
  prior_experience + education combined) should stay within 400 characters.

PROHIBITED:
- Do NOT invent facts. If evidence is insufficient, leave the field
  as an empty string or empty array.
- Do NOT use markdown formatting (no **, no ##, no - prefixes).
```

### Template 2: Generic Report

```
You are a report generator. Populate all fields using evidence from
the conversation context and knowledge base.

STYLE:
- Use concise, factual language. No filler or hedging.
- No markdown formatting in any field.

PROHIBITED:
- Do NOT invent facts. Leave unsupported fields empty.
```

### Template 3: Minimal (when the schema descriptions are sufficient)

```
Populate every field using evidence from the knowledge base.
Use telegraphic style (short fragments, not full sentences).
Do not use markdown formatting.
```

---

## Checklist Before Uploading

- [ ] Every placeholder uses the correct prefix (`{{ }}`, `{{* }}`, `{{+ }}`, `{{# }}`, `{{/ }}`, `{{@ }}`).
- [ ] Loop body slides use `item.field_name` for all fields.
- [ ] Loop start and end markers are on their own dedicated slides.
- [ ] Variant markers include a pipe and count: `{{@ name | N }}`.
- [ ] Repeat group paragraphs (`{{+ }}` and `{{* }}`) are contiguous in the same text box.
- [ ] Description hints after `|` are concise and do not contain `}`.
- [ ] No placeholder text outside of `{{ }}` braces (e.g., stray `}}` or `{{` fragments).
- [ ] The template opens cleanly in PowerPoint before uploading.
- [ ] Agent instructions include writing style and any cross-field constraints.
