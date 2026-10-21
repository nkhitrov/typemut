# Contributing

## Development

```bash
make install    # create venv and install with dev deps
make test       # run tests
make lint       # run ruff, flake8/wps, mypy
make mutate     # run typemut on itself (--incremental: reuses kills in typemut.sqlite);
                # fails on survivors missing from typemut-baseline.json
                # extra options: make mutate MUTATE_ARGS="--refresh"
make mutate-baseline  # accept the current survivors (review the diff before committing)
make docs       # serve this documentation at http://127.0.0.1:8000
make docs-build # build it into site/ (fails on warnings)
```

## Dependencies

- **parso** — CST parsing (preserves formatting and whitespace)
- **rich** — terminal reporting
- **click** — CLI framework
