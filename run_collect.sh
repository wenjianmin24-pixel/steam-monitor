#!/bin/bash
export http_proxy=http://127.0.0.1:3128
export https_proxy=http://127.0.0.1:3128
export HTTP_PROXY=http://127.0.0.1:3128
export HTTPS_PROXY=http://127.0.0.1:3128
export no_proxy=localhost,127.0.0.1,::1
export NO_PROXY=localhost,127.0.0.1,::1
cd /workspace/steam-monitor
echo "=== $(date -u '+%Y-%m-%d %H:%M:%S UTC') ===" >> collect.log
/workspace/venv/bin/python collect.py all >> collect.log 2>&1
echo "exit=$? reviews=$(/workspace/venv/bin/python -c 'import sqlite3;print(sqlite3.connect("data.db").execute("select count(*) from review").fetchone()[0])')" >> collect.log
