#!/usr/bin/env python
# -*- coding: utf-8 -*-

import csv
import json
import os
import shutil
import uuid
from datetime import datetime
from difflib import SequenceMatcher


ENCODING_MAP = {
    "utf-8": "utf-8",
    "utf-8-sig": "utf-8",
    "utf-8-bom": "utf-8",
    "shift-jis": "shift_jis",
    "shift_jis": "shift_jis",
    "sjis": "shift_jis",
    "cp932": "cp932",
    "windows-31j": "cp932",
    "euc-jp": "euc_jp",
    "euc_jp": "euc_jp",
}

NEWLINE_MAP = {
    "crlf": "\r\n",
    "lf": "\n",
    "cr": "\r",
    "\r\n": "\r\n",
    "\n": "\n",
    "\r": "\r",
}


def normalize_encoding(encoding):
    return ENCODING_MAP.get(encoding.lower().replace(" ", ""), encoding)


def normalize_newline(newline):
    key = newline.lower() if newline.lower() in NEWLINE_MAP else newline
    return NEWLINE_MAP.get(key, "\r\n")


def read_csv_data(conf):
    csv_file_path = conf.get("csv_file_path", "")
    headers = []
    rows = []
    if not os.path.exists(csv_file_path):
        return headers, rows

    read_encoding = normalize_encoding(conf.get("read_encoding", "utf-8"))
    with open(
        csv_file_path,
        mode="r",
        encoding=read_encoding,
        newline="",
    ) as current_file:
        reader = csv.reader(current_file)
        for index, row in enumerate(reader):
            if index == 0:
                headers = row
            else:
                rows.append(row)
    return headers, rows


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
                changes.append(("セル変更", new_index + 1, column_name, before, after))

        for index in range(old_start + paired_count, old_end):
            changes.append(("行削除", index + 1, "行全体", row_text(old_rows[index]), ""))
        for index in range(new_start + paired_count, new_end):
            changes.append(("行追加", index + 1, "行全体", "", row_text(new_rows[index])))
    return changes


def collect_changes(old_headers, old_rows, new_headers, new_rows):
    changes = []
    if old_headers != new_headers:
        changes.append(
            ("ヘッダー変更", 0, "ヘッダー", row_text(old_headers), row_text(new_headers))
        )
    changes.extend(compare_rows(new_headers, old_rows, new_rows))
    return changes


def history_file_path(conf):
    csv_file_path = conf.get("csv_file_path", "")
    return conf.get("history_file_path") or (csv_file_path + ".history.csv")


def write_history(conf, username, old_headers, old_rows, new_headers, new_rows):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_id = datetime.now().strftime("%Y%m%d%H%M%S%f") + "-" + uuid.uuid4().hex[:8]
    changes = collect_changes(old_headers, old_rows, new_headers, new_rows)
    if not changes:
        changes.append(("変更なし", 0, "", "", ""))

    path = history_file_path(conf)
    file_exists = os.path.exists(path)
    with open(path, mode="a", encoding="utf-8", newline="") as history_file:
        writer = csv.writer(history_file, lineterminator="\r\n")
        if not file_exists:
            writer.writerow(
                [
                    "保存ID",
                    "変更日時",
                    "ユーザー名",
                    "ファイルID",
                    "ファイル名",
                    "変更種別",
                    "行番号",
                    "列名",
                    "変更前",
                    "変更後",
                ]
            )
        for action, row_number, column_name, before, after in changes:
            writer.writerow(
                [
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
                ]
            )
    return len(changes), path


def apply_csv_change(conf, username, headers, rows):
    csv_file_path = conf.get("csv_file_path", "")
    old_headers, old_rows = read_csv_data(conf)
    write_encoding = normalize_encoding(conf.get("write_encoding", "utf-8"))
    newline = normalize_newline(conf.get("newline", "\r\n"))

    if conf.get("create_backup", True) and os.path.exists(csv_file_path):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        shutil.copy2(csv_file_path, csv_file_path + "." + timestamp + ".bak")

    with open(
        csv_file_path,
        mode="w",
        encoding=write_encoding,
        newline="",
    ) as destination:
        writer = csv.writer(
            destination,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator=newline,
        )
        writer.writerow(headers)
        writer.writerows(rows)

    history_count, history_path = write_history(
        conf,
        username,
        old_headers,
        old_rows,
        headers,
        rows,
    )
    return history_count, history_path
