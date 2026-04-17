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
from datetime import datetime

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
SETTING_PATH = os.path.join(SCRIPT_DIR, "setting.json")
LOG_PATH     = os.path.join(SCRIPT_DIR, "log.csv")

ENCODING_MAP = {
    "utf-8":       "utf-8",
    "utf-8-sig":   "utf-8-sig",
    "utf-8-bom":   "utf-8-sig",
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
        with open(LOG_PATH, mode="a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, lineterminator="\r\n")
            if not file_exists:
                writer.writerow(["日時", "ユーザー名", "操作", "詳細"])
            writer.writerow([timestamp, username, action, detail])
    except Exception:
        pass

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
        headers  = data.get("headers",  [])
        rows     = data.get("rows",     [])

        if not file_id or not username:
            send_json({"success": False, "error": "file_id と username は必須です"})
            return

        # ユーザーの許可チェック
        matched_user = next((u for u in users if u.get("username") == username), None)
        if matched_user is None:
            send_json({"success": False, "error": "ユーザーが存在しません"})
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

        write_log(username, "ファイルを保存",
                  "id={} name={} rows={}".format(file_id, conf.get("name",""), len(rows)))

        send_json({
            "success":    True,
            "message":    "保存しました ({} 行)".format(len(rows)),
            "saved_rows": len(rows),
        })

    except json.JSONDecodeError as e:
        send_json({"success": False, "error": "JSONパースエラー: " + str(e)})
    except Exception as e:
        send_json({"success": False, "error": str(e)})

if __name__ == "__main__":
    main()
