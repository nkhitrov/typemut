#!/usr/bin/env bash
# Downloads the database of the newest run (highest run id, whatever its
# outcome) on the default branch of this repository, not of a fork. Any
# failure is a warning and leaves no file behind: no database means a full run.
set -uo pipefail

full_run() {
  echo "::$1::$2: running every mutant"
  exit 0
}

[ -n "${DEFAULT_BRANCH:-}" ] || full_run warning "Unknown default branch"
for tool in gh unzip; do
  command -v "$tool" > /dev/null || full_run warning "$tool is not installed"
done

# head_repository_id keeps out a fork's pull request from a branch with the
# default branch's name; the run id keeps out a re-run of an old run, which
# uploads later than newer runs.
# shellcheck disable=SC2016  # jq variables, not shell ones
query='[.artifacts[]
        | select(.expired | not)
        | select(.workflow_run.head_branch == $ENV.DEFAULT_BRANCH)
        | select(.workflow_run.head_repository_id == ($ENV.REPO_ID | tonumber))]
       | max_by(.workflow_run.id) // empty
       | "\(.id) \(.workflow_run.id)"'
if ! found="$(gh api --method GET "repos/$GITHUB_REPOSITORY/actions/artifacts" \
    -f name="$ARTIFACT_NAME" -F per_page=100 --jq "$query")"; then
  full_run warning "Could not list the $ARTIFACT_NAME artifacts"
fi
[ -n "$found" ] || full_run notice "No $ARTIFACT_NAME artifact on $DEFAULT_BRANCH"
read -r artifact_id run_id <<< "$found"

if ! tmp="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/typemut-db.XXXXXX")"; then
  full_run warning "Could not create a temporary directory"
fi
trap 'rm -rf -- "$tmp"' EXIT

if ! gh api "repos/$GITHUB_REPOSITORY/actions/artifacts/$artifact_id/zip" > "$tmp/db.zip" \
    || ! unzip -q "$tmp/db.zip" -d "$tmp/db"; then
  full_run warning "Could not download the database of run $run_id"
fi
shopt -s nullglob dotglob
files=("$tmp/db"/*)
if [ "${#files[@]}" -ne 1 ] || [ ! -f "${files[0]}" ]; then
  full_run warning "The $ARTIFACT_NAME artifact of run $run_id does not hold one file"
fi
file="${files[0]}"

if [ "$(head -c 15 -- "$file")" != "SQLite format 3" ]; then
  full_run warning "The $ARTIFACT_NAME artifact of run $run_id is not an SQLite database"
fi
# A corrupt database kept and uploaded again would fail every later run.
if command -v python3 > /dev/null && ! python3 -I - "$file" << 'PY'
import sqlite3
import sys
from pathlib import Path

try:
    connection = sqlite3.connect(Path(sys.argv[1]).resolve().as_uri() + "?mode=ro", uri=True)
    sys.exit(connection.execute("PRAGMA quick_check").fetchone()[0] != "ok")
except sqlite3.DatabaseError:
    sys.exit(1)
PY
then
  full_run warning "The database of run $run_id is corrupt"
fi

# Copy next to the target, then rename: the target is either the old file or
# the whole new one. Journal files of an old database would corrupt the new one.
part="$DB.part.$$"
if ! mkdir -p -- "$(dirname -- "$DB")" || ! cp -- "$file" "$part" \
    || ! rm -f -- "$DB-wal" "$DB-shm" "$DB-journal" || ! mv -f -- "$part" "$DB"; then
  rm -f -- "$part"
  full_run warning "Could not save the database of run $run_id as $DB"
fi
echo "::notice::typemut database from run $run_id"
printf 'run-id=%s\n' "$run_id" >> "$GITHUB_OUTPUT"
