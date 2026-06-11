#!/usr/bin/env python3
"""
Trello sync helper for the backlog skill.

Usage:
  python3 trello.py card-create "feature description" [project]
  python3 trello.py card-move <card_id> <list_name>   # backlog|in_progress|test|done|blocked
  python3 trello.py card-find "feature description"
  python3 trello.py card-comment <card_id> "message"

Credentials loaded from AWS Secrets Manager: backlog/trello
"""
import sys
import json
import subprocess
import urllib.request
import urllib.parse

def get_creds():
    import os
    env = {k: v for k, v in os.environ.items() if k != "AWS_PROFILE"}
    env["AWS_DEFAULT_REGION"] = "us-east-1"
    # Use rtk proxy to bypass RTK rewriting which breaks JSON parse
    result = subprocess.run(
        ["aws", "secretsmanager", "get-secret-value",
         "--secret-id", "backlog/trello",
         "--query", "SecretString", "--output", "text",
         "--region", "us-east-1"],
        capture_output=True, text=True, env=env
    )
    return json.loads(result.stdout.strip())

def api(method, path, data=None):
    creds = get_creds()
    key, token = creds["api_key"], creds["token"]
    sep = "&" if "?" in path else "?"
    url = f"https://api.trello.com/1{path}{sep}key={key}&token={token}"
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def card_create(name, project=None):
    creds = get_creds()
    list_id = creds["lists"]["backlog"]
    desc = f"Project: {project}" if project else ""
    card = api("POST", "/cards", {"name": name, "idList": list_id, "desc": desc})
    print(card["id"])

def card_move(card_id, list_name):
    creds = get_creds()
    list_id = creds["lists"][list_name]
    api("PUT", f"/cards/{card_id}", {"idList": list_id})
    print(f"moved to {list_name}")

def card_find(name):
    creds = get_creds()
    board_id = creds["board_id"]
    cards = api("GET", f"/boards/{board_id}/cards?fields=id,name,idList")
    name_lower = name.lower()
    for card in cards:
        if name_lower in card["name"].lower():
            print(card["id"], card["name"])
            return
    print("NOT_FOUND")

def card_comment(card_id, text):
    api("POST", f"/cards/{card_id}/actions/comments", {"text": text})
    print("commented")

cmd = sys.argv[1]
if cmd == "card-create":
    card_create(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
elif cmd == "card-move":
    card_move(sys.argv[2], sys.argv[3])
elif cmd == "card-find":
    card_find(sys.argv[2])
elif cmd == "card-comment":
    card_comment(sys.argv[2], sys.argv[3])
