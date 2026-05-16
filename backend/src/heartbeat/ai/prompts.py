from datetime import datetime

SYSTEM_PROMPT = """\
You are an on-call incident analyst. Write a concise postmortem draft in plain English.

Rules:
- Summarize what happened factually based only on the data provided.
- Identify the probable cause from the check timeline. Do not speculate beyond the evidence.
- Suggest two or three concrete next steps to prevent recurrence.
- Three to five short paragraphs at most.
- No emojis.\
"""


def render_incident_prompt(
    endpoint_name: str,
    endpoint_url: str,
    started_at: datetime,
    ended_at: datetime | None,
    duration_seconds: int | None,
    frozen_timeline: list[dict],
) -> str:
    lines: list[str] = [
        f"Endpoint: {endpoint_name}",
        f"URL: {endpoint_url}",
        f"Incident started: {started_at.isoformat()}",
    ]
    if ended_at is not None:
        lines.append(f"Incident ended: {ended_at.isoformat()}")
        if duration_seconds is not None:
            lines.append(f"Duration: {duration_seconds}s")
    else:
        lines.append("Incident status: open")

    lines.append("")
    lines.append("Check timeline:")
    lines.append(f"{'Timestamp':<28} {'Outcome':<8} {'Latency':>8} {'Status':>7}  Error")
    lines.append("-" * 70)

    for entry in frozen_timeline:
        ts: str = entry["checked_at"]
        outcome: str = entry["outcome"]
        latency = f"{entry['latency_ms']}ms"
        status = str(entry["status_code"]) if entry["status_code"] is not None else "-"
        error_cat = entry.get("error_category") or ""
        error_msg = entry.get("error_message") or ""
        if error_cat and error_msg:
            error = f"{error_cat}: {error_msg}"
        elif error_cat:
            error = error_cat
        elif error_msg:
            error = error_msg
        else:
            error = ""
        row = f"{ts:<28} {outcome:<8} {latency:>8} {status:>7}  {error}"
        lines.append(row.rstrip())

    return "\n".join(lines)
