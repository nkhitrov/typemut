#!/usr/bin/env bash
# Resolves the database path, the default branch, and whether this run may
# store the database: only trusted events (push, schedule, workflow_dispatch)
# on the default branch do; pull requests and other branches only read it.
set -uo pipefail

workdir="${INPUT_WORKING_DIRECTORY:-.}"
if ! workdir="$(cd -- "$workdir" && pwd -P)"; then
  echo "::error::working-directory '${INPUT_WORKING_DIRECTORY}' does not exist"
  exit 1
fi

db="${INPUT_DB:-typemut.sqlite}"
case "$db" in
  /*) ;;
  *) db="$workdir/$db" ;;
esac

branch="${INPUT_DEFAULT_BRANCH:-${EVENT_DEFAULT_BRANCH:-}}"
if [ -z "$branch" ]; then
  # A schedule event carries no repository in its payload.
  if ! branch="$(gh api "repos/$GITHUB_REPOSITORY" --jq .default_branch)" || [ -z "$branch" ]; then
    echo "::warning::Could not find the default branch: the database is neither downloaded nor uploaded"
    branch=""
  fi
fi

store=false
case "${GITHUB_EVENT_NAME:-}" in
  push | schedule | workflow_dispatch)
    if [ -n "$branch" ] && [ "${GITHUB_REF:-}" = "refs/heads/$branch" ] && [ "${INPUT_UPLOAD:-true}" != false ]; then
      store=true
    fi
    ;;
esac

{
  printf 'db=%s\n' "$db"
  printf 'default-branch=%s\n' "$branch"
  printf 'store=%s\n' "$store"
} >> "$GITHUB_OUTPUT"
