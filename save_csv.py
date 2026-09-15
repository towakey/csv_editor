#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
save_csv.py - 直接保存を禁止する互換CGI
"""

import os

from cgi_response import send_json


def main():
    if os.environ.get("REQUEST_METHOD", "GET").upper() == "OPTIONS":
        send_json({"success": True})
        return
    send_json(
        {
            "success": False,
            "error": "直接保存は無効です。編集画面から確認依頼を送信してください",
        }
    )


if __name__ == "__main__":
    main()
