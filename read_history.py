#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
read_history.py - 権限ユーザー向けCSV変更履歴取得CGI
GETパラメータ: ?username=user1&file_id=order
"""

import csv
import json
import os
from urllib.parse import parse_qs

from auth_common import can_view_history, validate_auth_token
from cgi_response import send_json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTING_PATH = os.path.join(SCRIPT_DIR, "setting.json")
HISTORY_COLUMNS = [
    "save_id", "changed_at", "username", "file_id", "file_name",
    "action", "row_number", "column_name", "before", "after",
]


def history_file_path(conf):
    csv_file_path = conf.get("csv_file_path", "")
    return conf.get("history_file_path") or (csv_file_path + ".history.csv")


def restore_history_value(value):
    if value.startswith(("'=", "'+", "'-", "'@")):
        return value[1:]
    return value


def read_history(conf):
    path = history_file_path(conf)
    if not os.path.exists(path):
        return []

    entries = []
    with open(path, mode="r", encoding="utf-8", newline="") as history_file:
        reader = csv.reader(history_file)
        next(reader, None)
        for row in reader:
            row += [""] * (10 - len(row))
            values = [restore_history_value(value) for value in row[:10]]
            entries.append(dict(zip(HISTORY_COLUMNS, values)))
    return entries


def main():
    try:
        with open(SETTING_PATH, mode="r", encoding="utf-8") as setting_file:
            setting = json.load(setting_file)
    except Exception as error:
        send_json({"success": False, "error": "setting.json 読み込み失敗: " + str(error)})
        return

    parsed = parse_qs(os.environ.get("QUERY_STRING", ""), keep_blank_values=True)
    username = parsed.get("username", [""])[0]
    file_id = parsed.get("file_id", [""])[0]
    auth_token = os.environ.get("HTTP_X_AUTH_TOKEN", "")
    users = setting.get("users", [])
    authenticated_user = validate_auth_token(users, username, auth_token)

    if authenticated_user is None:
        send_json({"success": False, "error": "認証の有効期限が切れました。再ログインしてください"})
        return
    if not can_view_history(authenticated_user):
        send_json({"success": False, "error": "作業履歴を閲覧する権限がありません"})
        return

    allowed_file_ids = set(authenticated_user.get("allowed_file_ids", []))
    files = [
        conf for conf in setting.get("files", [])
        if conf.get("id") in allowed_file_ids
    ]
    if file_id:
        files = [conf for conf in files if conf.get("id") == file_id]
        if not files:
            send_json({"success": False, "error": "閲覧可能なfile_idではありません: " + file_id})
            return

    try:
        entries = []
        for conf in files:
            entries.extend(read_history(conf))
        entries.sort(
            key=lambda entry: (entry.get("changed_at", ""), entry.get("save_id", "")),
            reverse=True,
        )
        send_json({"success": True, "entries": entries[:2000]})
    except Exception as error:
        send_json({"success": False, "error": str(error)})


if __name__ == "__main__":
    main()
