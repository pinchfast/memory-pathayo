FACT_EXTRACTION_PROMPT = """\
You are the memory system of an AI project manager for a software company.
Extract EVERY atomic fact explicitly stated in the message below. The message is
from a conversation between the AI project manager and a founder, engineer, or
other team member. Never invent facts; only record what is stated.

Speaker: {speaker} (role: {speaker_role})
Timestamp: {timestamp}

Message:
\"\"\"{message}\"\"\"

Return ONLY valid JSON with this schema:
{{
  "facts": [
    {{
      "local_id": "f0",
      "fact_kind": "skill|status_update|commitment|blocker|decision|requirement|"
        "idea|risk|performance|availability|preference|relationship|identity|fact",
      "subject": "who or what the fact is about (person name, project name, task, or 'company')",
      "predicate": "short relation, e.g. 'is skilled in', 'completed', 'is blocked by', 'committed to'",
      "value": "the content of the fact",
      "topics": ["1-5 lowercase slugs"],
      "entities": ["named people, projects, tools, companies"],
      "project": "project name if the fact concerns a specific project, else null",
      "task": "task name/identifier if the fact concerns a specific task, else null",
      "numeric_value": null,
      "unit": null,
      "sentiment": "positive|neutral|negative|mixed",
      "temporal_hint": "current|past|future|ongoing|planned|recurring",
      "due_date": "ISO date if a deadline is stated, else null",
      "evidence_quote": "exact substring from the message"
    }}
  ],
  "relations": [
    {{"from": "f0", "to": "f1", "type": "causes|influences|blocks|depends_on"}}
  ]
}}

Rules:
1. One subject, one predicate, one value per fact; split compound statements.
2. Capture skills, experience levels, and tool proficiency as 'skill' facts.
3. Capture progress claims, completed work, and delays as 'status_update' facts.
4. Capture promises with deadlines as 'commitment' facts and fill due_date.
5. Capture obstacles as 'blocker' facts and link them with 'blocks' relations.
6. Capture founder requirements and decisions as 'requirement'/'decision' facts.
7. Capture signs of low output, missed deadlines, or vague answers as 'performance' facts.
8. Resolve pronouns to actual names; use the speaker name for self-references.
9. evidence_quote MUST be an exact substring of the message.
"""

QUERY_INTENT_PROMPT = """\
You are the retrieval planner of an AI project manager's memory.
Analyze this query and return ONLY valid JSON:

Query: \"\"\"{query}\"\"\"

{{
  "topics": ["1-8 lowercase slugs, include indirect topics"],
  "entities": ["named people, projects, tools"],
  "fact_kind_hints": ["relevant kinds from: skill,status_update,commitment,"
    "blocker,decision,requirement,idea,risk,performance,availability,"
    "preference,relationship,identity"],
  "temporal_scope": "current|past|future|any",
  "expanded_query": "one-sentence rewrite optimized for semantic search"
}}
"""

ASSOCIATIVE_RANKING_PROMPT = """\
You are ranking memory facts for an AI project manager answering this query.

Query: \"\"\"{query}\"\"\"

Candidate facts:
{facts}

For each fact, judge how useful it is for answering the query, including
indirect connections (e.g. an engineer's past delays matter when asked about
deadline risk). Return ONLY valid JSON:

{{
  "scores": [
    {{"fact_id": "...", "relevance": 0.0, "connection": "direct|causal|contextual|historical",
      "reasoning": "one short sentence"}}
  ]
}}

Only include facts with relevance >= 0.2.
"""

REPORT_PROMPT = """\
You are an AI project manager writing a {report_type} report for the founders
of a company. Write in {language}. Be honest, specific, and concise; founders
may be non-technical, so explain plainly and avoid jargon unless the audience
is technical.

Company memory facts (grouped, with dates):
{facts}

Project and people summary:
{summary}

Write the report with these sections:
1. Overall status (one paragraph, plain language)
2. Progress since last report (what was actually delivered)
3. People (who is performing, who is behind, credibility concerns if any)
4. Blockers and risks
5. Recommended actions

Return ONLY valid JSON:
{{"title": "...", "body_markdown": "...", "highlights": ["3-6 bullet strings"], "risk_level": "low|medium|high"}}
"""
