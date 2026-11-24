"""Short material may come back with fewer headings than the usual floor."""
import asyncio
import json
from types import SimpleNamespace

from src.features.summary import writing

ZWEI = json.dumps({"title": "Photosynthese", "sections": [
    {"title": "Grundlagen und Ort", "description": "Wo sie stattfindet."},
    {"title": "Reaktionsphasen", "description": "Licht und Calvin-Zyklus."},
]})


def test_two_sections_fail_the_usual_floor():
    assert writing.parse_outline(ZWEI).sections == []


def test_two_sections_pass_a_lower_floor():
    assert [a.title for a in writing.parse_outline(ZWEI, minimum=1).sections] == [
        "Grundlagen und Ort", "Reaktionsphasen"]


class _Caller:
    def __init__(self):
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=ZWEI))])


def _plan(material: str):
    caller = _Caller()
    plan = asyncio.run(writing.plan_outline(caller, language="German", template_body="",
                                            sources=["doc.docx"], material=material, target=4,
                                            enforce_schema=False))
    return plan, caller.calls


def test_short_material_takes_two_sections_at_once():
    plan, calls = _plan("Die Photosynthese ist ein Prozess. " * 10)
    assert len(plan.sections) == 2 and calls == 1


def test_long_material_still_wants_the_floor(monkeypatch):
    monkeypatch.setattr(writing, "SUMMARY_OUTLINE_MAX_ATTEMPTS", 1)
    plan, _ = _plan("x" * (writing.SUMMARY_MIN_SECTIONS * writing.SUMMARY_CHARS_PER_SECTION))
    assert plan.sections == []
