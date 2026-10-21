# Configuration

All keys of `typemut.toml` with their defaults. See [Operators](operators.md),
[Filtering](filtering.md) and [Plugins](plugins.md) for what they do.

```toml
[typemut]
module-path = "src/myproject"           # directory to scan for annotations
test-command = "make typecheck"         # command to run type checker
timeout = 30                            # seconds per mutation
excluded-modules = ["src/vendor/*.py"]  # glob patterns to skip
skip-comments = ["type: ignore", "pragma: no mutate"]
db = "typemut.sqlite"                   # database file
plugins = ["sqlalchemy"]                # library plugins: sqlalchemy, fastapi, faststream, dmr; none by default
checker = "mypy"                        # mypy, pyright, basedpyright, generic; default "auto" detects it
                                        # from test-command (set it when test-command is a wrapper like make)
# checker-version-command = "mypy --version"  # optional; for incremental runs;
                                        # default: test-command up to the checker + --version
incremental = false                     # reuse kills of earlier runs (--incremental / --no-incremental)
# max-duration = 1500                   # seconds; start no new mutant after it (--max-duration)
cache-key-files = ["uv.lock", "poetry.lock", "requirements*.txt"]  # glob patterns relative to the
                                        # project root (absolute, empty or invalid ones are skipped with a warning);
                                        # a change to any drops every cached result

[typemut.operators]
# all enabled by default, disable selectively
remove-union-member = true
remove-literal-member = true
widen-type = true
remove-optional = true
add-optional = true
widen-container-type = true
swap-iterator-generator = true
typevar-variance = true

[typemut.ignore-types]
# qualified type patterns each operator must not touch; "all" applies to every operator
all = []
add-optional = ["sqlalchemy.orm.Mapped"]

[typemut.ignore-classes]
# qualified class patterns whose fields (and their subclasses' fields) each operator
# must not touch; "all" applies to every operator
all = []
add-optional = ["myproject.api.BaseResponse"]

[typemut.entrypoints]
# qualified name patterns of framework-called handlers whose signatures are not mutated
decorators = []                         # functions decorated with these
base-classes = []                       # methods of classes inheriting from these
parameter-types = []                    # functions with a parameter annotated with these
```
