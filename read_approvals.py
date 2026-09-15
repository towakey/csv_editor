#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
read_approvals.py - 作業者向け確認依頼一覧・下書き取得CGI
GET: ?username=... [&request_id=...]
"""

import os
from urllib.parse import parse_qs

from approval_common import list_requests, load_request, load_setting
from auth_common import is_admin_user, validate_auth_token
from cgi_response import send_json


def main():
    try:
        setting = load_setting()
    except Exception as error:
        send_json({"success": False, "error": "setting.json 読み込み失敗: " + str(error)})
        return

    parsed = parse_qs(os.environ.get("QUERY_STRING", ""), keep_blank_values=True)
    username = parsed.get("username", [""])[0]
    request_id = parsed.get("request_id", [""])[0]
    auth_token = os.environ.get("HTTP_X_AUTH_TOKEN", "")
    user = validate_auth_token(setting.get("users", []), username, auth_token)
    if user is None:
        send_json({"success": False, "error": "認証の有効期限が切れました。再ログインしてください"})
        return

    try:
        if request_id:
            request_data = load_request(setting, request_id)
            if (
                request_data.get("worker_username") != username
                and not is_admin_user(user)
            ):
                send_json({"success": False, "error": "この下書きを閲覧する権限がありません"})
                return
            send_json(
                {
                    "success": True,
                    "request": {
                        "request_id": request_data.get("request_id", ""),
                        "status": request_data.get("status", ""),
                        "file_id": request_data.get("file_id", ""),
                        "headers": request_data.get("headers", []),
                        "rows": request_data.get("rows", []),
                        "rejection_reason": request_data.get("rejection_reason", ""),
                    },
                }
            )
            return

        entries = []
        for request_data in list_requests(setting):
            if (
                request_data.get("worker_username") != username
                and not is_admin_user(user)
            ):
                continue
            entries.append(
                {
                    "request_id": request_data.get("request_id", ""),
                    "status": request_data.get("status", ""),
                    "created_at": request_data.get("created_at", ""),
                    "updated_at": request_data.get("updated_at", ""),
                    "file_id": request_data.get("file_id", ""),
                    "file_name": request_data.get("file_name", ""),
                    "worker_username": request_data.get("worker_username", ""),
                    "rejection_reason": request_data.get("rejection_reason", ""),
                    "notification_error": request_data.get(
                        "approver_notification_error",
                        request_data.get("worker_notification_error", ""),
                    ),
                }
            )
        entries.sort(key=lambda entry: entry.get("created_at", ""), reverse=True)
        send_json({"success": True, "entries": entries[:500]})
    except FileNotFoundError:
        send_json({"success": False, "error": "確認依頼が見つかりません"})
    except Exception as error:
        send_json({"success": False, "error": str(error)})


if __name__ == "__main__":
    main()
