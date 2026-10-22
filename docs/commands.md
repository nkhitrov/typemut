# Commands

Global option: `-C, --project-dir PATH` — change to this directory before running
(the target project's root, where `typemut.toml` lives).

| Command | Description |
|---------|-------------|
| `typemut run` | Full pipeline: discover mutations, run the type checker on each, show the report |
| `typemut init` | Discover mutations and store them in SQLite (replaces previous results; the [result cache](incremental.md) keeps the kills of incremental runs) |
| `typemut exec` | Run the type checker against each **pending** mutation |
| `typemut report` | Show the terminal report |
| `typemut html` | Generate the HTML report with diffs |

`init` + `exec` + `report` are the steps of `run`. Running them separately lets
you resume: results are saved as they arrive, so after an interrupted `exec`
(Ctrl+C, CI timeout) run `typemut exec` again and it continues with the
mutants that are still pending.

## `typemut run`

| Option | Default | Description |
|--------|---------|-------------|
| `--config PATH` | `typemut.toml` | Config file |
| `--db PATH` | `db` from config (`typemut.sqlite`) | Database file |
| `--jobs N` | `1` | Number of parallel workers (see [Parallel runs](parallel.md)) |
| `--incremental / --no-incremental` | `incremental` from config (off) | Reuse kills of earlier runs whose files are unchanged (see [Incremental runs](incremental.md)) |
| `--refresh` | — | Run every mutant without reusing anything, and store the results for later incremental runs |
| `--max-duration SECONDS` | `max-duration` from config (none) | Start no new mutant after this many seconds; finished results are saved |
| `--fail-under PERCENT` | — | Exit with code 1 if the mutation score is below this value |
| `--baseline PATH` | — | JSON file of accepted survivors; exit with code 1 on any other survivor |
| `--update-baseline` | — | Write the current survivors to the `--baseline` file instead of checking it |

## `typemut init`

| Option | Default | Description |
|--------|---------|-------------|
| `--config PATH` | `typemut.toml` | Config file |
| `--db PATH` | `db` from config (`typemut.sqlite`) | Database file |

## `typemut exec`

| Option | Default | Description |
|--------|---------|-------------|
| `--config PATH` | `typemut.toml` | Config file |
| `--db PATH` | `db` from config (`typemut.sqlite`) | Database file |
| `--jobs N` | `1` | Number of parallel workers |
| `--incremental / --no-incremental` | `incremental` from config (off) | Reuse kills of earlier runs whose files are unchanged |
| `--refresh` | — | Run the pending mutants without reusing cached kills, and store the results for later incremental runs (`exec` only runs pending mutants: use `run --refresh`, or `init` first, to recheck every mutant) |
| `--max-duration SECONDS` | `max-duration` from config (none) | Start no new mutant after this many seconds |

## `typemut report`

| Option | Default | Description |
|--------|---------|-------------|
| `--db PATH` | `typemut.sqlite` | Database file |
| `--fail-under PERCENT` | — | Exit with code 1 if the mutation score is below this value |
| `--baseline PATH` | — | JSON file of accepted survivors; exit with code 1 on any other survivor |
| `--update-baseline` | — | Write the current survivors to the `--baseline` file instead of checking it |

## `typemut html`

| Option | Default | Description |
|--------|---------|-------------|
| `--db PATH` | `typemut.sqlite` | Database file |
| `-o, --output PATH` | `typemut-report.html` | Output file |
| `--open` | — | Open the report in a browser |
