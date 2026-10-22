# Type checkers

typemut runs `test-command` as is, but it reads the output with a plugin for the
type checker that command runs. The plugin tells a real kill from a mutant that
merely broke the code: a failure whose only errors are a missing name, a syntax
error or an invalid type is recorded as `error`, not `killed`. It also finds the
checker's config files and cache directory. The checker's version, the files
with errors and which project files a file imports are known to the plugin
too: [incremental runs](incremental.md) use them to tell whether
an earlier kill can be reused.

| `checker` | Recognised executables | Errors counted as broken code |
|-----------|------------------------|-------------------------------|
| `mypy` | `mypy`, `dmypy` | `[name-defined]`, `[syntax]`, `[valid-type]` |
| `pyright` | `pyright` | `reportUndefinedVariable`, `reportInvalidTypeForm`, errors without a rule (syntax errors) |
| `basedpyright` | `basedpyright` | same as `pyright` (a subclass: the output format is the same) |
| `generic` | — | mypy-style `[code]` at the end of any output line, as above |

By default (`checker = "auto"`) the checker is detected from `test-command`:
a recognised executable counts when it is the command itself, possibly after
environment assignments, `env`/`exec`/`time`, or a runner (`uv run`,
`poetry run`, `pipx run`, `pdm run`, `hatch run`, `rye run`, `pnpm exec`,
`uvx`, `npx`, `bunx`, `python -m`), in any command of a chain
(`uv run mypy src`, `python -m mypy -p app`, `cd src && npx pyright`).
Runner options are skipped, with their values (`uv run --group dev mypy`,
`npx -p pyright pyright`). An
executable name passed to another tool (`tox -e mypy`,
`pre-commit run mypy --all-files`) is not detected. A command that runs none
of them (`make typecheck`, a script, a wrapper like `tox`), or more than one
(`mypy src && pyright src`), gets the `generic` checker and a warning; name the
checker instead:

```toml
[typemut]
test-command = "make typecheck"
checker = "mypy"
```

The run prints the checker it uses, with the config files it found and the
cache directory it would use (and, if configured as a relative path inside
the project, copy into each worktree with `--jobs`), relative to the project
root (`Type checker: mypy (config: pyproject.toml; cache: .mypy_cache)`); the
cache is listed even before mypy has created it. mypy's cache directory comes
from `--cache-dir`, `MYPY_CACHE_DIR`, `cache_dir` in its config, or
`.mypy_cache`, with `~` and `$VAR` expanded as mypy does.
An unknown `checker` name is logged as a warning and `generic` is used. mypy's
`--pretty`, `--show-column-numbers` and `--show-error-end` output is understood;
only errors count (mypy notes, pyright warnings and information are ignored).
Both stdout and stderr are parsed, so noise from wrappers such as `uv run` on
stderr does not hide the checker's errors.

Incremental runs reuse earlier kills only while the checker's version is the
same, and do not use the cache at all while it is unknown. It is taken from `test-command` up to the checker executable plus `--version`,
as written there (`cd backend && uv run mypy .` -> `cd backend && uv run mypy --version`:
of the commands before the checker only `cd` and `pushd` are kept). If the
command does not run the executable directly (`tox -e mypy`, `make typecheck`),
set `checker-version-command`, e.g. `checker-version-command = "npx pyright --version"`;
the first `X.Y.Z` in its output is the version. `generic` only has a version
when `checker-version-command` is set, but it never reuses kills anyway: it
cannot tell which files they depend on.

## Third-party checkers

A package can ship a checker plugin: subclass `typemut.checkers.base.TypeChecker`
and register it under the `typemut.checkers` entry point group. The entry point
name is the value for `checker = ...`:

```toml
# pyproject.toml of the plugin package
[project.entry-points."typemut.checkers"]
pytype = "typemut_pytype:PytypeChecker"
```

```python
from collections.abc import Iterable

from typemut.checkers.base import Diagnostic, TypeChecker


class PytypeChecker(TypeChecker):
    name = "pytype"
    executables = frozenset({"pytype"})

    def parse_output(self, output: str) -> Iterable[Diagnostic]:
        ...  # one Diagnostic(path, code) per error
```

Set `name`, `executables` (used for detection and the version command),
`false_kill_codes` and `config_names` (config files the checker reads from the
project root), and override `parse_output(output)` to return a
`Diagnostic(path, code)` (from `typemut.checkers.base`) for every error in one
output stream. `executables` should not overlap those of another checker:
`checker = "auto"` falls back to `generic` when a command matches two
unrelated checkers. The one exception is a subclass of a checker that shares
its executables (e.g. `class StrictMypyChecker(MypyChecker)` with the
inherited `mypy`): auto-detection then picks the subclass instead of its base.
Two such subclasses of the same checker installed together match both, so set
`checker = "<name>"` explicitly. `config_files`, `cache_paths` (cache
directories inside the project), `worktree_cache_paths` (those copied into
each worktree; by default all of `cache_paths`, mypy leaves out a cache
configured by an absolute path), `python_version` and `dependencies` (by
default: the project files reachable through imports; `None` means that kill
is not reused) can be overridden too. A checker that can never tell which files a kill depends on
(e.g. its output carries no file paths) should set
`traces_dependencies = False`: incremental runs then neither reuse nor store
its results and leave the cache alone, as with `generic`. The constructor takes
`(test_command, version_command, runner, graph=None, environ=None)`; *environ*
is the environment the checker runs with (the process environment by default). An entry point that fails to import
or does not name a `TypeChecker` subclass is logged as a warning and skipped.
