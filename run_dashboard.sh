#!/usr/bin/env bash
# Launch the PIE Phase 4 syndicate dashboard.
# Usage: ./run_dashboard.sh   (from the project root)
set -euo pipefail

cd "$(dirname "$0")"

# Prefer the project venv's interpreter if present.
if [ -x "./venv/bin/python" ]; then
  PY="./venv/bin/python"
else
  PY="python3"
fi

echo "Starting PIE dashboard at http://localhost:8501 ..."
exec "$PY" -m streamlit run app.py \
  --server.port 8501 \
  --server.address localhost \
  --server.headless true \
  --browser.gatherUsageStats false
