# Keeping the database between CI runs

An incremental run is only as fast as the database it starts from, and a CI
job starts from a fresh checkout. Carry `typemut.sqlite` from run to run with
these rules:

- **Not in git.** The database is binary, changes on every run, and an
  untracked or modified file in the project fails the clean-tree check of
  `--jobs`. Keep `*.sqlite` in `.gitignore` (or pass `--db` outside the
  project).
- **Only trusted runs on the default branch store it** (push, schedule, manual
  runs). Pull/merge requests and other branches only read it: a cached kill is
  copied as is, so a database written by an untrusted change could hide
  survivors from later runs.
- **Every run, the default branch included, starts from the latest database of
  the default branch, whatever that run's outcome.** A run that failed (a new
  survivor) or was stopped by `--max-duration` saved its finished results, and
  the next run continues from them. That is how a project too large for one CI
  job gets covered: each run on main adds kills until none are left to run.
- **No database means a full run**: correct, only slower. An expired artifact
  or an evicted cache costs one slow run, nothing else.
- **Time limits nest**: `--max-duration` < the step's (script's) timeout < the
  job's timeout, so typemut stops starting mutants, waits for the running ones
  and saves, and the upload step still runs. Leave room for one mutant's
  `timeout` plus the baseline check between `--max-duration` and the step
  timeout.
- **Runs on the default branch wait for each other.** Two overlapping runs
  would both upload a database, and the older commit's run could finish
  last and become "the latest". Queue them (a concurrency group on GitHub, a
  `resource_group` on GitLab), so a queued run downloads the database of the
  run before it when it starts, and pick the newest run's database, not the
  newest upload (the artifact examples do; the GitHub cache example restores
  the newest upload, see its caveat). A queued run waits for the one ahead of
  it, so a push that arrives during the weekly refresh waits until the refresh
  is done.
- **Recheck on a schedule**: a weekly `typemut run --refresh` on the default
  branch runs every mutant again and stores the results like a push. It
  rechecks only what fits in its `--max-duration`, so give it a limit (and job
  timeout) long enough for the whole project, within the platform's maximum
  job time: the GitHub examples use 5.5 hours, the GitLab one 5h40m, instead
  of 25 minutes.

typemut's own CI does this with a GitHub artifact: see
[`.github/workflows/ci.yml`](https://github.com/nkhitrov/typemut/blob/main/.github/workflows/ci.yml). (There, any change to typemut's own sources resets
the cache, since an unreleased typemut is keyed by its sources: pull requests
that touch `src/typemut/` run every mutant.)

