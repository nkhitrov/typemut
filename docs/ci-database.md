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

On GitHub Actions the ready-made action (the first tab below) does all of
this but the triggers, the time limits and the concurrency group, which belong
to the workflow; the manual workflows after it spell the same steps out. typemut's
own CI uses the action: see
[`.github/workflows/ci.yml`](https://github.com/nkhitrov/typemut/blob/main/.github/workflows/ci.yml). (There, any change to typemut's own sources resets
the cache, since an unreleased typemut is keyed by its sources: pull requests
that touch `src/typemut/` run every mutant.)

=== "GitHub Actions: ready-made action"

    The [`typemut` action](https://github.com/nkhitrov/typemut/blob/main/action.yml)
    runs the steps of the artifact workflow (next tab): it downloads the
    database of the newest run on the default branch of this repository (any
    failure is a warning and a full run; a file that is not an intact SQLite
    database is discarded), runs `typemut run --incremental`, and uploads the
    database, even when typemut failed, but only from `push`, `schedule` and
    `workflow_dispatch` runs on the default branch (`pull_request_target` and
    every other event only read it). The workflow still has to give it:

    - `permissions: actions: read`, to list and download artifacts;
    - the `concurrency` group, so that runs on the default branch upload one
      after another (an action cannot set it);
    - the job's `timeout-minutes`, above the action's `timeout-minutes`, which
      is above `max-duration`; the weekly `refresh` gets longer limits;
    - typemut and the type checker: install the project (`uv sync`) and pass
      `command: uv run typemut`, or set `version` to install typemut with
      `python -m pip`;
    - `*.sqlite` in `.gitignore`, since `jobs` needs a clean git tree.

    It runs on GitHub-hosted runners as is; a self-hosted one needs `gh`,
    `unzip`, `python3` and `timeout` (or `gtimeout`). Pin the action to a
    release tag (`0.5.0` or later) or a commit SHA.

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
        # > timeout-minutes > max-duration; the weekly --refresh gets longer.
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
          - uses: nkhitrov/typemut@0.5.0
            with:
              command: uv run typemut
              jobs: 4
              baseline: typemut-baseline.json
              refresh: ${{ (github.event_name == 'schedule' || inputs.refresh) && 'true' || 'false' }}
              max-duration: ${{ (github.event_name == 'schedule' || inputs.refresh) && 19800 || 1500 }}
              timeout-minutes: ${{ (github.event_name == 'schedule' || inputs.refresh) && 340 || 35 }}
    ```

    | Input | Default | Description |
    |-------|---------|-------------|
    | `command` | `typemut` | Command that starts typemut, split on whitespace (`uv run typemut`, `poetry run typemut`) |
    | `version` | — | Install this typemut version (`latest` for the newest) with `python -m pip` into the Python on `PATH` (set it up with `actions/setup-python`); empty: use `command` as is |
    | `working-directory` | `.` | Project root, where `typemut.toml` lives |
    | `db` | `typemut.sqlite` | Database file (`--db`), relative to `working-directory` |
    | `jobs` | — | `--jobs` |
    | `max-duration` | — | `--max-duration`, in seconds |
    | `timeout-minutes` | — | Stop typemut with SIGTERM after this many minutes; it saves its finished results like on Ctrl+C, and the upload still runs. Use it instead of a step timeout, which would also stop the upload |
    | `refresh` | `false` | `--refresh`: recheck every mutant |
    | `baseline` | — | `--baseline`, relative to `working-directory` |
    | `fail-under` | — | `--fail-under` |
    | `args` | — | More `typemut run` options, split on whitespace |
    | `artifact-name` | `typemut-db` | Database artifact name; give each job that stores a database (a matrix) its own, or set `upload: false` in all but one |
    | `retention-days` | `30` | Days to keep the uploaded database |
    | `upload` | `true` | `false`: never upload the database |
    | `default-branch` | the repository's | Branch whose database is used and stored |
    | `token` | `github.token` | Token that lists and downloads artifacts (`actions: read`) |

    Outputs: `db` (absolute path of the database, e.g. for `typemut html --db`),
    `db-run-id` (the run the database came from; empty for a full run) and
    `stored` (`true` when this run uploads it).

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

    Three jobs share the script: `typemut` runs on the default branch and keeps the
    database as an artifact even when it fails (`when: always`); `typemut-mr` runs
    for merge requests and keeps nothing; `typemut-refresh` is the weekly
    `--refresh` from a pipeline schedule, with a longer time limit so that it
    rechecks the whole project (raise the project's and the runner's maximum job
    timeout to match). All download the artifact of the `typemut` or
    `typemut-refresh` job of the newest default-branch pipeline in which that job
    succeeded or failed: GitLab's "latest artifact of a branch" endpoint only knows
    successful pipelines, so the job is looked up through the API, in the 50 newest
    pipelines of the default branch (listed by the server, so merge request
    pipelines do not push them out). A pipeline still running other jobs (a later
    stage, a deploy waiting on a manual job) counts once its typemut job is done;
    pipelines are ordered by id, so a retried job of an older pipeline does not
    win. With none among them, the run is a full one.
    `resource_group: typemut-db` is GitLab's counterpart to the GitHub concurrency
    group: the `typemut` and `typemut-refresh` jobs run one at a time, and a job
    waiting for the group downloads the database when its script starts, after
    the job ahead of it has uploaded. A push pipeline that starts during the
    weekly refresh therefore waits for it (up to its 6h timeout). The group's
    default process mode lets waiting jobs start in any order; set it to
    `oldest_first` (`curl --request PUT --header "PRIVATE-TOKEN: ..." --data
    "process_mode=oldest_first" "$CI_API_V4_URL/projects/<id>/resource_groups/typemut-db"`)
    so they run in pipeline order and the newest pipeline's database is also the
    last one written. Listing pipelines and jobs needs a token with the
    `read_api` scope (a project access token with the Reporter role, saved as the
    masked CI/CD variable `TYPEMUT_API_TOKEN`; leave it unprotected so merge
    request pipelines see it). Without it the script falls back to the job token
    and the `typemut` job of the latest successful pipeline. `curl --fail` fetches the single file, so
    no zip is involved; a missing artifact (or a failed download, whose partial
    file is removed) just means a full run.
    `RUNNER_SCRIPT_TIMEOUT` below `timeout` leaves the runner time to upload the
    artifact after a script timeout; it needs GitLab Runner 16.4 or later (older
    runners ignore it, and a job that hits `timeout` uploads nothing).

    ```yaml
    .typemut:
      image: ghcr.io/astral-sh/uv:python3.13-bookworm
      timeout: 45m
      variables:
        RUNNER_SCRIPT_TIMEOUT: 35m     # < timeout, > --max-duration (Runner 16.4+)
        TYPEMUT_MAX_DURATION: "1500"
      script:
        - uv sync
        - |
          api="$CI_API_V4_URL/projects/$CI_PROJECT_ID"
          if [ -n "${TYPEMUT_API_TOKEN:-}" ]; then
            # Newest `typemut`/`typemut-refresh` job on the default branch,
            # successful or failed, in its 50 newest pipelines.
            job_id="$(python3 - <<'PY'
          import json, os, urllib.parse, urllib.request
          api = os.environ["CI_API_V4_URL"] + "/projects/" + os.environ["CI_PROJECT_ID"]
          def get(path):
              headers = {"PRIVATE-TOKEN": os.environ["TYPEMUT_API_TOKEN"]}
              with urllib.request.urlopen(urllib.request.Request(api + path, headers=headers)) as response:
                  return json.load(response)
          ref = urllib.parse.quote(os.environ["CI_DEFAULT_BRANCH"], safe="")
          for pipeline in get(f"/pipelines?ref={ref}&order_by=id&sort=desc&per_page=50"):
              jobs = get(f"/pipelines/{pipeline['id']}/jobs?scope[]=success&scope[]=failed&per_page=100")
              found = [job["id"] for job in jobs if job["name"] in ("typemut", "typemut-refresh")]
              if found:
                  print(found[0])
                  break
          PY
          )" || job_id=""
            if [ -n "$job_id" ]; then
              curl --fail --location -sS --header "PRIVATE-TOKEN: $TYPEMUT_API_TOKEN" \
                "$api/jobs/$job_id/artifacts/typemut.sqlite" -o typemut.sqlite \
                && echo "typemut database from job $job_id" \
                || { echo "no previous DB"; rm -f typemut.sqlite; }
            else
              echo "no previous DB"
            fi
          else
            # Latest successful pipeline of the default branch only.
            curl --fail --location -sS --header "JOB-TOKEN: $CI_JOB_TOKEN" \
              "$api/jobs/artifacts/$CI_DEFAULT_BRANCH/raw/typemut.sqlite?job=typemut" -o typemut.sqlite \
              || { echo "no previous DB"; rm -f typemut.sqlite; }
          fi
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
