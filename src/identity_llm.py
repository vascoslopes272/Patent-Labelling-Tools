"""
identity_llm.py — asking a language model which aircraft a patent is about.

Stage 03a. Two interchangeable routes, both producing {patent_id: answer_dict}:

  "export"  (default)  build_llm_prompt() writes one question per patent into
                       the workbook's LLM_Prompts sheet. You paste them into a
                       chat and paste the replies back; parse_llm_answer() reads
                       them. No API key, and the workbook keeps a verbatim
                       record of every prompt and answer — which is what a
                       methodology chapter needs to be reproducible.
  "api"                ask_claude() calls the Anthropic API with structured
                       output, so every reply is valid JSON against the schema.

The system prompt is written to make an honest "I don't know" the easy answer.
An invented model name or performance figure is far worse than a blank cell.
"""

from __future__ import annotations

import json
import re

from src.aircraft_specs import POWERTRAIN_DEFS, IS_ELECTRIC_OPTIONS


#
#   MODE "export"  (default)  build_llm_prompt() → the LLM_Prompts sheet → you
#                             paste into a chat → paste the reply back into the
#                             llm_answer column → parse_llm_answer() reads it.
#   MODE "api"                ask_claude() calls the Anthropic API directly.
#
# The export mode is the default deliberately: it needs no API key, it keeps a
# verbatim record of every prompt and answer in the workbook (which is what a
# thesis methodology chapter needs to be reproducible), and it lets you use
# whatever chat interface you already have open.

LLM_SYSTEM_PROMPT = (
    "You are an aerospace research assistant helping build a dataset of eVTOL and "
    "advanced air mobility aircraft for a master's thesis.\n\n"
    "You are given a patent's assignee company, its filing and publication years, and "
    "its title and abstract. Identify the real, publicly announced aircraft this patent "
    "most likely relates to.\n\n"
    "Rules you must follow:\n"
    "- Answer ONLY from what you actually know about the company's announced aircraft. "
    "Never invent a model name, and never invent a performance figure.\n"
    "- If you do not know which aircraft it is, set aircraft_name to null and say why "
    "in reasoning. An honest null is far more useful here than a guess.\n"
    "- Give every specification only if you are confident of it. Any figure you are "
    "unsure of must be null, not an estimate.\n"
    "- confidence is your own 0-1 estimate that aircraft_name is correct.\n"
    "- Units are fixed: mass in kg, speed in km/h, range in km, endurance in minutes."
)

# Kept as a raw JSON schema (not Pydantic) so the module imports without
# pydantic installed — the notebook's export mode never touches the API path.
LLM_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "aircraft_name": {"type": ["string", "null"]},
        "manufacturer": {"type": ["string", "null"]},
        "powertrain": {
            "type": ["string", "null"],
            "enum": [*POWERTRAIN_DEFS.keys(), None],
        },
        "is_electric": {"type": ["string", "null"], "enum": ["Yes", "Hybrid", "No", "Unknown", None]},
        "pax": {"type": ["number", "null"]},
        "mtow_kg": {"type": ["number", "null"]},
        "payload_kg": {"type": ["number", "null"]},
        "cruise_speed_kmh": {"type": ["number", "null"]},
        "max_speed_kmh": {"type": ["number", "null"]},
        "range_km": {"type": ["number", "null"]},
        "endurance_min": {"type": ["number", "null"]},
        "industry_primary": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["aircraft_name", "confidence", "reasoning"],
    "additionalProperties": False,
}


def build_llm_prompt(entry: dict) -> str:
    """The per-patent question. `entry` is one row of the identity table."""
    abstract = (entry.get("abstract") or "")[:1200]
    return (
        f"Patent: {entry.get('patent_id')}\n"
        f"Assignee (raw): {entry.get('assignee_raw') or 'unknown'}\n"
        f"Company (normalised): {entry.get('company_canonical') or 'unknown'}\n"
        f"Filing year: {entry.get('app_year') or 'unknown'}\n"
        f"Publication year: {entry.get('pub_year') or 'unknown'}\n"
        f"Title: {entry.get('title') or ''}\n"
        f"Abstract: {abstract}\n\n"
        "Which real aircraft does this most likely relate to? "
        "Reply with a single JSON object using exactly these keys: "
        "aircraft_name, manufacturer, powertrain "
        f"({'|'.join(POWERTRAIN_DEFS)}), is_electric ({IS_ELECTRIC_OPTIONS}), "
        "pax, mtow_kg, payload_kg, cruise_speed_kmh, max_speed_kmh, range_km, "
        "endurance_min, industry_primary, confidence, reasoning. "
        "Use null for anything you do not confidently know."
    )


_JSON_BLOB_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_llm_answer(text: str | None) -> dict:
    """Tolerantly parse a pasted chat reply into the answer dict.

    Chat replies arrive wrapped in prose and ```json fences, so the first
    balanced-looking {...} blob is extracted rather than requiring clean JSON.
    An unparseable answer returns {} instead of raising — one bad paste in a
    350-row sheet must not abort the export.
    """
    if not text or not str(text).strip():
        return {}
    raw = str(text).strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    m = _JSON_BLOB_RE.search(raw)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def ask_claude(
    prompts: dict[str, str],
    model: str = "claude-opus-5",
    max_tokens: int = 4096,
    max_workers: int = 8,
    progress: bool = True,
) -> dict[str, dict]:
    """Optional API path for the LLM step. `prompts` is {patent_id: prompt}.

    Uses structured outputs (output_config.format) so every reply is valid JSON
    against LLM_OUTPUT_SCHEMA — no prose stripping, no retry-on-malformed loop.
    Requests are independent, so they run on a small thread pool; the SDK
    already retries 429/5xx with backoff, so nothing is layered on top of that.

    Credentials resolve the SDK's normal way (ANTHROPIC_API_KEY, or an
    `ant auth login` profile) — nothing is read from config.yaml.
    """
    import anthropic
    from concurrent.futures import ThreadPoolExecutor, as_completed

    client = anthropic.Anthropic()
    results: dict[str, dict] = {}

    def _one(pid: str, prompt: str) -> tuple[str, dict]:
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=LLM_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema", "schema": LLM_OUTPUT_SCHEMA}},
            )
            if resp.stop_reason == "refusal":
                return pid, {"_error": "refusal"}
            text = next((b.text for b in resp.content if b.type == "text"), "")
            return pid, (json.loads(text) if text else {})
        except Exception as exc:                      # noqa: BLE001 — one bad
            return pid, {"_error": f"{type(exc).__name__}: {exc}"}   # patent must
                                                                     # not kill the run
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_one, pid, p) for pid, p in prompts.items()]
        for i, fut in enumerate(as_completed(futures), 1):
            pid, data = fut.result()
            results[pid] = data
            if progress and (i % 25 == 0 or i == len(futures)):
                print(f"  LLM {i}/{len(futures)}")
    return results

