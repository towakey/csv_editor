#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
read_csv.py - CSVファイル読み込みCGI
GETパラメータ: ?file_id=order&username=admin
"""

import json
import csv
import os
import sys
from urllib.parse import parse_qs
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

def send_json(obj):
    body = (json.dumps(obj, ensure_ascii=False) + "\r\n").encode("utf-8")
    headers = (
        "Content-Type: application/json; charset=utf-8\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "Cache-Control: no-store\r\n"
        "Content-Length: {}\r\n"
        "\r\n"
    ).format(len(body)).encode("ascii")
    sys.stdout.buffer.write(headers + body)
    sys.stdout.flush()

def normalize_encoding(enc):
    return ENCODING_MAP.get(enc.lower().replace(" ", ""), enc)

def parse_int(value, default):
    try:
        return int(value)
    except Exception:
        return default

def write_log(username, action, detail=""):
    timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    # setting.json 読み込み
    try:
        with open(SETTING_PATH, mode="r", encoding="utf-8") as f:
            setting = json.load(f)
    except Exception as e:
        send_json({"success": False, "error": "setting.json 読み込み失敗: " + str(e)})
        return

    files = setting.get("files", [])
    users = setting.get("users", [])

    # GETパラメータ解析
    qs = os.environ.get("QUERY_STRING", "")
    parsed = parse_qs(qs, keep_blank_values=True)
    file_id = parsed.get("file_id", [""])[0]
    username = parsed.get("username", [""])[0]
    offset = parse_int(parsed.get("offset", ["0"])[0], 0)
    limit = parse_int(parsed.get("limit", ["1000"])[0], 1000)
    if offset < 0:
        offset = 0
    if limit <= 0:
        limit = 1000
    if limit > 5000:
        limit = 5000

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
        write_log(username, "アクセス拒否", "file_id=" + file_id)
        send_json({"success": False, "error": "このファイルへのアクセス権がありません"})
        return

    # ファイル設定取得
    conf = next((f for f in files if f.get("id") == file_id), None)
    if conf is None:
        send_json({"success": False, "error": "file_id が見つかりません: " + file_id})
        return

    csv_file_path = conf.get("csv_file_path", "")
    read_enc      = normalize_encoding(conf.get("read_encoding", "utf-8"))

    if not os.path.exists(csv_file_path):
        send_json({"success": False, "error": "ファイルが見つかりません: " + csv_file_path})
        return

    try:
        rows    = []
        headers = []
        with open(csv_file_path, mode="r", encoding=read_enc, newline="") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i == 0:
                    headers = row
                else:
                    rows.append(row)

        write_log(username, "ファイルを開く",
                  "id={} name={} rows={}".format(file_id, conf.get("name",""), len(rows)))

        total_rows = len(rows)
        page_rows = rows[offset: offset + limit]
        has_more = (offset + len(page_rows)) < total_rows

        result = {
            "success":          True,
            "headers":          headers,
            "rows":             page_rows,
            "total_rows":       total_rows,
            "offset":           offset,
            "limit":            limit,
            "returned_rows":    len(page_rows),
            "has_more":         has_more,
            "conf_name":        conf.get("name", ""),
            "editable_columns": conf.get("editable_columns", []),
        }
        send_json(result)

    except Exception as e:
        send_json({"success": False, "error": str(e)})

if __name__ == "__main__":
    main()
