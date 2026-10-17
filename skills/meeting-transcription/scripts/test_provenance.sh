#!/usr/bin/env bash
# Tests for the recording-provenance helpers in debrief_sync.sh.
#
# WHY THIS EXISTS: the handoff used to stamp every manifest with `date` and
# `duration_s: 0`, so each derived transcript claimed the meeting happened at
# upload time and lasted a minute. Deriving the values from the audio instead is
# easy to get subtly wrong in two ways this file pins down:
#   1. printf '%.0f' on a locale whose decimal separator is ',' writes the
#      partially-parsed value AND fails, so a `|| printf 0` fallback appends a
#      digit instead of replacing the number.
#   2. BSD `date -j` fills fields the format does not name from the CURRENT
#      time, so a format without %S stamps a different second on every run.
# Both produce plausible-looking numbers. Only a counter-test catches them.
#
# Usage:  ./test_provenance.sh [path/to/an/audio/file]
# The optional argument enables the probe test; without it that one is skipped
# (no audio fixture is committed — this repo ships no media).

set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
src="$here/debrief_sync.sh"
[[ -f "$src" ]] || { echo "debrief_sync.sh not found next to this test"; exit 2; }

# Source only the helper block, so config resolution does not run.
helpers="$(mktemp)"; trap 'rm -f "$helpers"' EXIT
sed -n '/^# --- Recording provenance/,/^# --- Capability registry/p' "$src" | sed '$d' > "$helpers"
grep -q 'derive_recorded_at' "$helpers" || { echo "helper block not found — did the section header change?"; exit 2; }
# shellcheck disable=SC1090
source "$helpers"

audio="${1:-}"   # saved up front: `set --` inside a loop would overwrite $1
fail=0
check() {
  if [[ "$2" == "$3" ]]; then printf '  ok   %s: %s\n' "$1" "$3"
  else printf '  FAIL %s: expected %s, got %s\n' "$1" "$2" "$3"; fail=1; fi
}

tmp="$(mktemp -d)"; trap 'rm -f "$helpers"; rm -rf "$tmp"' EXIT

echo "filename carries the start time"
: > "$tmp/meeting 20240315 0930.mp3"
check "YYYYMMDD HHMM" "$(TZ=UTC date -u -r "$(TZ=UTC date -j -f %Y%m%d%H%M%S 20240315093000 +%s 2>/dev/null \
     || TZ=UTC date -d '2024-03-15 09:30:00' +%s)" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
     || TZ=UTC date -u -d "@$(TZ=UTC date -d '2024-03-15 09:30:00' +%s)" +%Y-%m-%dT%H:%M:%SZ)" \
  "$(TZ=UTC derive_recorded_at "$tmp/meeting 20240315 0930.mp3" 0)"

echo "same filename twice must give the same answer (no current-second bleed)"
a="$(TZ=UTC derive_recorded_at "$tmp/meeting 20240315 0930.mp3" 0)"
sleep 1
b="$(TZ=UTC derive_recorded_at "$tmp/meeting 20240315 0930.mp3" 0)"
check "stable across runs" "$a" "$b"
case "$a" in *:00Z) echo "  ok   seconds are zero, not the wall clock";; *) echo "  FAIL seconds not zeroed: $a"; fail=1;; esac

echo "no timestamp in the name — fall back to mtime minus duration"
: > "$tmp/undated.mp3"
touch -t 202403150935.00 "$tmp/undated.mp3"      # recording STOPPED at 09:35
check "mtime minus 300s" "$(TZ=UTC date -u -r "$(( $(stat -f %m "$tmp/undated.mp3" 2>/dev/null || stat -c %Y "$tmp/undated.mp3") - 300 ))" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
     || TZ=UTC date -u -d "@$(( $(stat -c %Y "$tmp/undated.mp3") - 300 ))" +%Y-%m-%dT%H:%M:%SZ)" \
  "$(TZ=UTC derive_recorded_at "$tmp/undated.mp3" 300)"

echo "a file with no decodable audio yields 0, it does not abort"
: > "$tmp/empty.mp3"
check "unknown duration" "0" "$(probe_duration_s "$tmp/empty.mp3")"

echo "rounding is locale-independent"
# Find an installed locale that actually uses a comma, by ASKING each one
# rather than guessing from its name.
comma=""
for cand in $(locale -a 2>/dev/null); do
  case "$cand" in *[Uu][Tt][Ff]*) ;; *) continue;; esac
  [[ "$(LC_ALL="$cand" locale decimal_point 2>/dev/null)" == "," ]] && { comma="$cand"; break; }
done
for pair in "3491.030204 3491" "317.413878 317" "3491.5 3492" "9.9 10" "0.4 0"; do
  set -- $pair   # overwrites $1, which is why the file path is saved in $audio above
  check "round $1 (C)" "$2" "$(LC_ALL=C _round_seconds "$1")"
  if [[ -n "$comma" ]]; then
    check "round $1 ($comma)" "$2" "$(LC_ALL="$comma" LC_NUMERIC="$comma" _round_seconds "$1")"
  fi
done
[[ -z "$comma" ]] && echo "  skip no comma-decimal locale installed — half the rounding checks did not run"
check "garbage in, 0 out" "0" "$(_round_seconds "not-a-number")"

# The blind spot that made the first fix wrong: an `LC_ALL=C` prefix does not
# reach the printf BUILTIN under /bin/bash 3.2 (macOS default), but DOES under
# homebrew bash 5.x. Running the table only in the current shell therefore proves
# nothing about the shell most macOS machines actually use. Run it there too.
if [[ -x /bin/bash ]]; then
  bbver="$(/bin/bash -c 'echo ${BASH_VERSINFO[0]}')"
  echo "rounding under /bin/bash (major version $bbver)"
  for pair in "3491.030204 3491" "3491.5 3492" "9.9 10"; do
    set -- $pair
    got="$(/bin/bash -c 'export LC_ALL="'"${comma:-C}"'" LC_NUMERIC="'"${comma:-C}"'"; source "$1"; _round_seconds "$2"' _ "$helpers" "$1" 2>/dev/null)"
    check "/bin/bash round $1" "$2" "$got"
  done
else
  echo "  skip /bin/bash not present"
fi

if [[ -n "$audio" && -f "$audio" ]]; then
  echo "probe against the supplied audio file"
  d="$(probe_duration_s "$audio")"
  case "$d" in
    ''|*[!0-9]*) echo "  FAIL duration not an integer: '$d'"; fail=1;;
    0)           echo "  FAIL duration probed as 0 — no ffprobe and no afinfo?"; fail=1;;
    *)           echo "  ok   duration is a plain integer: ${d}s";;
  esac
else
  echo "probe test skipped (pass an audio file path to enable it)"
fi

echo
[[ $fail -eq 0 ]] && echo "all checks passed" || echo "FAILURES present"
exit $fail
