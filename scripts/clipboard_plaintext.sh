#!/usr/bin/env bash
# Keeps copies made in VS Code pasteable in Chrome.
#
# Problem (2026-09-15): text copied from VS Code (snap Electron, incl. the Claude
# chat) freezes Chrome on Ctrl+V — even in the address bar — while the same text
# re-offered as plain text pastes instantly. VS Code advertises Chromium-internal
# formats (chromium/x-internal-source-rfh-token, chromium/x-source-url, text/html)
# and Chrome (with Input Leap also syncing the clipboard) hangs on them.
#
# Fix: poll the CLIPBOARD's format list; when the owner is VS Code, take the
# plain text and re-own the clipboard with UTF8_STRING only (xclip serves it).
#
# Usage:  scripts/clipboard_plaintext.sh &      (stop: kill the PID it prints)
set -u
INTERVAL="${INTERVAL:-0.3}"
echo "clipboard_plaintext: running as PID $$"
last=""
while true; do
  targets=$(timeout 2 xclip -o -selection clipboard -t TARGETS 2>/dev/null)
  if printf '%s' "$targets" | grep -q '^chromium/x-source-url$'; then
    src=$(timeout 2 xclip -o -selection clipboard -t chromium/x-source-url 2>/dev/null | tr -d '\0')
    if [[ "$src" == vscode-file:* ]]; then
      txt=$(timeout 2 xclip -o -selection clipboard -t UTF8_STRING 2>/dev/null)
      if [[ -n "$txt" ]]; then
        printf '%s' "$txt" | xclip -i -selection clipboard >/dev/null 2>&1
        if [[ "$txt" != "$last" ]]; then
          echo "$(date +%T) cleaned VS Code copy (${#txt} chars)"
          last="$txt"
        fi
      fi
    fi
  fi
  sleep "$INTERVAL"
done
