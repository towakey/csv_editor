#!/usr/bin/env python
# -*- coding: utf-8 -*-

import base64
import hashlib
import hmac
import time

TOKEN_LIFETIME_SECONDS = 8 * 60 * 60


def is_admin_user(user):
    return user.get("username") == "admin" or user.get("role") == "admin"


def create_auth_token(user):
    expires_at = int(time.time()) + TOKEN_LIFETIME_SECONDS
    payload = "{}|{}".format(user.get("username", ""), expires_at)
    signature = hmac.new(
        _token_key(user),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    encoded_payload = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
    return encoded_payload.rstrip("=") + "." + signature


def validate_auth_token(users, username, token):
    user = next((item for item in users if item.get("username") == username), None)
    if user is None or not token:
        return None

    try:
        encoded_payload, signature = token.split(".", 1)
        padding = "=" * (-len(encoded_payload) % 4)
        payload = base64.urlsafe_b64decode(encoded_payload + padding).decode("utf-8")
        token_username, expires_at_text = payload.rsplit("|", 1)
        expires_at = int(expires_at_text)
    except (TypeError, ValueError):
        return None

    expected_signature = hmac.new(
        _token_key(user),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return None
    if token_username != username or expires_at < int(time.time()):
        return None
    return user


def _token_key(user):
    password = user.get("password", "")
    return hashlib.sha256(
        ("csv-editor-auth:" + password).encode("utf-8")
    ).digest()