=== "GitHub Actions: artifact"

    Artifacts are kept for `retention-days` (up to the repository's limit, 90 days
    by default), can be found by name through the API, and a failed or timed-out
    run still uploads one with `if: always()`. The download step looks for the
    unexpired `typemut-db` artifact of the newest run (highest run id) on `main`
    of this repository: `head_repository_id` keeps out a fork's pull request from
    a branch that is also named `main`, and the run id keeps out a re-run of an
    old run, which uploads later than newer runs. It reads the 100 most recently
    uploaded `typemut-db` artifacts, which is plenty with one per run on main.
    The `concurrency` group queues runs of the same branch, so a run on main
    starts after the previous one has uploaded. GitHub keeps only one waiting run
    per group, and a newer one cancels it. For a waiting push run that is fine:
    the newer run downloads the same database and covers its commit. But a push
    can also cancel a waiting weekly refresh (or wait for a running one, up to its
    time limit); re-trigger a cancelled refresh by hand with the workflow's
    `refresh` input. Don't give refreshes a group of their own: a push run started
    during a refresh has a higher run id, so its database, built without the
    refresh's results, would become the latest. `overwrite: true` lets a re-run of failed jobs, which reuses the
    run, replace that run's artifact. The weekly `--refresh` run gets a 5.5-hour
    limit (a GitHub-hosted job runs for at most 6 hours).

    ```yaml
    name: typemut

    on:
      push:
        branches: [main]
      pull_request:
      schedule:
        - cron: "0 3 * * 1"   # weekly --refresh
      workflow_dispatch:
        inputs:
          refresh:            # re-trigger a refresh replaced in the queue
            type: boolean
            default: false

    permissions:
      contents: read

    jobs:
      typemut:
        runs-on: ubuntu-latest
        # > step timeout > --max-duration; the weekly --refresh gets longer.
        timeout-minutes: ${{ (github.event_name == 'schedule' || inputs.refresh) && 350 || 45 }}
        concurrency:                   # runs on main upload one after another
          group: typemut-db-${{ github.ref }}
          cancel-in-progress: false
        permissions:
          contents: read
          actions: read                # list and download artifacts
        steps:
          - uses: actions/checkout@v4
          - uses: astral-sh/setup-uv@v4
          - run: uv sync

          - name: Download the typemut database of main
            env:
              GH_TOKEN: ${{ github.token }}
              REPO_ID: ${{ github.repository_id }}
            run: |
              # Unexpired artifact of the newest run on main of this repository
              # (not of a fork), whatever that run's outcome.
              query='[.artifacts[]
                      | select(.expired | not)
                      | select(.workflow_run.head_branch == "main")
                      | select(.workflow_run.head_repository_id == ($ENV.REPO_ID | tonumber))]
                     | max_by(.workflow_run.id) // empty
                     | "\(.id) \(.workflow_run.id)"'
              if ! found="$(gh api "repos/$GITHUB_REPOSITORY/actions/artifacts?name=typemut-db&per_page=100" --jq "$query")"; then
                echo "::warning::Could not list the typemut-db artifacts: running every mutant"
                exit 0
              fi
              if [ -z "$found" ]; then
                echo "::notice::No typemut database of main: running every mutant"
                exit 0
              fi
              read -r artifact_id run_id <<< "$found"
              if gh api "repos/$GITHUB_REPOSITORY/actions/artifacts/$artifact_id/zip" > typemut-db.zip \
                  && unzip -o -q typemut-db.zip typemut.sqlite; then
                echo "::notice::typemut database from run $run_id"
              else
                echo "::warning::Could not download the database of run $run_id: running every mutant"
                rm -f typemut.sqlite
              fi
              rm -f typemut-db.zip

          - name: typemut
            timeout-minutes: ${{ (github.event_name == 'schedule' || inputs.refresh) && 340 || 35 }}
            env:
              ARGS: ${{ (github.event_name == 'schedule' || inputs.refresh) && '--refresh --max-duration 19800' || '--max-duration 1500' }}
            run: >-
              uv run typemut run --incremental --jobs 4
              --baseline typemut-baseline.json $ARGS

          # Only trusted events on main store the database, even when typemut failed.
          - name: Upload the typemut database
            if: always() && github.event_name != 'pull_request' && github.ref == 'refs/heads/main'
            uses: actions/upload-artifact@v4
            with:
              name: typemut-db
              path: typemut.sqlite
              retention-days: 30
              if-no-files-found: ignore
              overwrite: true          # a re-run of failed jobs reuses the run
    ```

