# Operators

typemut generates mutations of type annotations and checks whether the type checker catches them. Each mutation operator targets a specific class of type safety issues.

## RemoveUnionMember

Removes one member from a union type.

```python
# Original
def handle(value: int | str | float) -> None: ...

# Mutant: remove str
def handle(value: int | float) -> None: ...
```

**Survived = your code doesn't distinguish between union members.** If removing `str` from the union causes no type error, it means no code path relies on `value` being a `str`. The union may be overly broad, or the type checker doesn't see the code that handles `str` specifically.

## RemoveOptional

Removes `None` from `X | None`.

```python
# Original
def find_user(id: int) -> User | None: ...

# Mutant
def find_user(id: int) -> User: ...
```

**Survived = callers don't check for `None`.** The return type says "might be None" but no consumer's type annotations actually require a None-check. Either the None case is dead code, or callers use `# type: ignore`.

## AddOptional

Adds `| None` to return types and class fields (parameters are excluded — callers simply won't pass None, making those mutations uninformative).

```python
# Original
class Config:
    name: str

# Mutant
class Config:
    name: str | None
```

`None` goes inside quoted forward references (`'Node'` → `'Node | None'`; `'Node' | None`
passes the checker but raises `TypeError` at runtime) and inside type qualifiers
`ClassVar`, `Final`, `Required`, `NotRequired`, `ReadOnly` and `InitVar`, also when
spelled `typing.ClassVar` (`ClassVar[int]` → `ClassVar[int | None]`; `ClassVar[int] | None`
is not a type). A bare `ClassVar`/`Final` (`x: Final = 1`) is not mutated.

**Survived = consumers don't rely on non-None guarantee.** The field claims to always have a value, but no typed code would break if it could be `None`. This often reveals missing type coverage in code that reads the field.

## WidenType

Replaces a concrete class with its parent (base) class to find places where a more abstract type could be used.

```python
class Animal: ...
class Cat(Animal): ...
class Dog(Animal): ...

# Original
def feed(pet: Cat) -> None: ...

# Mutant
def feed(pet: Animal) -> None: ...
```

**Survived = the code doesn't rely on the concrete subclass.** The function could accept the broader base type, suggesting the annotation is more specific than necessary.

- Only project classes are widened, to their first base. A name is resolved through the
  imports of the annotated file, so same-named classes of different modules (or a library
  class imported under a project class's name) are not mixed up.
- The base is written as the file can name it (an alias, `enum.IntEnum` after `import enum`),
  otherwise its import is added. Bases that cannot be imported are skipped: aliases
  (`_Base = UserDict`), classes defined under `if`/`try` or nested in another class, and
  bases whose name the file already uses for something else.
- `Page[str]` becomes `BaseModel` for `class Page(BaseModel, Generic[T])`; when the class
  passes type arguments to its base (`class Items(list[T])`), `Items[int]` is not widened.
- Names inside `Literal[...]`, call arguments (`Depends(Service)`) and parts of dotted
  names are not widened.

## RemoveLiteralMember

Removes one value from a multi-value `Literal[...]`.

```python
# Original
def open_file(mode: Literal["r", "w", "a"]) -> None: ...

# Mutant: remove "a"
def open_file(mode: Literal["r", "w"]) -> None: ...
```

**Survived = that literal value is never used.** No typed caller passes `"a"`, so the Literal is broader than the code actually needs.

## WidenContainerType

Replaces a concrete container with the next more abstract type.

```python
# Original
def total(items: list[int]) -> int: ...

# Mutant
def total(items: Sequence[int]) -> int: ...
```

**Widening steps:** `list`/`tuple` → `Sequence`, `set`/`frozenset` → `AbstractSet`, `dict` → `Mapping`, `Sequence`/`AbstractSet`/`Mapping` → `Collection`, `Collection` → `Iterable`. `tuple[X, ...]` becomes `Sequence[X]`, `Mapping[K, V]` becomes `Collection[K]`, and heterogeneous tuples like `tuple[int, str]` are skipped.

**Survived = the code only uses the abstract interface.** A parameter could accept the wider type; a return type could promise less.

## SwapIteratorGenerator

Widens iterator/generator types by one step: `Iterator` → `Iterable`, `Generator[Y, S, R]` → `Iterator[Y]`, and the async equivalents.

```python
# Original
def read_lines(path: str) -> Generator[str, None, None]: ...

# Mutant
def read_lines(path: str) -> Iterator[str]: ...
```

**Survived = nobody uses the extra capability.** Callers never call `next()` / `send()` or read the generator's return value, so the simpler type is enough.

## TypeVarVariance

Removes `covariant=True` / `contravariant=True` from a `TypeVar`, or adds either one to an invariant `TypeVar`. A flag the call already spells out (`covariant=False`) is not added again, and a `TypeVar` with `infer_variance=True` gets no added flag.

```python
# Original
T_co = TypeVar("T_co", covariant=True)

# Mutant
T_co = TypeVar("T_co")
```

**Survived = variance is not relied on (removal), or the TypeVar could be declared variant (addition).**
