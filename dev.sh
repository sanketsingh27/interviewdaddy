#!/bin/sh
set -eu

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    python3 -m venv .venv
fi

if [ ! -d frontend/node_modules ]; then
    npm ci --prefix frontend
fi

exec .venv/bin/python dev.py
