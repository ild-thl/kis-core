"""When a provider is down, its LLM seats go to the ones still answering, each at most doubles."""

import pytest

from src.services import provider_transport as pt


def _ziel(pid, cap):
    return pt.Target(provider_id=pid, name=f"p{pid}", root=f"http://p{pid}", api_key="",
                     model="m", caps={"llm": cap} if cap else {})


@pytest.fixture
def tuer(monkeypatch):
    unten: set[int] = set()
    monkeypatch.setattr(pt, "is_down", lambda pid, bucket: pid in unten)
    lokal, mylab, mylab_gwdg, gwdg = _ziel(1, 10), _ziel(2, 4), _ziel(3, 2), _ziel(4, 2)
    door = pt._Door(lokal, mylab, "llm", [mylab_gwdg, gwdg])
    return door, unten, (lokal, mylab, mylab_gwdg, gwdg)


def _grenze(door, ziel):
    return dict(door.seats(ziel, b"{}"))[f"{ziel.provider_id}:llm"]


def test_all_up_keeps_every_cap(tuer):
    door, _unten, ziele = tuer
    assert [_grenze(door, z) for z in ziele] == [10, 4, 2, 2]


def test_a_dead_first_choice_hands_its_seats_on(tuer):
    door, unten, (_lokal, mylab, mylab_gwdg, gwdg) = tuer
    unten.add(1)
    # 18 seats in all, 8 left, so each would grow by 2.25 and is held at double.
    assert [_grenze(door, z) for z in (mylab, mylab_gwdg, gwdg)] == [8, 4, 4]


def test_a_small_loss_grows_the_others_a_little(tuer):
    door, unten, (lokal, mylab, _mg, gwdg) = tuer
    unten.add(3)
    assert (_grenze(door, lokal), _grenze(door, mylab), _grenze(door, gwdg)) == (11, 4, 2)


def test_an_uncapped_provider_leaves_the_caps_alone(monkeypatch):
    monkeypatch.setattr(pt, "is_down", lambda pid, bucket: pid == 1)
    door = pt._Door(_ziel(1, 10), _ziel(2, 4), "llm", [_ziel(3, 0)])
    assert _grenze(door, door.backups[0]) == 4
