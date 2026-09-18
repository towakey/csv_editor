#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
request_approval.py - CSV変更の確認依頼CGI
POST: { "file_id": "...", "username": "...", "headers": [...], "rows": [[...]] }
"""

import json
import os
import secrets
import sys
import uuid
from datetime import datetime

from approval_common import (
    build_review_url,
    file_fingerprint,
    find_file,
    load_setting,
    resolve_approvers,
    save_request,
    send_email,
    token_hash,
    write_log,
)
from auth_common import validate_auth_token
from cgi_response import send_json
from csv_storage import collect_changes, read_csv_data


def main():
    draft_saved = False
    method = os.environ.get("REQUEST_METHOD", "GET").upper()
    if method == "OPTIONS":
        send_json({"success": True})
        return
    if method != "POST":
        send_json({"success": False, "error": "POST のみ受け付けます"})
        return

    try:
        setting = load_setting()
        content_length = int(os.environ.get("CONTENT_LENGTH", 0))
        if content_length <= 0:
            send_json({"success": False, "error": "データが空です"})
            return
        data = json.loads(sys.stdin.buffer.read(content_length).decode("utf-8"))
    except Exception as error:
        send_json({"success": False, "error": "リクエスト解析失敗: " + str(error)})
        return

    file_id = data.get("file_id", "")
    username = data.get("username", "")
    headers = data.get("headers", [])
    rows = data.get("rows", [])
    auth_token = os.environ.get("HTTP_X_AUTH_TOKEN", "")
    users = setting.get("users", [])
    worker = validate_auth_token(users, username, auth_token)

    if worker is None:
        send_json({"success": False, "error": "認証の有効期限が切れました。再ログインしてください"})
        return
    if file_id not in set(worker.get("allowed_file_ids", [])):
        write_log(username, "確認依頼アクセス拒否", "file_id=" + file_id)
        send_json({"success": False, "error": "このファイルへの書き込み権限がありません"})
        return
    if (
        not isinstance(headers, list)
        or not headers
        or not isinstance(rows, list)
        or any(not isinstance(row, list) for row in rows)
    ):
        send_json({"success": False, "error": "ヘッダーまたは行データが不正です"})
        return

    file_conf = find_file(setting, file_id)
    if file_conf is None:
        send_json({"success": False, "error": "file_id が見つかりません: " + file_id})
        return
    if not worker.get("email"):
        send_json({"success": False, "error": "作業者のメールアドレスが未設定です"})
        return

    try:
        approvers = [
            approver
            for approver in resolve_approvers(setting, file_conf)
            if approver.get("username") != username
        ]
        if not approvers:
            raise ValueError("作業者本人以外の承認者を設定してください")
        source_headers, source_rows = read_csv_data(file_conf)
        if not collect_changes(source_headers, source_rows, headers, rows):
            raise ValueError("変更内容がありません")
        request_id = datetime.now().strftime("%Y%m%d%H%M%S%f") + "-" + uuid.uuid4().hex[:8]
        token = secrets.token_urlsafe(32)
        review_url = build_review_url(setting, request_id, token)
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        request_data = {
            "request_id": request_id,
            "status": "pending",
            "created_at": created_at,
            "updated_at": created_at,
            "file_id": file_id,
            "file_name": file_conf.get("name", file_id),
            "worker_username": username,
            "worker_display_name": worker.get("display_name", username),
            "worker_email": worker.get("email", ""),
            "approver_usernames": [approver.get("username", "") for approver in approvers],
            "approver_emails": [approver["email"] for approver in approvers],
            "token_hash": token_hash(token),
            "source_fingerprint": file_fingerprint(file_conf.get("csv_file_path", "")),
            "source_headers": source_headers,
            "source_rows": source_rows,
            "headers": headers,
            "rows": rows,
            "rejection_reason": "",
        }
        save_request(setting, request_data)
        draft_saved = True

        subject = "【CSVエディタ】{} の確認依頼".format(request_data["file_name"])
        body = (
            "{} さんからCSV変更の確認依頼が届きました。\n\n"
            "対象ファイル: {}\n"
            "依頼日時: {}\n"
            "確認・承認URL:\n{}\n\n"
            "心当たりがない場合はこのメールを破棄してください。"
        ).format(
            request_data["worker_display_name"],
            request_data["file_name"],
            created_at,
            review_url,
        )
        try:
            send_email(setting, request_data["approver_emails"], subject, body)
        except Exception as error:
            request_data["approver_notification_error"] = str(error)
            save_request(setting, request_data)
            raise
        write_log(username, "確認依頼", "id={} file_id={}".format(request_id, file_id))
        send_json(
            {
                "success": True,
                "request_id": request_id,
                "message": "確認依頼を送信しました。承認されるまで実ファイルは変更されません",
            }
        )
    except Exception as error:
        write_log(username, "確認依頼失敗", "file_id={} error={}".format(file_id, error))
        send_json(
            {
                "success": False,
                "draft_saved": draft_saved,
                "request_id": request_id if "request_id" in locals() else "",
                "error": str(error),
            }
        )


if __name__ == "__main__":
    main()
