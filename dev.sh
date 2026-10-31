#!/bin/sh
set -eu

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    python3 -m venv .venv
fi

if [ -f .env ]; then
    exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 0 --env-file .env
fi

exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 0
