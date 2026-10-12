#!/bin/bash
# Installs TrendIntel to /Applications/trend-intel (plain directory) and sets up
# a launchd background agent (auto-start + keep-alive).
#
# Usage: ./agent/install-macos.sh [--target DIR]   (default: /Applications/trend-intel)
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${TI_TARGET:-/Applications/trend-intel}"
if [[ "${1:-}" == "--target" && -n "${2:-}" ]]; then TARGET="$2"; fi
if [[ -n "${TI_TARGET:-}" ]]; then TARGET="${TI_TARGET}"; fi

if [[ ! -d "$SRC/trend_intel" ]]; then
  echo "ERROR: source not found at $SRC (run from the repo's agent/ dir)" >&2
  exit 1
fi
if ! command -v python3 >/dev/null; then
  echo "ERROR: python3 not found — install Python 3.10+ first" >&2
  exit 1
fi

echo "==> Installing to $TARGET ..."
if [[ ! -w "$(dirname "$TARGET")" ]]; then
  echo "    (needs admin rights for $(dirname "$TARGET") — asking for sudo)"
  SUDO="sudo"
else
  SUDO=""
fi
$SUDO rm -rf "$TARGET"
$SUDO mkdir -p "$TARGET"
if [[ -n "$SUDO" ]]; then
  # make it user-owned so the agent can write its data
  $SUDO chown "$USER" "$TARGET"
fi
cp -R "$SRC/." "$TARGET/"
rm -rf "$TARGET/trend_intel/__pycache__" \
       "$TARGET/trend_intel/sources/__pycache__" \
       "$TARGET/agent/__pycache__" \
       "$TARGET/data"

echo "==> Creating private venv (PEP 668-safe, no system Python changes) ..."
if python3 -m venv "$TARGET/.venv"; then
  "$TARGET/.venv/bin/pip" install --quiet pytrends 2>/dev/null \
    && echo "    pytrends installed into venv" \
    || echo "    (pytrends install skipped — core sources still work)"
else
  echo "    (venv unavailable — using system python3)"
fi

mkdir -p "$TARGET/bin"
cat > "$TARGET/bin/trendintel" <<'CLI'
#!/bin/bash
# usage: trendintel {run|status|collect|report|stop|log}
DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -x "$DIR/.venv/bin/python" ]]; then
  PY="$DIR/.venv/bin/python"
else
  PY="$(command -v python3)"
fi
export PYTHONPATH="$DIR"
case "${1:-run}" in
  run)     exec "$PY" "$DIR/agent/agent.py" ;;
  status)  exec "$PY" "$DIR/agent/status.py" "${@:2}" ;;
  collect) cd "$DIR" && exec "$PY" -m trend_intel.collector "${@:2}" ;;
  report)  exec cat "$DIR/data/intel_report.json" ;;
  stop)    launchctl unload "$HOME/Library/LaunchAgents/com.trendintel.agent.plist" 2>/dev/null || true
           pkill -f "agent/agent.py" 2>/dev/null || true
           echo "stopped" ;;
  log)     exec tail -n "${2:-50}" "$DIR/data/agent.log" ;;
  *) echo "usage: trendintel {run|status|collect|report|stop|log}" >&2; exit 1 ;;
esac
CLI
chmod +x "$TARGET/bin/trendintel"

echo "==> Installing launchd agent (auto-start + keep-alive) ..."
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$HOME/Library/LaunchAgents/com.trendintel.agent.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.trendintel.agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>${TARGET}/bin/trendintel</string>
    <string>run</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${TARGET}/data/launchd.log</string>
  <key>StandardErrorPath</key><string>${TARGET}/data/launchd.log</string>
</dict>
</plist>
PLIST
if command -v launchctl >/dev/null; then
  launchctl unload "$HOME/Library/LaunchAgents/com.trendintel.agent.plist" 2>/dev/null || true
  launchctl load "$HOME/Library/LaunchAgents/com.trendintel.agent.plist"
else
  echo "(launchctl not available here — on macOS the agent loads automatically)"
fi

echo
echo "Installed successfully at $TARGET"
echo
echo "CLI:"
echo "  $TARGET/bin/trendintel status"
echo "  $TARGET/bin/trendintel log 100"
echo "  $TARGET/bin/trendintel stop"
echo
echo "Report (for your trend-search app):"
echo "  $TARGET/data/intel_report.json"
echo
echo "Optional: pip3 install pytrends   (enables related-query expansion)"
