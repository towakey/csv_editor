#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
approval_review.py - メールリンクから変更内容を確認・承認・却下するCGI
"""

import html
import os
import sys
from datetime import datetime
from urllib.parse import parse_qs

from approval_common import (
    file_lock,
    file_fingerprint,
    find_file,
    load_request,
    load_setting,
    request_lock,
    save_request,
    send_email,
    token_hash,
    write_log,
)
from csv_storage import apply_csv_change, collect_changes, read_csv_data


STATUS_LABELS = {
    "pending": "確認待ち",
    "approved": "承認済み",
    "rejected": "却下済み",
}


def send_html(title, content, status="200 OK"):
    body = (
        "<!DOCTYPE html><html lang=\"ja\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>{}</title><style>"
        "body{{font-family:Meiryo,sans-serif;background:#f1f5f9;color:#1e293b;"
        "margin:0;padding:24px}}"
        "main{{max-width:1100px;margin:auto;background:#fff;border-radius:12px;padding:24px;"
        "box-shadow:0 4px 18px rgba(0,0,0,.1)}}h1{{font-size:22px;margin-top:0}}"
        ".meta{{display:grid;grid-template-columns:140px 1fr;gap:8px;padding:14px;"
        "background:#f8fafc;border-radius:8px;margin-bottom:18px}}"
        ".warning{{padding:12px;background:#fff7ed;border:1px solid #fdba74;color:#9a3412;"
        "border-radius:8px;margin:14px 0}}.message{{padding:14px;border-radius:8px;margin:14px 0}}"
        ".success{{background:#f0fdf4;border:1px solid #86efac;color:#166534}}"
        ".error{{background:#fef2f2;border:1px solid #fca5a5;color:#991b1b}}"
        "table{{width:100%;border-collapse:collapse;font-size:13px;margin:16px 0}}"
        "th,td{{border:1px solid #e2e8f0;padding:8px;text-align:left;vertical-align:top}}"
        "th{{background:#f8fafc}}td.value{{white-space:pre-wrap;"
        "overflow-wrap:anywhere;max-width:340px}}"
        "form{{display:inline}}button{{border:0;border-radius:8px;padding:10px 22px;color:#fff;"
        "font-weight:700;cursor:pointer;margin-right:8px}}.approve{{background:#16a34a}}"
        ".reject{{background:#dc2626}}textarea{{width:100%;min-height:90px;padding:10px;"
        "border:1px solid #cbd5e1;border-radius:8px;margin:8px 0 12px;box-sizing:border-box}}"
        "@media(max-width:640px){{body{{padding:10px}}main{{padding:16px}}"
        ".meta{{grid-template-columns:1fr}}table{{display:block;overflow:auto}}}}"
        "</style></head><body><main>{}</main></body></html>"
    ).format(html.escape(title), content).encode("utf-8")
    headers = (
        "Status: {}\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Cache-Control: no-store\r\n"
        "X-Content-Type-Options: nosniff\r\n"
        "Referrer-Policy: no-referrer\r\n"
        "Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; "
        "form-action 'self'\r\n"
        "Content-Length: {}\r\n\r\n"
    ).format(status, len(body)).encode("ascii")
    output = getattr(sys.stdout, "buffer", sys.stdout)
    output.write(headers + body)
    output.flush()


def load_authorized_request(setting, request_id, token):
    request_data = load_request(setting, request_id)
    if not token or token_hash(token) != request_data.get("token_hash"):
        raise PermissionError("確認リンクが無効です")
    return request_data


def request_parameters():
    method = os.environ.get("REQUEST_METHOD", "GET").upper()
    if method == "POST":
        content_length = int(os.environ.get("CONTENT_LENGTH", 0))
        raw = sys.stdin.buffer.read(content_length).decode("utf-8")
        return method, parse_qs(raw, keep_blank_values=True)
    return method, parse_qs(os.environ.get("QUERY_STRING", ""), keep_blank_values=True)


def render_changes(request_data, file_conf):
    old_headers = request_data.get("source_headers")
    old_rows = request_data.get("source_rows")
    if old_headers is None or old_rows is None:
        old_headers, old_rows = read_csv_data(file_conf)
    changes = collect_changes(
        old_headers,
        old_rows,
        request_data.get("headers", []),
        request_data.get("rows", []),
    )
    if not changes:
        return "<p>変更はありません。</p>"

    rows = []
    for action, row_number, column_name, before, after in changes:
        rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td class=\"value\">{}</td>"
            "<td class=\"value\">{}</td></tr>".format(
                html.escape(str(action)),
                html.escape(str(row_number or "—")),
                html.escape(str(column_name or "—")),
                html.escape(str(before if before != "" else "（空欄）")),
                html.escape(str(after if after != "" else "（空欄）")),
            )
        )
    return (
        "<h2>変更内容（{}件）</h2><table><thead><tr><th>種別</th><th>行</th>"
        "<th>列</th><th>変更前</th><th>変更後</th></tr></thead><tbody>{}</tbody></table>"
    ).format(len(changes), "".join(rows))


def render_review(setting, request_data, token, message=""):
    file_conf = find_file(setting, request_data.get("file_id", ""))
    if file_conf is None:
        raise ValueError("対象ファイルの設定が見つかりません")

    status = request_data.get("status", "")
    stale = (
        file_fingerprint(file_conf.get("csv_file_path", ""))
        != request_data.get("source_fingerprint", "")
    )
    content = "<h1>CSV変更の確認</h1>"
    if message:
        content += message
    content += (
        "<div class=\"meta\"><strong>状態</strong><span>{}</span>"
        "<strong>対象ファイル</strong><span>{}</span>"
        "<strong>作業者</strong><span>{}</span>"
        "<strong>依頼日時</strong><span>{}</span></div>"
    ).format(
        html.escape(STATUS_LABELS.get(status, status)),
        html.escape(request_data.get("file_name", "")),
        html.escape(request_data.get("worker_display_name", "")),
        html.escape(request_data.get("created_at", "")),
    )
    if stale and status == "pending":
        content += (
            "<div class=\"warning\">依頼後に実ファイルが変更されています。"
            "この依頼は承認できません。作業者に再依頼を依頼してください。</div>"
        )
    content += render_changes(request_data, file_conf)

    if status == "pending":
        hidden = (
            '<input type="hidden" name="id" value="{}">'
            '<input type="hidden" name="token" value="{}">'
        ).format(
            html.escape(request_data["request_id"], quote=True),
            html.escape(token, quote=True),
        )
        if not stale:
            content += (
                '<form method="post">{}<input type="hidden" name="action" value="approve">'
                '<button class="approve" type="submit">承認</button></form>'
            ).format(hidden)
        content += (
            '<h2>却下する場合</h2><form method="post">{}'
            '<input type="hidden" name="action" value="reject">'
            '<textarea name="reason" required placeholder="却下理由を入力してください"></textarea>'
            '<button class="reject" type="submit">却下</button></form>'
        ).format(hidden)
    elif status == "rejected":
        content += "<div class=\"message error\">却下理由: {}</div>".format(
            html.escape(request_data.get("rejection_reason", ""))
        )
    return content


def notify_worker(setting, request_data, decision):
    worker_email = request_data.get("worker_email", "")
    if not worker_email:
        raise ValueError("作業者のメールアドレスが未設定です")

    if decision == "approved":
        subject = "【CSVエディタ】{} の変更が承認されました".format(
            request_data.get("file_name", "")
        )
        body = (
            "確認依頼が承認され、実ファイルへ反映されました。\n\n"
            "対象ファイル: {}\n依頼ID: {}"
        ).format(request_data.get("file_name", ""), request_data.get("request_id", ""))
    else:
        subject = "【CSVエディタ】{} の変更が却下されました".format(
            request_data.get("file_name", "")
        )
        body = (
            "確認依頼が却下されました。変更内容は下書きとして残っています。\n\n"
            "対象ファイル: {}\n却下理由: {}\n依頼ID: {}"
        ).format(
            request_data.get("file_name", ""),
            request_data.get("rejection_reason", ""),
            request_data.get("request_id", ""),
        )
    send_email(setting, [worker_email], subject, body)


def process_decision(setting, request_id, token, action, reason):
    with request_lock(setting, request_id):
        request_data = load_authorized_request(setting, request_id, token)
        if request_data.get("status") != "pending":
            return request_data, '<div class="message error">この依頼は処理済みです。</div>'

        file_conf = find_file(setting, request_data.get("file_id", ""))
        if file_conf is None:
            raise ValueError("対象ファイルの設定が見つかりません")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if action == "approve":
            with file_lock(setting, request_data.get("file_id", "")):
                current_fingerprint = file_fingerprint(file_conf.get("csv_file_path", ""))
                if current_fingerprint != request_data.get("source_fingerprint", ""):
                    raise ValueError("依頼後に実ファイルが変更されたため承認できません")
                history_count, unused_history_path = apply_csv_change(
                    file_conf,
                    request_data.get("worker_username", ""),
                    request_data.get("headers", []),
                    request_data.get("rows", []),
                )
            request_data["status"] = "approved"
            request_data["approved_at"] = now
            request_data["updated_at"] = now
            request_data["history_count"] = history_count
            message = '<div class="message success">承認し、実ファイルへ反映しました。</div>'
            log_action = "確認依頼を承認"
        elif action == "reject":
            if not reason.strip():
                raise ValueError("却下理由を入力してください")
            request_data["status"] = "rejected"
            request_data["rejected_at"] = now
            request_data["updated_at"] = now
            request_data["rejection_reason"] = reason.strip()
            message = (
                '<div class="message success">却下しました。'
                "変更内容は作業者の下書きとして保持されます。</div>"
            )
            log_action = "確認依頼を却下"
        else:
            raise ValueError("操作が不正です")

        save_request(setting, request_data)
        write_log(
            request_data.get("worker_username", ""),
            log_action,
            "id={} file_id={}".format(
                request_data.get("request_id", ""),
                request_data.get("file_id", ""),
            ),
        )
        try:
            notify_worker(setting, request_data, request_data["status"])
            request_data["worker_notified_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_request(setting, request_data)
        except Exception as error:
            request_data["worker_notification_error"] = str(error)
            save_request(setting, request_data)
            message += (
                '<div class="warning">作業者への通知メール送信に失敗しました: {}</div>'
            ).format(html.escape(str(error)))
        return request_data, message


def main():
    try:
        setting = load_setting()
        method, parameters = request_parameters()
        request_id = parameters.get("id", [""])[0]
        token = parameters.get("token", [""])[0]
        if not request_id or not token:
            raise PermissionError("確認リンクが不正です")

        message = ""
        if method == "POST":
            request_data, message = process_decision(
                setting,
                request_id,
                token,
                parameters.get("action", [""])[0],
                parameters.get("reason", [""])[0],
            )
        elif method == "GET":
            request_data = load_authorized_request(setting, request_id, token)
        else:
            send_html(
                "操作エラー",
                '<div class="message error">未対応の操作です。</div>',
                "405 Method Not Allowed",
            )
            return
        send_html("CSV変更の確認", render_review(setting, request_data, token, message))
    except PermissionError as error:
        send_html(
            "確認リンクエラー",
            '<div class="message error">{}</div>'.format(html.escape(str(error))),
            "403 Forbidden",
        )
    except FileNotFoundError:
        send_html(
            "確認依頼エラー",
            '<div class="message error">確認依頼が見つかりません。</div>',
            "404 Not Found",
        )
    except Exception as error:
        send_html(
            "処理エラー",
            '<div class="message error">{}</div>'.format(html.escape(str(error))),
            "400 Bad Request",
        )


if __name__ == "__main__":
    main()
