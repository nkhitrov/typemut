#!/usr/bin/env bash
# Runs `typemut run --incremental` with the action's inputs. With
# TIMEOUT_MINUTES, typemut gets SIGTERM after that time and stops like on
# Ctrl+C, saving its finished results, so the upload step still has them.
set -uo pipefail
set -f  # no globbing when splitting the command and args on whitespace

read -ra command <<< "${TYPEMUT_COMMAND:-typemut}"
[ "${#command[@]}" -gt 0 ] || command=(typemut)
read -ra extra <<< "${ARGS:-}"

args=(run --incremental --db "$DB")
if [ -n "${JOBS:-}" ]; then
  args+=(--jobs "$JOBS")
fi
if [ -n "${MAX_DURATION:-}" ]; then
  args+=(--max-duration "$MAX_DURATION")
fi
if [ -n "${BASELINE:-}" ]; then
  args+=(--baseline "$BASELINE")
fi
if [ -n "${FAIL_UNDER:-}" ]; then
  args+=(--fail-under "$FAIL_UNDER")
fi
case "${REFRESH:-false}" in
  true) args+=(--refresh) ;;
  false | "") ;;
  *) echo "::warning::refresh must be true or false, not '$REFRESH': running without --refresh" ;;
esac

limit=()
if [ -n "${TIMEOUT_MINUTES:-}" ]; then
  if ! [[ "$TIMEOUT_MINUTES" =~ ^[0-9]+$ ]] || [ "$TIMEOUT_MINUTES" -eq 0 ]; then
    echo "::warning::timeout-minutes must be a positive whole number, not '$TIMEOUT_MINUTES': running without it"
  elif timeout_bin="$(command -v timeout || command -v gtimeout)"; then
    # Two more minutes for the running mutants and the save, then SIGKILL.
    limit=("$timeout_bin" --signal=TERM --kill-after=2m "${TIMEOUT_MINUTES}m")
  else
    echo "::warning::Neither timeout nor gtimeout is installed: running without timeout-minutes"
  fi
fi

echo "${command[*]} ${args[*]}${extra[*]+ ${extra[*]}}"
${limit[@]+"${limit[@]}"} "${command[@]}" "${args[@]}" ${extra[@]+"${extra[@]}"}
status=$?
if [ "${#limit[@]}" -gt 0 ] && [ "$status" -eq 124 ]; then
  echo "::error::typemut was stopped after timeout-minutes ($TIMEOUT_MINUTES); its finished results are saved"
fi
exit "$status"