=== "GitHub Actions: cache"

    Simpler, with no API calls, but caches unused for 7 days are evicted and the
    repository's cache storage is limited (10 GB by default, oldest evicted first).
    Each run on main saves a new cache under a unique key; every run restores the
    newest one by the `typemut-` prefix. Pull requests can restore caches of the
    base branch, and caches saved by pull requests stay scoped to them, so main
    never reads one. The triggers, time limits and concurrency group are those of
    the artifact workflow; only the database steps differ (no `actions: read`
    needed).

    The caveat: the restore step takes the newest *saved* cache, not the newest
    run's. The concurrency group does not stop a re-run of an older run on main
    (say, "Re-run failed jobs" on a run that failed): it saves last, so later runs
    restore it instead of the newer runs' caches. Nothing wrong gets reused,
    since kills are only copied for files whose hashes still match (and a changed
    typemut, checker version or lockfile resets the cache), but the progress of
    the runs in between is lost and their mutants run again. Re-run only the
    newest run on main, or use the artifact variant, which picks the newest run.

    ```yaml
    name: typemut

    on:
      push:
        branches: [main]
      pull_request:
      schedule:
        - cron: "0 3 * * 1"   # weekly --refresh
      workflow_dispatch:
        inputs:
          refresh:            # re-trigger a refresh replaced in the queue
            type: boolean
            default: false

    permissions:
      contents: read

    jobs:
      typemut:
        runs-on: ubuntu-latest
        # > step timeout > --max-duration; the weekly --refresh gets longer.
        timeout-minutes: ${{ (github.event_name == 'schedule' || inputs.refresh) && 350 || 45 }}
        concurrency:                   # runs on main save one after another
          group: typemut-db-${{ github.ref }}
          cancel-in-progress: false
        steps:
          - uses: actions/checkout@v4
          - uses: astral-sh/setup-uv@v4
          - run: uv sync

          - uses: actions/cache/restore@v4
            with:
              path: typemut.sqlite
              key: typemut-${{ github.run_id }}-${{ github.run_attempt }}
              restore-keys: typemut-   # the newest cache saved on main

          - name: typemut
            timeout-minutes: ${{ (github.event_name == 'schedule' || inputs.refresh) && 340 || 35 }}
            env:
              ARGS: ${{ (github.event_name == 'schedule' || inputs.refresh) && '--refresh --max-duration 19800' || '--max-duration 1500' }}
            run: >-
              uv run typemut run --incremental --jobs 4
              --baseline typemut-baseline.json $ARGS

          - uses: actions/cache/save@v4
            if: always() && github.event_name != 'pull_request' && github.ref == 'refs/heads/main'
            with:
              path: typemut.sqlite
              key: typemut-${{ github.run_id }}-${{ github.run_attempt }}
    ```

