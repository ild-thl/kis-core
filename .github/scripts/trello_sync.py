"""Keeps a Trello board and a GitHub project in step, with Trello owning the text and the column synced both ways."""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

TRELLO_API = "https://api.trello.com/1"
GITHUB_GRAPHQL = "https://api.github.com/graphql"
SKIP_LISTS = {"Info"}
LINK_LABEL = "trello"
ARCHIVED_PREFIX = "[archiviert] "
CARD_URL = re.compile(r"https://trello\.com/c/([A-Za-z0-9]+)")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"Missing environment variable {name}")
    return value


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else EPOCH


class Trello:
    def __init__(self, key, token, board_id):
        self.auth = {"key": key, "token": token}
        self.board_id = board_id

    def call(self, method, path, **params):
        query = urllib.parse.urlencode({**self.auth, **params})
        if method == "GET":
            request = urllib.request.Request(f"{TRELLO_API}/{path}?{query}")
        else:
            request = urllib.request.Request(f"{TRELLO_API}/{path}", data=query.encode(), method=method)
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def lists(self):
        return self.call("GET", f"boards/{self.board_id}/lists", fields="name")

    def cards(self):
        return self.call("GET", f"boards/{self.board_id}/cards/all",
                         fields="name,desc,idList,shortLink,shortUrl,closed,dateLastActivity,labels")

    def last_moves(self):
        """Returns the time each card last entered its current list (creation counts as entering)."""
        moves = {}
        actions = self.call("GET", f"boards/{self.board_id}/actions",
                            filter="createCard,updateCard:idList,copyCard,convertToCardFromCheckItem", limit=1000)
        for action in actions:
            card = action.get("data", {}).get("card", {})
            card_id = card.get("id")
            if card_id and card_id not in moves:
                moves[card_id] = parse_time(action["date"])
        return moves


