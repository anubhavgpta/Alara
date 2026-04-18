"""Build a formatted memory context block for injection into the system prompt."""

from alara.memory.store import get_all_memories, get_recent_summaries


def build_memory_context(n_summaries: int = 3) -> str:
    summaries = get_recent_summaries(n_summaries)
    memories = get_all_memories()

    if not summaries and not memories:
        return ""

    lines: list[str] = ["--- Alara Memory ---"]

    if summaries:
        lines.append("Past sessions:")
        for summary in summaries:
            for bullet in summary.strip().splitlines():
                lines.append(bullet if bullet.startswith("-") else f"- {bullet}")

    if memories:
        lines.append("Known facts:")
        for m in memories:
            lines.append(f"{m['key']}: {m['value']}")

    lines.append("--------------------")
    return "\n".join(lines)
