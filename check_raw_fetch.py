#!/usr/bin/env python3
"""
Guard against raw mutating fetch() calls in index.html.

WHY THIS EXISTS
---------------
The server rejects every non-GET request that lacks the X-Device-Token
header (app.py's _block_cross_origin_mutations). The frontend's api()
helper attaches that header; a bare fetch() does not. So any
fetch(..., {method: 'POST'|'PUT'|'DELETE'|'PATCH'}) 401s permanently once
the app is locked — and because GETs still succeed, the dashboard looks
healthy while mutations silently fail.

This bug was found and fixed at least four separate times in this file
(see the "Via api() so it carries X-Device-Token" comments), including on
/api/close-trade — a money path where a silent 401 means a trade the user
asked to close stays open. A pattern that recurs that often needs a
mechanical check, not vigilance.

USAGE
-----
    python check_raw_fetch.py            # exit 1 if violations found
    python check_raw_fetch.py --list     # show every fetch() for review

Wire into a pre-commit hook or CI to make regressions impossible to merge.

ALLOWED EXCEPTION
-----------------
/api/unlock is exempt by design: it is how a client proves it knows the
PIN, so it cannot already hold the token it is requesting.
"""

import argparse
import os
import re
import sys

INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

MUTATING = ("POST", "PUT", "DELETE", "PATCH")

# Endpoints that legitimately use a raw fetch.
EXEMPT_PATHS = ("/api/unlock",)


def find_fetch_calls(text):
    """Yield (line_no, url, options_blob) for each `fetch(` call."""
    for m in re.finditer(r"\bfetch\s*\(", text):
        start = m.end()
        depth = 1
        i = start
        # Walk to the matching close paren so we capture the whole call,
        # regardless of how the options object is formatted.
        while i < len(text) and depth:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
            if i - start > 4000:      # runaway guard
                break
        blob = text[start:i]
        line_no = text.count("\n", 0, m.start()) + 1
        url_m = re.search(r"""['"`]([^'"`]*)['"`]""", blob)
        yield line_no, (url_m.group(1) if url_m else "?"), blob


def violations(text):
    out = []
    for line_no, url, blob in find_fetch_calls(text):
        method_m = re.search(r"""method\s*:\s*['"`](\w+)['"`]""", blob)
        if not method_m:
            continue                              # no method => GET
        method = method_m.group(1).upper()
        if method not in MUTATING:
            continue
        if any(p in url or p in blob for p in EXEMPT_PATHS):
            continue
        if "X-Device-Token" in blob:              # manually attached: fine
            continue
        out.append((line_no, method, url))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="list every fetch() call")
    args = ap.parse_args()

    with open(INDEX) as f:
        text = f.read()

    if args.list:
        for line_no, url, blob in find_fetch_calls(text):
            m = re.search(r"""method\s*:\s*['"`](\w+)['"`]""", blob)
            print(f"  {line_no:>6}  {(m.group(1).upper() if m else 'GET'):<7} {url}")
        return 0

    bad = violations(text)
    if not bad:
        print("OK — no raw mutating fetch() calls in index.html")
        return 0

    print(f"FAIL — {len(bad)} raw mutating fetch() call(s) missing X-Device-Token:\n")
    for line_no, method, url in bad:
        print(f"  index.html:{line_no}  {method} {url}")
    print(
        "\nThese will 401 whenever the app is locked, silently.\n"
        "Fix: route through api(), which attaches X-Device-Token.\n"
        "Note api() returns parsed JSON and THROWS on non-2xx — it does not\n"
        "return a Response, so drop any `response.ok` / `await response.json()`."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
