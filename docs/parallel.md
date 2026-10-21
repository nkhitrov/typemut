# Parallel runs

Each mutant is a full type checker run, so a single worker is slow on a real
project. `--jobs N` runs mutants on N workers in parallel:

```bash
git status --porcelain               # must print nothing: workers only see committed code
typemut run --jobs 8                 # 8 type checker processes at once
```

With `--jobs` greater than 1, typemut creates N temporary `git worktree`s of the
current commit, splits the mutants between them (all mutants of one file go to
the same worker), runs each worker in its own process and removes the worktrees
at the end. What this means for your project:

- **The working tree must be clean.** Uncommitted or untracked files would not
  be in the worktrees, so typemut refuses to start and lists them. Commit or
  stash them first.
- **`test-command` runs inside each worktree**, not in your project directory.
  Keep `module-path` and paths in `test-command` relative to the project root.
  Git-ignored files (`.venv`, generated code) are not copied: the type checker
  must be callable without them — e.g. installed in an activated virtualenv or
  on `PATH`.
- **The type checker's cache is copied into each worktree**, so workers start
  warm: the baseline check fills it in the project first, then every new
  worktree gets a copy with modification times and symlinks kept (mypy drops
  cache entries whose times differ). For mypy that is the directory shown as
  `cache:` in the `Type checker:` line (see [Type checkers](type-checkers.md)),
  copied only when it is configured as a relative path inside the project,
  under the configured name (a symlinked `.mypy_cache` lands in the worktree
  as `.mypy_cache`, where mypy looks for it). mypy in a worktree finds an
  absolute cache directory (`MYPY_CACHE_DIR=/abs/path`, an absolute
  `--cache-dir` or `cache_dir`, or one built from `~` or `$VAR`) at the same
  place as in the project, so all workers share that one cache instead (a
  warning says so); use a relative path inside the project to give each
  worker its own copy. A cache outside the project (`../mypy-cache`) is
  neither listed nor copied, and workers start cold; `--cache-dir=/dev/null`
  turns mypy's cache off, so there is nothing to copy or warn about. pyright
  and `generic` have no cache to copy. A missing cache is skipped and a failed
  copy is logged as a warning; that worker then starts cold. If the copy is
  interrupted (Ctrl-C), the half-made worktree is removed.
- **Pick N by CPU cores and memory**: every worker runs its own type checker
  process (mypy on a large project can take gigabytes of RAM). The number of
  CPU cores is a good start.
- The baseline check (type checker on unmodified code) runs once, in the
  project itself, before the workers start.

`--jobs` is also available on `typemut exec`. Without it (or with `--jobs 1`)
mutants run one by one directly in your project, which needs neither git nor a
clean tree.
