#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import sys


def send_json(obj):
    body = (json.dumps(obj, ensure_ascii=False) + "\r\n").encode("utf-8")
    headers = (
        "Content-Type: application/json; charset=utf-8\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "Access-Control-Allow-Headers: Content-Type, X-Auth-Token\r\n"
        "Cache-Control: no-store\r\n"
        "Content-Length: {}\r\n"
        "\r\n"
    ).format(len(body)).encode("ascii")
    output = getattr(sys.stdout, "buffer", sys.stdout)
    output.write(headers + body)
    output.flush()
