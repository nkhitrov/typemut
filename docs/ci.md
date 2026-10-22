# Using in CI

`typemut run` and `typemut report` exit with code 0 regardless of survivors unless
you ask them to gate:

```bash
typemut run --fail-under 90                          # exit 1 if the mutation score is below 90%
typemut run --baseline typemut-baseline.json         # exit 1 on survivors not in the baseline
typemut run --baseline typemut-baseline.json --update-baseline   # accept the current survivors
```

A **baseline** is a JSON file of survived mutants you have reviewed and accept
(e.g. equivalent mutants the type checker can never kill). Commit it and run with
`--baseline` in CI: known survivors pass, new ones fail the build and are listed.
Entries are matched by file, operator, original and mutated annotation, and the
text of the source line — not its number, so edits elsewhere in a file keep the
baseline valid. Entries that no longer survive are reported; rerun with
`--update-baseline` to drop them.

`run` and `report` also exit with code 1 while any mutant is still pending (a run
stopped by `--max-duration`, an interrupted `exec`), and then do not update the
baseline: a gate on incomplete results would pass by accident.

Mutation testing is slow, so use `--jobs N` in CI (it needs a clean git working tree,
see [Parallel runs](parallel.md)), and `--incremental` with the database kept
between CI runs (see [Incremental runs](incremental.md) and
[Keeping the database between CI runs](ci-database.md)). typemut runs this on itself — see `make mutate` and
[`.github/workflows/ci.yml`](https://github.com/nkhitrov/typemut/blob/main/.github/workflows/ci.yml).
