#!/bin/bash
# Doble clic en macOS para arrancar textgraph.
cd "$(dirname "$0")" || exit 1
echo "Arrancando textgraph…"
exec python3 server.py "$@"
