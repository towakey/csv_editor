#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
read_history.py - admin専用のCSV変更履歴取得CGI
GETパラメータ: ?username=admin&file_id=order
"""

import csv
import json
import os
import sys
from urllib.parse import parse_qs

from auth_common import is_admin_user, validate_auth_token

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTING_PATH = os.path.join(SCRIPT_DIR, "setting.json")
HISTORY_COLUMNS = [
    "save_id", "changed_at", "username", "file_id", "file_name",
    "action", "row_number", "column_name", "before", "after",
]


def send_json(obj):
    body = (json.dumps(obj, ensure_ascii=False) + "\r\n").encode("utf-8")
    sys.stdout.write("Content-Type: application/json; charset=utf-8\r\n")
    sys.stdout.write("Access-Control-Allow-Origin: *\r\n")
    sys.stdout.write("Cache-Control: no-store\r\n")
    sys.stdout.write("Content-Length: {}\r\n".format(len(body)))
    sys.stdout.write("\r\n")
    sys.stdout.flush()
    sys.stdout.buffer.write(body)
    sys.stdout.flush()


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
    with open(path, mode="r", encoding="utf-8-sig", newline="") as history_file:
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
    admin_user = validate_auth_token(users, username, auth_token)

    if admin_user is None:
        send_json({"success": False, "error": "認証の有効期限が切れました。再ログインしてください"})
        return
    if not is_admin_user(admin_user):
        send_json({"success": False, "error": "作業履歴はadminユーザーのみ閲覧できます"})
        return

    files = setting.get("files", [])
    if file_id:
        files = [conf for conf in files if conf.get("id") == file_id]
        if not files:
            send_json({"success": False, "error": "file_id が見つかりません: " + file_id})
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
