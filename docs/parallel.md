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
- The baseline check (type checker on unmodified code) runs in the project
  itself, then once more in the first worktree before any mutant runs. If it
  passes in the project but fails in the worktree, typemut stops with the
  first errors: the type checker sees a different project there, and every
  mutant would be "killed" by errors it did not cause. Common causes: the
  project is installed in editable mode (a `.pth` file points at the project
  root, so mypy skips e.g. `docs_src/` or `examples/` there as an installed
  package but checks them in a worktree), files the checker needs are
  git-ignored or untracked, or `test-command` / the checker config uses
  absolute paths into the project. Make the checker pass in a fresh
  `git worktree add` checkout (e.g. exclude those directories in its config)
  or use `--jobs 1`. One worktree stands for all: they are checkouts of the
  same commit with the same carried cache.

After every `exec` (with or without `--jobs`), typemut also warns when at
least 90% of the kills (of at least 10 with errors the checker reports) have
errors in one and the same file that they did not mutate: such kills most
likely come from errors unrelated to the mutants, e.g. an environment that
differs from the baseline check's. The mutant outputs in the report show
them. The warning only compares paths relative to the project, so it misses
checkers that print absolute paths inside the worktrees (pyright) — there
the worktree baseline check above is what catches it.

`--jobs` is also available on `typemut exec`. Without it (or with `--jobs 1`)
mutants run one by one directly in your project, which needs neither git nor a
clean tree.
