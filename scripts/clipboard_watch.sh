#!/usr/bin/env bash
# clipboard_watch.sh — catch intermittent X11 clipboard stalls while labelling.
#
# Why this exists: Ctrl+V intermittently freezing Chrome (both the labelling
# wizard AND the omnibox) was traced to X11 clipboard ownership, not to any page.
# On X11 exactly one client owns the CLIPBOARD selection, and a paste BLOCKS the
# pasting app until that owner answers. With AnyDesk and TeamViewer both running
# and both syncing/re-claiming the clipboard, ownership flips constantly; land a
# paste while it belongs to a stalled remote-sync process and Chrome hangs until
# the X selection timeout.
#
# Run this in a spare terminal while you work. It samples the clipboard once a
# second and logs ONLY the bad samples, so a quiet log means a healthy clipboard.
# When a freeze happens, look here: the line tells you how long the read blocked
# and which process owned the selection at that moment.
#
#   bash scripts/clipboard_watch.sh                 # log to stdout
#   bash scripts/clipboard_watch.sh clip.log        # also append to a file
#
# Ctrl+C to stop. Read-only: never writes to your clipboard.

set -u

LOG="${1:-}"
SLOW_MS=500        # anything slower than this is user-visible lag
TIMEOUT_S=3        # a read this slow is what a "frozen" paste feels like
INTERVAL=1

command -v xclip >/dev/null 2>&1 || { echo "need xclip: sudo apt install xclip"; exit 1; }

say() {
  printf '%s\n' "$1"
  [ -n "$LOG" ] && printf '%s\n' "$1" >> "$LOG"
}

# Which PID owns the CLIPBOARD selection right now. xprop doesn't expose the
# owner directly, so infer it from the window id that holds the selection.
owner() {
  local wid pid cmd
  wid=$(timeout 2 xprop -root -notype _NET_ACTIVE_WINDOW 2>/dev/null | awk '{print $NF}')
  pid=$(timeout 2 xprop -id "$wid" _NET_WM_PID 2>/dev/null | awk '{print $NF}')
  if [ -n "${pid:-}" ] && [ "$pid" != "found." ] 2>/dev/null; then
    cmd=$(ps -p "$pid" -o comm= 2>/dev/null)
    printf '%s' "${cmd:-unknown}(pid $pid)"
  else
    printf '%s' "unknown"
  fi
}

say "clipboard_watch: sampling every ${INTERVAL}s; logging reads slower than ${SLOW_MS}ms."
say "clipboard_watch: remote tools running now: $(ps -eo comm= 2>/dev/null | grep -icE 'anydesk|teamviewer') process(es)."
say "clipboard_watch: started $(date '+%F %T'). Quiet output = healthy."

slow=0; timeouts=0; samples=0
trap 'say ""; say "clipboard_watch: stopped $(date "+%F %T") — $samples samples, $slow slow, $timeouts timed out."; exit 0' INT TERM

while true; do
  start=$(date +%s%N)
  timeout "$TIMEOUT_S" xclip -o -selection clipboard >/dev/null 2>&1
  rc=$?
  end=$(date +%s%N)
  ms=$(( (end - start) / 1000000 ))
  samples=$((samples + 1))

  if [ "$rc" -eq 124 ]; then
    timeouts=$((timeouts + 1))
    say "$(date '+%F %T')  TIMEOUT  read blocked >${TIMEOUT_S}s  owner=$(owner)   <-- a paste here would freeze Chrome"
  elif [ "$ms" -ge "$SLOW_MS" ]; then
    slow=$((slow + 1))
    say "$(date '+%F %T')  SLOW     read took ${ms}ms  owner=$(owner)"
  fi

  sleep "$INTERVAL"
done