class Project:
    def __init__(self, token, owner, number):
        self.token = token
        self.owner = owner
        self.number = int(number)

    def query(self, text, **variables):
        body = json.dumps({"query": text, "variables": variables}).encode()
        request = urllib.request.Request(GITHUB_GRAPHQL, data=body, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        if result.get("errors"):
            sys.exit(f"GitHub API error: {result['errors']}")
        return result["data"]

    def load(self):
        data = self.query("""
            query($owner: String!, $number: Int!) {
              user(login: $owner) { projectV2(number: $number) {
                id
                field(name: "Status") { ... on ProjectV2SingleSelectField { id options { id name } } }
              } }
            }""", owner=self.owner, number=self.number)
        project = data["user"]["projectV2"]
        self.id = project["id"]
        self.status_field = project["field"]["id"]
        self.options = {option["name"]: option["id"] for option in project["field"]["options"]}

    def items(self):
        items, cursor = [], None
        while True:
            data = self.query("""
                query($id: ID!, $cursor: String) {
                  node(id: $id) { ... on ProjectV2 { items(first: 100, after: $cursor) {
                    pageInfo { hasNextPage endCursor }
                    nodes {
                      id type
                      status: fieldValueByName(name: "Status") {
                        ... on ProjectV2ItemFieldSingleSelectValue { name updatedAt }
                      }
                      content {
                        ... on DraftIssue { id title body }
                        ... on Issue { id title body url labels(first: 20) { nodes { name } } }
                      }
                    }
                  } } }
                }""", id=self.id, cursor=cursor)
            page = data["node"]["items"]
            items.extend(page["nodes"])
            if not page["pageInfo"]["hasNextPage"]:
                return items
            cursor = page["pageInfo"]["endCursor"]

    def add_draft(self, title, body):
        data = self.query("""
            mutation($project: ID!, $title: String!, $body: String) {
              addProjectV2DraftIssue(input: {projectId: $project, title: $title, body: $body}) { projectItem { id } }
            }""", project=self.id, title=title, body=body)
        return data["addProjectV2DraftIssue"]["projectItem"]["id"]

    def set_status(self, item_id, name):
        self.query("""
            mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
              updateProjectV2ItemFieldValue(input: {projectId: $project, itemId: $item, fieldId: $field,
                value: {singleSelectOptionId: $option}}) { projectV2Item { id } }
            }""", project=self.id, item=item_id, field=self.status_field, option=self.options[name])

    def update_draft(self, draft_id, title, body):
        self.query("""
            mutation($id: ID!, $title: String!, $body: String) {
              updateProjectV2DraftIssue(input: {draftIssueId: $id, title: $title, body: $body}) { draftIssue { id } }
            }""", id=draft_id, title=title, body=body)

    def update_issue(self, issue_id, title=None, body=None):
        fields = {k: v for k, v in {"title": title, "body": body}.items() if v is not None}
        self.query("""
            mutation($id: ID!, $title: String, $body: String) {
              updateIssue(input: {id: $id, title: $title, body: $body}) { issue { id } }
            }""", id=issue_id, **fields)


def draft_body(card):
    labels = ", ".join(label["name"] for label in card["labels"] if label["name"])
    parts = [card["desc"].strip()] if card["desc"].strip() else []
    if labels:
        parts.append(f"Labels: {labels}")
    parts.append(f"Trello: {card['shortUrl']}")
    return "\n\n".join(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="only print what would change")
    args = parser.parse_args()
    dry = args.dry_run

    trello = Trello(env("TRELLO_KEY"), env("TRELLO_TOKEN"), env("TRELLO_BOARD_ID"))
    project = Project(env("PROJECT_TOKEN"), env("PROJECT_OWNER"), env("PROJECT_NUMBER"))
    project.load()

    lists = {item["id"]: item["name"] for item in trello.lists()}
    list_by_name = {name: list_id for list_id, name in lists.items()}
    cards = trello.cards()
    moves = trello.last_moves()
    items = project.items()

    changes = []

    def do(text, action):
        changes.append(text)
        print(("WOULD " if dry else "") + text)
        if not dry:
            action()

    linked = {}
    for item in items:
        content = item.get("content") or {}
        match = CARD_URL.search(content.get("body") or "")
        if match:
            linked[match.group(1)] = item

    for card in cards:
        list_name = lists.get(card["idList"], "")
        if list_name in SKIP_LISTS:
            continue
        item = linked.get(card["shortLink"])
        title = (ARCHIVED_PREFIX if card["closed"] else "") + card["name"]

        if item is None:
            if card["closed"]:
                continue
            body = draft_body(card)

            def create(card=card, title=title, body=body, list_name=list_name):
                item_id = project.add_draft(title, body)
                if list_name in project.options:
                    project.set_status(item_id, list_name)
            do(f"create item '{title}' in {list_name}", create)
            continue

        content = item["content"]
        is_draft = item["type"] == "DRAFT_ISSUE"
        if is_draft:
            body = draft_body(card)
            if content["title"] != title or (content["body"] or "").strip() != body.strip():
                do(f"update item text '{title}'",
                   lambda c=content, t=title, b=body: project.update_draft(c["id"], t, b))
        elif content["title"] != title:
            do(f"update issue title '{title}'", lambda c=content, t=title: project.update_issue(c["id"], title=t))

        if card["closed"]:
            continue
        status = item.get("status") or {}
        github_column = status.get("name")
        if github_column == list_name:
            continue
        trello_time = moves.get(card["id"], parse_time(card["dateLastActivity"]))
        github_time = parse_time(status.get("updatedAt"))
        if github_column and github_time > trello_time and github_column in list_by_name:
            do(f"move card '{card['name']}' to {github_column}",
               lambda c=card, col=github_column: trello.call("PUT", f"cards/{c['id']}", idList=list_by_name[col]))
        elif list_name in project.options:
            do(f"move item '{card['name']}' to {list_name}",
               lambda i=item, col=list_name: project.set_status(i["id"], col))

    for item in items:
        content = item.get("content") or {}
        if item["type"] != "ISSUE" or CARD_URL.search(content.get("body") or ""):
            continue
        labels = {label["name"] for label in content["labels"]["nodes"]}
        if LINK_LABEL not in labels:
            continue
        column = (item.get("status") or {}).get("name")
        list_id = list_by_name.get(column) or list_by_name["Backlog"]

        def publish(content=content, list_id=list_id):
            card = trello.call("POST", "cards", idList=list_id, name=content["title"],
                               desc=content["body"] or "", pos="bottom")
            body = ((content["body"] or "").rstrip() + f"\n\nTrello: {card['shortUrl']}").strip()
            project.update_issue(content["id"], body=body)
        do(f"create card '{content['title']}' from issue", publish)

    print(f"{len(changes)} change(s){' planned' if dry else ''}.")


if __name__ == "__main__":
    main()