=== "GitLab CI: artifact"

    Three jobs share the setup: `typemut` runs on the default branch and keeps the
    database as an artifact even when it fails (`when: always`); `typemut-mr` runs
    for merge requests and keeps nothing; `typemut-refresh` is the weekly
    `--refresh` from a pipeline schedule, with a longer time limit so that it
    rechecks the whole project (raise the project's and the runner's maximum job
    timeout to match).

    Before typemut starts, `ci/typemut-db.sh` downloads the database of the newest
    `typemut` or `typemut-refresh` job on the default branch that succeeded or
    failed. GitLab's "latest artifact of a branch" endpoint only knows successful
    pipelines, so the script looks the job up with [glab](https://gitlab.com/gitlab-org/cli)
    and [jq](https://jqlang.org): `glab ci list` gives the 50 newest pipelines of
    the default branch (merge request pipelines have other refs and do not push
    them out), `glab ci get` the jobs of each, newest first, until one has such a
    job. A pipeline still running other jobs (a later stage, a deploy waiting on a
    manual job) counts once its typemut job is done; pipelines are ordered by id,
    so a retried job of an older pipeline does not win. `glab api` then fetches the
    single `typemut.sqlite` (no zip involved), and the script keeps it only if it
    is an SQLite database. No such job, an expired artifact, or any API error means
    no database and a full run, never a broken file; the script never fails the
    job. The first run scans all 50 pipelines, a few minutes.

    Listing pipelines needs a token with the `read_api` scope: a project access
    token with the Reporter role and a short expiry, saved as the masked CI/CD
    variable `TYPEMUT_API_TOKEN`. Use a token of its own, not an existing
    `GITLAB_TOKEN`, which often has the `api` scope. Without it, glab uses the job
    token, and the script takes the `typemut` job of the latest successful
    pipeline instead. Either:

    - leave the variable unprotected, so merge request pipelines use it too. Any
      code in a merge request of this project can then read it, so don't run
      pipelines of fork merge requests in the parent project; or
    - protect it (safer): only the default branch's jobs list pipelines, merge
      requests get the database of the latest successful pipeline, which may be
      older.

    Either way the default branch must be protected: only its pipelines' jobs are
    picked, and only trusted users should be able to run them.

    `resource_group: typemut-db` is GitLab's counterpart to the GitHub concurrency
    group: the `typemut` and `typemut-refresh` jobs run one at a time, and a job
    waiting for the group downloads the database when its script starts, after
    the job ahead of it has uploaded. A push pipeline that starts during the
    weekly refresh therefore waits for it (up to its 6h timeout). The group's
    default process mode lets waiting jobs start in any order; set it to
    `oldest_first` (`glab api --method PUT "projects/<id>/resource_groups/typemut-db"
    --field process_mode=oldest_first`) so they run in pipeline order and the
    newest pipeline's database is also the last one written.
    `RUNNER_SCRIPT_TIMEOUT` below `timeout` leaves the runner time to upload the
    artifact after a script timeout; it needs GitLab Runner 16.4 or later (older
    runners ignore it, and a job that hits `timeout` uploads nothing).

    The `.glab` preset installs jq and a pinned glab release (checked against its
    SHA-256, amd64 runners) and turns on glab's CI auto-login (glab 1.90 or later).
    Its `before_script` replaces a `default: before_script`. In production, pin the
    image by digest, or bake glab and jq into your own image and drop `.glab`.

    ```yaml
    # glab and jq; glab logs in with the job token (CI auto-login).
    .glab:
      variables:
        GLAB_VERSION: "1.92.1"
        GLAB_SHA256: "18048e5cb2cbc92eb31d4190852c6da32f6713633cfefc7b3fe00c18806c4f53"  # linux_amd64.deb
        GLAB_ENABLE_CI_AUTOLOGIN: "true"
        GLAB_CHECK_UPDATE: "false"
        GLAB_SEND_TELEMETRY: "false"
      before_script:
        - apt-get update -qq && apt-get install -y -qq --no-install-recommends jq
        - curl -fsSL -o /tmp/glab.deb
            "https://gitlab.com/gitlab-org/cli/-/releases/v$GLAB_VERSION/downloads/glab_${GLAB_VERSION}_linux_amd64.deb"
        - echo "$GLAB_SHA256  /tmp/glab.deb" | sha256sum -c -
        - dpkg -i /tmp/glab.deb

    .typemut:
      extends: .glab
      image: ghcr.io/astral-sh/uv:python3.13-bookworm
      timeout: 45m
      variables:
        RUNNER_SCRIPT_TIMEOUT: 35m     # < timeout, > --max-duration (Runner 16.4+)
        TYPEMUT_MAX_DURATION: "1500"
      script:
        - uv sync
        - bash ci/typemut-db.sh        # the previous database, or none
        - uv run typemut run --incremental --jobs 4 --max-duration $TYPEMUT_MAX_DURATION
            --baseline typemut-baseline.json $TYPEMUT_EXTRA_ARGS

    .typemut-store:
      extends: .typemut
      resource_group: typemut-db       # one job at a time, like GitHub's concurrency group
      artifacts:
        paths: [typemut.sqlite]
        when: always                   # failed and timed-out runs store their results too
        expire_in: 30 days

    typemut:
      extends: .typemut-store
      rules:
        - if: $CI_PIPELINE_SOURCE == "schedule"
          when: never
        - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

    typemut-refresh:                   # weekly pipeline schedule on the default branch
      extends: .typemut-store
      timeout: 6h
      variables:
        RUNNER_SCRIPT_TIMEOUT: 5h50m
        TYPEMUT_MAX_DURATION: "20400"  # 5h40m: a refresh rechecks only what fits
        TYPEMUT_EXTRA_ARGS: "--refresh"
      rules:
        - if: $CI_PIPELINE_SOURCE == "schedule" && $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

    typemut-mr:
      extends: .typemut
      rules:
        - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    ```

    `ci/typemut-db.sh`:

    ```bash
    #!/usr/bin/env bash
    # Downloads typemut.sqlite of the newest typemut run on the default branch.
    # Never fails the job: without a database typemut runs every mutant.
    # No `set -e` (bash ignores it left of `||`): every step is chained instead.
    set -uo pipefail

    repo=(--repo "$CI_PROJECT_PATH")
    api="projects/$CI_PROJECT_ID"

    # Ids of the 50 newest pipelines of the default branch, newest first.
    pipelines() {
      glab ci list "${repo[@]}" --ref "$CI_DEFAULT_BRANCH" \
        --order id --sort desc --per-page 50 --output json | jq '.[].id'
    }

    # Id of the pipeline's typemut job if it succeeded or failed, else nothing.
    typemut_job() {
      glab ci get "${repo[@]}" --pipeline-id "$1" --output json | jq 'first(.jobs[]?
        | select(.name == ("typemut", "typemut-refresh"))
        | select(.status == ("success", "failed"))
        | .id) // empty'
    }

    # Id of the typemut job of the newest pipeline that has one.
    latest_typemut_job() {
      local ids id job
      ids="$(pipelines)" || return
      for id in $ids; do
        job="$(typemut_job "$id")" || return   # an API error is not "no job"
        if [ -n "$job" ]; then echo "$job"; return 0; fi
      done
      return 1
    }

    # Saves the artifact file at an API path as typemut.sqlite, if it is a database.
    download() {
      glab api "$1" > typemut.sqlite.part &&
        head -c 16 typemut.sqlite.part | grep -q '^SQLite format 3' &&
        mv typemut.sqlite.part typemut.sqlite
    }

    fetch() {
      if [ -z "${TYPEMUT_API_TOKEN:-}" ]; then
        # The job token cannot list pipelines: latest successful pipeline only.
        local ref
        ref="$(jq -rn --arg ref "$CI_DEFAULT_BRANCH" '$ref | @uri')" &&
          download "$api/jobs/artifacts/$ref/raw/typemut.sqlite?job=typemut" &&
          echo "typemut database of the latest successful pipeline"
        return
      fi
      unset GITLAB_ACCESS_TOKEN OAUTH_TOKEN    # glab uses typemut's own token only
      export GITLAB_TOKEN="$TYPEMUT_API_TOKEN"
      local job
      job="$(latest_typemut_job)" &&
        download "$api/jobs/$job/artifacts/typemut.sqlite" &&
        echo "typemut database from job $job"
    }

    fetch || echo "No typemut database of $CI_DEFAULT_BRANCH: running every mutant"
    rm -f typemut.sqlite.part
    ```

=== "GitLab CI: cache"

    Works with caveats, so prefer artifacts:

    - By default protected branches (the default branch) and unprotected ones
      (merge request branches) get separate caches, so a merge request never sees
      the cache of the default branch. Turning off **Use separate caches for
      protected branches** fixes that, but then any branch's job can write the
      cache the default branch reads, unless every job but the default branch's
      uses `policy: pull`.
    - `fallback_keys` needs GitLab 16.0 or later, a variable in `cache:policy`
      16.1 or later, `$CI_DEFAULT_BRANCH_SLUG` (the fallback key must be slugged
      like the key the default branch saves under) 17.4 or later, and
      `RUNNER_SCRIPT_TIMEOUT` GitLab Runner 16.4 or later.
    - Without a distributed cache (S3, GCS, ...), each runner has its own cache,
      and a job on another runner starts from nothing.

    ```yaml
    typemut:
      image: ghcr.io/astral-sh/uv:python3.13-bookworm
      timeout: 45m
      variables:
        RUNNER_SCRIPT_TIMEOUT: 35m
      cache:
        key: typemut-db-$CI_COMMIT_REF_SLUG
        fallback_keys: [typemut-db-$CI_DEFAULT_BRANCH_SLUG]
        paths: [typemut.sqlite]
        when: always
        policy: $TYPEMUT_CACHE_POLICY
      rules:
        - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
          variables:
            TYPEMUT_CACHE_POLICY: pull-push
        - if: $CI_PIPELINE_SOURCE == "merge_request_event"
          variables:
            TYPEMUT_CACHE_POLICY: pull   # merge requests only read the cache
      script:
        - uv sync
        - uv run typemut run --incremental --jobs 4 --max-duration 1500 --baseline typemut-baseline.json
    ```
