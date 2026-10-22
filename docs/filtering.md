# Filtering

Annotations are automatically skipped when:

- The line contains `# type: ignore` or `# pragma: no mutate`
- The annotation is `Any` (mutations are meaningless — Any absorbs all types)
- `AddOptional` targets a function parameter (low signal — callers won't pass None)

## Ignoring library types per operator

By default every operator mutates every annotation, including library wrapper
types it knows nothing about (`Mapped[int]` → `Mapped[int] | None`). To silence
such noise, list the types an operator must not touch under
`[typemut.ignore-types]`, keyed by operator (same keys as `[typemut.operators]`):

```toml
[typemut.ignore-types]
all = ["django.db.models.*"]                        # every operator
add-optional = ["sqlalchemy.orm.Mapped"]
remove-optional = ["sqlalchemy.orm.Mapped"]
widen-container-type = ["sqlalchemy.orm.Mapped"]
widen-type = ["sqlalchemy.orm.DeclarativeBase"]
```

- An operator skips every annotation that references one of its ignored types
  (anywhere in it, e.g. `list[Mapped[int]]`); other operators still mutate it.
- An operator also drops mutations that would introduce an ignored type, e.g.
  `WidenType` widening a model to `DeclarativeBase`.
- Patterns are `fnmatch` globs matched against the qualified name the type is
  **imported under** in the file (`from sqlalchemy.orm import Mapped` →
  `sqlalchemy.orm.Mapped`), not where it is defined. Aliases (`import sqlalchemy.orm as orm`,
  `orm.Mapped`) and relative imports of your own packages are resolved.
- Names that aren't imported (builtins, classes defined in the same file) are never ignored.
- Plugins see annotations first and are not affected: with `plugins = ["sqlalchemy"]`,
  `Mapped[...]` is still mutated correctly (`Mapped[int]` → `Mapped[int | None]`).
- Unknown operator keys and invalid values are logged as warnings and skipped.

## Ignoring fields of class hierarchies per operator

Some fields are equivalent mutants by design: on response or serialization
models nobody reads the fields in typed code, so `AddOptional`, `WidenType` and
`WidenContainerType` on them always survive, while `RemoveOptional` and
`RemoveUnionMember` still catch real mismatches. List the classes whose fields
an operator must not touch under `[typemut.ignore-classes]`, keyed by operator
(same keys as `[typemut.operators]`):

```toml
[typemut.ignore-classes]
add-optional = ["myproject.api.BaseResponse"]
widen-type = ["myproject.api.BaseResponse"]
widen-container-type = ["myproject.api.BaseResponse"]
all = []                                            # every operator
```

- An operator skips the fields (class-level annotations, `name: str`) of every
  class that is, or inherits from, one of its ignored classes, directly or
  through any number of project classes, in any module. Other operators still
  mutate them.
- Parameters, return types and local variables of the methods of those classes
  are mutated as usual.
- Patterns are `fnmatch` globs matched against qualified names: the class's own
  (`myproject.api.ItemResponse`; nested classes as `module.Outer.Inner`) and
  those of all its bases. A base is named the way it is imported
  (`from pydantic import BaseModel` → `pydantic.BaseModel`), a project class
  also by the module it is defined in, so a class re-exported from a package's
  `__init__.py` matches both `myproject.api.BaseResponse` and
  `myproject.api.base.BaseResponse`.
- Plugins see annotations first and are not affected.
- Unknown operator keys and invalid values are logged as warnings and skipped.
