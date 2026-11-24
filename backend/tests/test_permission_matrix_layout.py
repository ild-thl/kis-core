"""The layout of the permission table, no row may be lost or appear twice."""

from src.permissions_registry import (
    ALL_PERMISSION_KEYS,
    CHAPTER_MANAGE,
    CHAPTER_USE,
    GROUP_CHAPTER,
    GROUPS,
    PERM_SET_AIA_USAGE,
    PERM_SET_STATS_MODELS,
    PERM_SET_STATS_USERS,
    PERM_SET_TOOLS_STATS,
    PERMISSION_GROUPS,
)
from src.routes.admin import roles as roles_route

ADMIN = {"role": "admin", "email": "a@example.org"}


def test_every_permission_sits_in_exactly_one_group():
    placed = [key for group in GROUPS for key in PERMISSION_GROUPS[group]]

    assert sorted(placed) == sorted(ALL_PERMISSION_KEYS)
    assert len(placed) == len(set(placed))


def test_no_group_is_empty():
    assert all(PERMISSION_GROUPS[group] for group in GROUPS)


def test_groups_stand_in_two_chapters_in_display_order():
    assert [(GROUP_CHAPTER[g], g) for g in GROUPS] == [
        (CHAPTER_USE, "general"),
        (CHAPTER_USE, "aia"),
        (CHAPTER_USE, "tools"),
        (CHAPTER_MANAGE, "set.werkzeuge"),
        (CHAPTER_MANAGE, "set.assistent"),
        (CHAPTER_MANAGE, "set.statistik"),
        (CHAPTER_MANAGE, "set.anbieter"),
        (CHAPTER_MANAGE, "set.nutzer"),
        (CHAPTER_MANAGE, "set.system"),
        (CHAPTER_MANAGE, "set.mascot"),
        (CHAPTER_MANAGE, "set.event"),
        (CHAPTER_MANAGE, "set.campus"),
    ]


def test_the_statistics_rights_stand_together():
    """Only platform-wide numbers are a right, own modules are read at the module."""
    assert PERMISSION_GROUPS["set.statistik"] == (
        PERM_SET_AIA_USAGE,
        PERM_SET_STATS_USERS,
        PERM_SET_TOOLS_STATS,
        PERM_SET_STATS_MODELS,
    )


async def test_the_route_hands_each_group_its_chapter(monkeypatch):
    monkeypatch.setattr(roles_route.db, "list_custom_roles", lambda: [])

    body = roles_route.list_roles(admin=ADMIN)

    assert [(g["chapter"], g["key"]) for g in body["groups"]] == [
        (GROUP_CHAPTER[g], g) for g in GROUPS
    ]
