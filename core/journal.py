"""The Dream Journal — Homie's beliefs, in plain words.

The owner's named first win: an anytime "What Homie Knows About Me" page he can read and
correct. This module is the PURE renderer — it turns the honest belief rows from
`Remember.beliefs()` (each an hour + a probability in [0,1] + the evidence behind it) into
plain sentences a person can read at a glance, with a confidence WORD (never a raw percent
masquerading as precision) and a provenance chip ("from 30 days" vs "from 4 days").

Two hard rules, both from the brainstorm's external audit:
  * **Honest-empty.** With nothing firm to say, it says exactly that — never a padded or
    invented belief. Silence beats a confident guess.
  * **Confidence is a word, and only FIRM beliefs appear.** `Remember.beliefs()` already
    drops anything below the evidence floor, so a coincidence never reaches this page.

No bus, no I/O, no clock of its own — it renders what it is given, so it is trivially
testable and the same rows render identically on the cockpit, the status page, or a recap.
"""
from __future__ import annotations

HOURS_OF_DAY = (
    "midnight", "1am", "2am", "3am", "4am", "5am", "6am", "7am", "8am", "9am", "10am", "11am",
    "noon", "1pm", "2pm", "3pm", "4pm", "5pm", "6pm", "7pm", "8pm", "9pm", "10pm", "11pm",
)


def confidence_word(prob: float) -> str:
    """A calibrated WORD for a probability — never a false-precision percentage. The bands
    are deliberately coarse: the owner should feel the strength, not audit a decimal."""
    if prob >= 0.85:
        return "almost always"
    if prob >= 0.6:
        return "usually"
    if prob >= 0.4:
        return "often"
    return "sometimes"


def provenance(gdays: float) -> str:
    """How much living-with-you stands behind a belief. Rounds to whole days — the honest
    grain of the evidence, not the decayed float."""
    n = max(1, round(gdays))
    return f"from {n} day{'s' if n != 1 else ''}"


def _part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "in the morning"
    if 12 <= hour < 17:
        return "in the afternoon"
    if 17 <= hour < 22:
        return "in the evening"
    return "at night"


def _subject(topic: str, zone: str | None) -> str:
    """Turn a (topic, zone) into a plain clause. Unknown topics fall back to a readable
    generic rather than leaking an internal event name."""
    where = f"the {zone}" if zone else "home"
    if topic.startswith("presence"):
        return f"you're in {where}" if zone else "you're home"
    if topic.startswith("motion"):
        return f"there's movement in {where}"
    if topic.startswith("occupancy"):
        return f"{where} is in use"
    # Generic, still human: "the kitchen sees <event>".
    leaf = topic.split(".")[-1].replace("_", " ")
    return f"{where} sees {leaf}"


def sentence(row: dict) -> str:
    """One plain belief line, e.g.
    'Most mornings around 8am, you're in the kitchen. (almost always · from 30 days)'."""
    hour = row["hour"]
    clock = HOURS_OF_DAY[hour]
    lead = _part_of_day(hour).replace("in the ", "Most ").replace("at night", "Most nights")
    if lead.startswith("Most morning") or lead.startswith("Most afternoon") or lead.startswith("Most evening"):
        lead = lead + "s"  # morning -> mornings
    subject = _subject(row["topic"], row["zone"])
    tag = f"({confidence_word(row['prob'])} · {provenance(row['gdays'])})"
    return f"{lead} around {clock}, {subject}. {tag}"


def what_homie_knows(rows: list[dict]) -> list[str]:
    """The page as a list of plain lines. Honest-empty when there is nothing firm yet."""
    if not rows:
        return ["I'm still learning your routines — nothing I'd state as fact yet."]
    return [sentence(r) for r in rows]


def render_text(rows: list[dict], *, title: str = "What Homie knows about you") -> str:
    """A render-ready text block for the terminal/status page/recap."""
    lines = what_homie_knows(rows)
    body = "\n".join(f"  • {ln}" for ln in lines)
    return f"{title}\n{body}"
