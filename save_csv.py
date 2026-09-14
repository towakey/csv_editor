#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
save_csv.py - CSVファイル保存CGI
POSTボディ: JSON { "file_id": "order", "username": "admin", "headers": [...], "rows": [[...]] }
"""

import json
import csv
import os
import sys
import shutil
import uuid
from difflib import SequenceMatcher
from datetime import datetime

from auth_common import validate_auth_token

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
SETTING_PATH = os.path.join(SCRIPT_DIR, "setting.json")
LOG_PATH     = os.path.join(SCRIPT_DIR, "log.csv")

ENCODING_MAP = {
    "utf-8":       "utf-8",
    "utf-8-sig":   "utf-8",
    "utf-8-bom":   "utf-8",
    "shift-jis":   "shift_jis",
    "shift_jis":   "shift_jis",
    "sjis":        "shift_jis",
    "cp932":       "cp932",
    "windows-31j": "cp932",
    "euc-jp":      "euc_jp",
    "euc_jp":      "euc_jp",
}

NEWLINE_MAP = {
    "crlf": "\r\n", "lf": "\n", "cr": "\r",
    "\r\n": "\r\n", "\n": "\n", "\r": "\r",
}

def send_headers():
    sys.stdout.write("Content-Type: application/json; charset=utf-8\r\n")
    sys.stdout.write("Access-Control-Allow-Origin: *\r\n")
    sys.stdout.write("\r\n")
    sys.stdout.flush()

def send_json(obj):
    body = json.dumps(obj, ensure_ascii=False) + "\r\n"
    sys.stdout.buffer.write(body.encode("utf-8"))
    sys.stdout.flush()

def normalize_encoding(enc):
    return ENCODING_MAP.get(enc.lower().replace(" ", ""), enc)

def normalize_newline(nl):
    return NEWLINE_MAP.get(nl.lower() if nl.lower() in NEWLINE_MAP else nl, "\r\n")

def write_log(username, action, detail=""):
    timestamp   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.exists(LOG_PATH)
    try:
        with open(LOG_PATH, mode="a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, lineterminator="\r\n")
            if not file_exists:
                writer.writerow(["日時", "ユーザー名", "操作", "詳細"])
            writer.writerow([timestamp, username, action, detail])
    except Exception:
        pass

def history_file_path(conf):
    csv_file_path = conf.get("csv_file_path", "")
    return conf.get("history_file_path") or (csv_file_path + ".history.csv")

def safe_history_value(value):
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text

def row_text(row):
    return json.dumps(row, ensure_ascii=False)

def compare_rows(headers, old_rows, new_rows):
    changes = []
    matcher = SequenceMatcher(
        None,
        [tuple(row) for row in old_rows],
        [tuple(row) for row in new_rows],
        autojunk=False,
    )

    for operation, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if operation == "equal":
            continue

        if operation == "delete":
            for index in range(old_start, old_end):
                changes.append(("行削除", index + 1, "行全体", row_text(old_rows[index]), ""))
            continue

        if operation == "insert":
            for index in range(new_start, new_end):
                changes.append(("行追加", index + 1, "行全体", "", row_text(new_rows[index])))
            continue

        paired_count = min(old_end - old_start, new_end - new_start)
        for offset in range(paired_count):
            old_index = old_start + offset
            new_index = new_start + offset
            old_row = old_rows[old_index]
            new_row = new_rows[new_index]
            column_count = max(len(headers), len(old_row), len(new_row))
            for column_index in range(column_count):
                before = old_row[column_index] if column_index < len(old_row) else ""
                after = new_row[column_index] if column_index < len(new_row) else ""
                if before == after:
                    continue
                column_name = (
                    headers[column_index]
                    if column_index < len(headers)
                    else "列{}".format(column_index + 1)
                )
                changes.append(
                    ("セル変更", new_index + 1, column_name, before, after)
                )

        for index in range(old_start + paired_count, old_end):
            changes.append(("行削除", index + 1, "行全体", row_text(old_rows[index]), ""))
        for index in range(new_start + paired_count, new_end):
            changes.append(("行追加", index + 1, "行全体", "", row_text(new_rows[index])))

    return changes

def write_history(conf, username, old_headers, old_rows, new_headers, new_rows):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_id = datetime.now().strftime("%Y%m%d%H%M%S%f") + "-" + uuid.uuid4().hex[:8]
    changes = []

    if old_headers != new_headers:
        changes.append(
            ("ヘッダー変更", 0, "ヘッダー", row_text(old_headers), row_text(new_headers))
        )
    changes.extend(compare_rows(new_headers, old_rows, new_rows))
    if not changes:
        changes.append(("変更なし", 0, "", "", ""))

    path = history_file_path(conf)
    file_exists = os.path.exists(path)
    with open(path, mode="a", encoding="utf-8", newline="") as history_file:
        writer = csv.writer(history_file, lineterminator="\r\n")
        if not file_exists:
            writer.writerow([
                "保存ID", "変更日時", "ユーザー名", "ファイルID", "ファイル名",
                "変更種別", "行番号", "列名", "変更前", "変更後",
            ])
        for action, row_number, column_name, before, after in changes:
            writer.writerow([
                save_id,
                timestamp,
                safe_history_value(username),
                safe_history_value(conf.get("id", "")),
                safe_history_value(conf.get("name", "")),
                action,
                row_number or "",
                safe_history_value(column_name),
                safe_history_value(before),
                safe_history_value(after),
            ])

    return len(changes), path

def main():
    send_headers()

    method = os.environ.get("REQUEST_METHOD", "GET").upper()
    if method == "OPTIONS":
        send_json({"success": True})
        return
    if method != "POST":
        send_json({"success": False, "error": "POST のみ受け付けます"})
        return

    # setting.json 読み込み
    try:
        with open(SETTING_PATH, mode="r", encoding="utf-8") as f:
            setting = json.load(f)
    except Exception as e:
        send_json({"success": False, "error": "setting.json 読み込み失敗: " + str(e)})
        return

    files = setting.get("files", [])
    users = setting.get("users", [])

    try:
        content_length = int(os.environ.get("CONTENT_LENGTH", 0))
        if content_length <= 0:
            send_json({"success": False, "error": "データが空です"})
            return

        body    = sys.stdin.buffer.read(content_length)
        data    = json.loads(body.decode("utf-8"))

        file_id  = data.get("file_id",  "")
        username = data.get("username", "")
        auth_token = os.environ.get("HTTP_X_AUTH_TOKEN", "")
        headers  = data.get("headers",  [])
        rows     = data.get("rows",     [])

        if not file_id or not username:
            send_json({"success": False, "error": "file_id と username は必須です"})
            return

        # ユーザーの許可チェック
        matched_user = validate_auth_token(users, username, auth_token)
        if matched_user is None:
            send_json({"success": False, "error": "認証の有効期限が切れました。再ログインしてください"})
            return

        allowed_ids = set(matched_user.get("allowed_file_ids", []))
        if file_id not in allowed_ids:
            write_log(username, "保存アクセス拒否", "file_id=" + file_id)
            send_json({"success": False, "error": "このファイルへの書き込み権限がありません"})
            return

        # ファイル設定取得
        conf = next((f for f in files if f.get("id") == file_id), None)
        if conf is None:
            send_json({"success": False, "error": "file_id が見つかりません: " + file_id})
            return

        csv_file_path = conf.get("csv_file_path", "")
        write_enc     = normalize_encoding(conf.get("write_encoding", "utf-8"))
        newline       = normalize_newline(conf.get("newline", "\r\n"))
        create_backup = conf.get("create_backup", True)

        if not headers:
            send_json({"success": False, "error": "ヘッダーがありません"})
            return

        old_headers = []
        old_rows = []
        if os.path.exists(csv_file_path):
            read_enc = normalize_encoding(conf.get("read_encoding", "utf-8"))
            with open(csv_file_path, mode="r", encoding=read_enc, newline="") as current_file:
                reader = csv.reader(current_file)
                for index, row in enumerate(reader):
                    if index == 0:
                        old_headers = row
                    else:
                        old_rows.append(row)

        # バックアップ
        if create_backup and os.path.exists(csv_file_path):
            timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = csv_file_path + "." + timestamp + ".bak"
            shutil.copy2(csv_file_path, backup_path)

        # CSV書き込み
        with open(csv_file_path, mode="w", encoding=write_enc, newline="") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL, lineterminator=newline)
            writer.writerow(headers)
            for row in rows:
                writer.writerow(row)

        history_count, history_path = write_history(
            conf, username, old_headers, old_rows, headers, rows
        )

        write_log(username, "ファイルを保存",
                  "id={} name={} rows={} changes={}".format(
                      file_id, conf.get("name",""), len(rows), history_count
                  ))

        send_json({
            "success":    True,
            "message":    "保存しました ({} 行・履歴 {} 件)".format(len(rows), history_count),
            "saved_rows": len(rows),
            "history_count": history_count,
        })

    except json.JSONDecodeError as e:
        send_json({"success": False, "error": "JSONパースエラー: " + str(e)})
    except Exception as e:
        send_json({"success": False, "error": str(e)})

if __name__ == "__main__":
    main()
