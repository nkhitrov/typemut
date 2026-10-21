# Incremental runs

`typemut run --incremental` reuses the kills of earlier runs stored in the same
database, and runs only the mutants that are new, survived, ended in `error`,
or whose kill may no longer hold:

```bash
typemut run --incremental --jobs 4 --baseline typemut-baseline.json
```

**What is reused.** A killed mutant is identified by its file, line, column,
operator, original and mutated annotation and required import. When it is
killed, typemut records the files the kill depends on, with a hash of each: the
mutated file, the files the checker reported errors in, and every project file
those import (directly or not). The next incremental run copies the kill
(status and checker output) if all those files are unchanged, and prints
`Reused N cached kills`.

**What always runs again.** Survived and `error` mutants; kills by timeout;
kills whose errors are outside the project root (in installed packages) or
whose output names no file (a `test-command` that `cd`s before running the
checker); every mutant under the `generic` checker, which cannot tell the
files a kill depends on (the run says so, and stores nothing in the cache); kills whose files changed (the run prints
how many). The baseline check always runs too: it catches a broken tree and
warms the checker's cache.

**When the whole cache is dropped.** The cache is reset, with the changed input
named (`Result cache reset: checker version changed.`), when any of these differ
from the run that filled it: the typemut version (and, for unreleased builds,
its sources), the checker and its version, the version of the Python it runs
with, `test-command`, `timeout`, the checker's config files (`mypy.ini`,
`pyproject.toml`, `pyrightconfig.json`, ...) and the files matched by
`cache-key-files` (by default the lockfiles `uv.lock`, `poetry.lock`,
`requirements*.txt`). Patterns in `cache-key-files` are relative to the
project root; absolute, empty and invalid ones are skipped with a warning. If the checker's
version is unknown (see [Type checkers](type-checkers.md); set
`checker-version-command`), that run neither reuses nor stores results and
leaves the cache as it is, so a single failed version check does not discard
it: the next run with a known version reuses the kills again. The Python version is that of
`python --version`, run through the project runner the checker runs with
(`uv run python --version` for `uv run mypy`, `python3.12 --version` for
`python3.12 -m mypy`) or from the directory of a checker run by path
(`.venv/bin/python --version` for `.venv/bin/mypy`).

**Keeping the cache fresh.** `typemut run --refresh` runs every mutant and
stores the results without reusing any: run it on a schedule (e.g. weekly) to
recheck the kills. (`exec --refresh` only runs the mutants still pending.)
Under `--max-duration` a refresh rechecks only the mutants that fit: they run
in a fixed order, so the ones past the limit are never rechecked and keep
their old kills. Give the scheduled refresh a time limit (and CI timeout)
long enough for the whole project, or none. Without `--incremental` nothing is reused or stored, and the kills
already in the result cache stay there: a run without the flag (or `init`)
between two incremental runs does not discard them.

**Time limits.** `--max-duration SECONDS` (or `max-duration` in the config)
stops starting new mutants after that many seconds, waits for the running
ones and saves every finished result; the run then fails with
`N mutants not run yet`. Keep it below the CI job timeout. A run
stopped by `SIGTERM` (as CI runners stop jobs) saves its finished results too.
On a project with no cache yet, a first run may not fit in the CI timeout:
store the database after every run on the main branch (even a failed one), and
each next incremental run continues from the kills of the previous ones until
the whole project is covered.

The cache lives in the database file (`typemut.sqlite` by default): keep it
out of git (it is binary and changes on every run; with `--jobs` an untracked
file in the project fails the clean-tree check, so list it in `.gitignore` or
pass `--db` outside the project) and carry it between CI runs as a build
artifact or cache (see [Keeping the database between CI runs](ci-database.md)).

**Limits.** Reuse trusts the checker's output and typemut's import graph. For
every imported project module both its `.py` file and its `.pyi` stub are
tracked, so adding a stub next to a module (or a module next to a stub)
reruns the kills that depend on it. A file the checker reads that is not
imported (a plugin config, a stub found through `mypy_path` outside the
project, a new module that shadows another on the search path) is not
tracked; list it in
`cache-key-files` if a change to it can turn a kill into a survivor. For a
checker run by name without a project runner (`mypy src`, `npx pyright`), the
Python version is that of the `python` on `PATH`, which may not be the one the
checker runs with (a pipx-installed mypy), or may be missing (systems with only
`python3`): then a Python upgrade does not reset the cache; run the checker
through its environment (`uv run mypy`, `.venv/bin/mypy`) or use `--refresh`.
