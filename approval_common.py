#!/usr/bin/env python
# -*- coding: utf-8 -*-

import csv
import hashlib
import json
import os
import smtplib
import ssl
import tempfile
from contextlib import contextmanager
from datetime import datetime
from email.message import EmailMessage
from urllib.parse import urlencode


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTING_PATH = os.path.join(SCRIPT_DIR, "setting.json")
LOG_PATH = os.path.join(SCRIPT_DIR, "log.csv")


def load_setting():
    with open(SETTING_PATH, mode="r", encoding="utf-8") as setting_file:
        return json.load(setting_file)


def find_user(setting, username):
    return next(
        (user for user in setting.get("users", []) if user.get("username") == username),
        None,
    )


def find_file(setting, file_id):
    return next(
        (conf for conf in setting.get("files", []) if conf.get("id") == file_id),
        None,
    )


def approval_directory(setting):
    configured = setting.get("approval", {}).get("draft_directory", "approval_drafts")
    if os.path.isabs(configured):
        return configured
    return os.path.join(SCRIPT_DIR, configured)


def request_path(setting, request_id):
    safe_id = "".join(char for char in request_id if char.isalnum() or char in "-_")
    if safe_id != request_id or not safe_id:
        raise ValueError("確認依頼IDが不正です")
    return os.path.join(approval_directory(setting), safe_id + ".json")


def load_request(setting, request_id):
    with open(request_path(setting, request_id), mode="r", encoding="utf-8") as request_file:
        return json.load(request_file)


def save_request(setting, request_data):
    directory = approval_directory(setting)
    os.makedirs(directory, exist_ok=True)
    destination = request_path(setting, request_data["request_id"])
    file_descriptor, temporary_path = tempfile.mkstemp(
        dir=directory,
        prefix=request_data["request_id"] + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(file_descriptor, mode="w", encoding="utf-8") as temporary_file:
            json.dump(request_data, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
        os.replace(temporary_path, destination)
    except Exception:
        try:
            os.remove(temporary_path)
        except OSError:
            pass
        raise


def list_requests(setting):
    directory = approval_directory(setting)
    if not os.path.isdir(directory):
        return []

    requests = []
    for filename in os.listdir(directory):
        if not filename.endswith(".json"):
            continue
        try:
            with open(
                os.path.join(directory, filename),
                mode="r",
                encoding="utf-8",
            ) as request_file:
                requests.append(json.load(request_file))
        except (OSError, ValueError):
            continue
    return requests


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def file_fingerprint(path):
    digest = hashlib.sha256()
    try:
        with open(path, mode="rb") as source_file:
            while True:
                chunk = source_file.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except FileNotFoundError:
        return ""
    return digest.hexdigest()


def build_review_url(setting, request_id, token):
    base_url = setting.get("approval", {}).get("review_url", "").strip()
    if not base_url:
        host = os.environ.get("HTTP_X_FORWARDED_HOST") or os.environ.get("HTTP_HOST", "")
        forwarded_proto = os.environ.get("HTTP_X_FORWARDED_PROTO", "").split(",")[0].strip()
        scheme = forwarded_proto or (
            "https" if os.environ.get("HTTPS", "").lower() in ("on", "1") else "http"
        )
        script_name = os.environ.get("SCRIPT_NAME", "")
        if not host or not script_name:
            raise ValueError("setting.json の approval.review_url が未設定です")
        base_url = (
            scheme
            + "://"
            + host
            + script_name.rsplit("/", 1)[0]
            + "/approval_review.py"
        )
    separator = "&" if "?" in base_url else "?"
    return base_url + separator + urlencode({"id": request_id, "token": token})


def resolve_approvers(setting, file_conf):
    usernames = file_conf.get("approver_usernames", [])
    approvers = []
    missing = []
    for username in usernames:
        user = find_user(setting, username)
        if user is None or not user.get("email"):
            missing.append(username)
            continue
        approvers.append(user)
    if missing:
        raise ValueError(
            "承認者ユーザーまたはメールアドレスが未設定です: " + ", ".join(missing)
        )
    if not approvers:
        raise ValueError("このファイルには approver_usernames が設定されていません")
    return approvers


def send_email(setting, recipients, subject, body):
    smtp = setting.get("approval", {}).get("smtp", {})
    host = os.environ.get("CSV_EDITOR_SMTP_HOST", smtp.get("host", "")).strip()
    from_address = os.environ.get(
        "CSV_EDITOR_SMTP_FROM",
        smtp.get("from_address", ""),
    ).strip()
    if not host or not from_address:
        raise ValueError("setting.json の approval.smtp.host/from_address が未設定です")

    message = EmailMessage()
    message["From"] = from_address
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)

    port = int(smtp.get("port", 465 if smtp.get("use_ssl") else 587))
    timeout = int(smtp.get("timeout_seconds", 20))
    username = os.environ.get("CSV_EDITOR_SMTP_USERNAME", smtp.get("username", ""))
    password_environment = smtp.get("password_env", "CSV_EDITOR_SMTP_PASSWORD")
    password = os.environ.get(password_environment, smtp.get("password", ""))

    if smtp.get("use_ssl"):
        client = smtplib.SMTP_SSL(
            host,
            port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
    else:
        client = smtplib.SMTP(host, port, timeout=timeout)

    try:
        if smtp.get("starttls"):
            client.starttls(context=ssl.create_default_context())
        if username:
            client.login(username, password)
        client.send_message(message)
    finally:
        try:
            client.quit()
        except smtplib.SMTPException:
            client.close()


def write_log(username, action, detail=""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.exists(LOG_PATH)
    try:
        with open(LOG_PATH, mode="a", encoding="utf-8", newline="") as log_file:
            writer = csv.writer(log_file, lineterminator="\r\n")
            if not file_exists:
                writer.writerow(["日時", "ユーザー名", "操作", "詳細"])
            writer.writerow([timestamp, username, action, detail])
    except Exception:
        pass


@contextmanager
def named_lock(setting, lock_name):
    directory = approval_directory(setting)
    os.makedirs(directory, exist_ok=True)
    safe_name = "".join(
        char for char in lock_name if char.isalnum() or char in "-_"
    )
    if safe_name != lock_name or not safe_name:
        raise ValueError("ロック名が不正です")
    lock_path = os.path.join(directory, "." + safe_name + ".lock")
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError("この処理対象は別の処理で更新中です")
    try:
        os.close(descriptor)
        yield
    finally:
        try:
            os.remove(lock_path)
        except OSError:
            pass


def request_lock(setting, request_id):
    return named_lock(setting, "request-" + request_id)


def file_lock(setting, file_id):
    return named_lock(setting, "file-" + file_id)
