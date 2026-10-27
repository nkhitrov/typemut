"""TypeVarVariance operator — mutate variance flags on TypeVar declarations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from parso.python.tree import BaseNode, Leaf

from typemut.model import AnnotationContext, Mutation
from typemut.operators.base import TypeMutationOperator
from typemut.registry import Registry

_VARIANCE_KWARGS = ("covariant", "contravariant")


class TypeVarVariance(TypeMutationOperator):
    name = "TypeVarVariance"
    config_key = "typevar-variance"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        if context != AnnotationContext.TYPEVAR:
            return []

        original = self._node_code(node)
        args_node = self._find_args_trailer(node)
        if args_node is None:
            return []

        items = self._call_items(args_node)
        flags = self._variance_flags(items)
        mutations: list[Mutation] = []
        line = node.start_pos[0]
        col = node.start_pos[1]

        # Swapping co <-> contra is not generated: a covariant TypeVar sits in
        # output positions by definition, so the swap is always killed.
        enabled = [name for name in _VARIANCE_KWARGS if flags.get(name) is True]
        if enabled:
            existing = enabled[0]
            mutations.append(
                Mutation(
                    file="",
                    operator=self.name,
                    line=line,
                    col=col,
                    original=original,
                    mutated=self._remove_kwarg(node, original, items, existing),
                    description=f"Remove {existing}=True",
                )
            )
        elif flags.get("infer_variance") is not True:
            # No variance: add each flag the call does not spell out yet
            for name in _VARIANCE_KWARGS:
                if name in flags:
                    continue
                mutations.append(
                    Mutation(
                        file="",
                        operator=self.name,
                        line=line,
                        col=col,
                        original=original,
                        mutated=self._add_kwarg(node, original, args_node, f"{name}=True"),
                        description=f"Add {name}=True",
                    )
                )

        return mutations

    def _find_args_trailer(self, node: BaseNode | Leaf) -> BaseNode | None:
        """Find the trailer node containing the call arguments: '(' ... ')'."""
        if isinstance(node, BaseNode):
            for child in node.children:
                if (
                    isinstance(child, BaseNode)
                    and child.type == "trailer"
                    and child.children
                    and isinstance(child.children[0], Leaf)
                    and child.children[0].value == "("
                ):
                    return child
        return None

    def _call_items(self, trailer: BaseNode) -> Sequence[BaseNode | Leaf]:
        """Arguments and commas between the call's parentheses, in order."""
        inner = trailer.children[1:-1]
        if len(inner) == 1 and isinstance(inner[0], BaseNode) and inner[0].type == "arglist":
            return list(inner[0].children)
        return list(inner)

    def _variance_flags(self, items: Iterable[BaseNode | Leaf]) -> Mapping[str, bool]:
        """Map variance keywords given in the call to whether they are ``True``."""
        flags: dict[str, bool] = {}
        for item in items:
            name = self._kwarg_name(item)
            if isinstance(item, BaseNode) and name in {*_VARIANCE_KWARGS, "infer_variance"}:
                flags[name] = self._node_code(item.children[2]) == "True"
        return flags

    def _kwarg_name(self, item: BaseNode | Leaf) -> str | None:
        """Keyword of a ``name=value`` argument, ``None`` for anything else."""
        if not isinstance(item, BaseNode) or item.type != "argument":
            return None
        keyword, equals = item.children[0], item.children[1]
        if isinstance(keyword, Leaf) and isinstance(equals, Leaf) and equals.value == "=":
            return keyword.value
        return None

    def _offset(self, node: BaseNode | Leaf, pos: tuple[int, int]) -> int:
        """Offset of a source position inside the code of ``node``."""
        line, col = pos
        first_line, first_col = node.start_pos
        if line == first_line:
            return col - first_col
        lines = self._node_code(node).splitlines(keepends=True)
        return sum(len(text) for text in lines[: line - first_line]) + col

    def _remove_kwarg(
        self,
        node: BaseNode | Leaf,
        text: str,
        items: Sequence[BaseNode | Leaf],
        kwarg_name: str,
    ) -> str:
        """Cut a keyword argument out of the call, with the comma it owns."""
        index = next(i for i, item in enumerate(items) if self._kwarg_name(item) == kwarg_name)
        arg = items[index]
        if index + 2 < len(items):
            # Followed by another argument: drop up to where that one starts
            start, end = arg.start_pos, items[index + 2].start_pos
        elif index + 1 < len(items):
            # Last argument with a trailing comma: keep the previous comma
            start = items[index - 1].end_pos if index else arg.start_pos
            end = items[index + 1].end_pos
        else:
            # Last argument without a trailing comma: drop the comma before it
            start = items[index - 2].end_pos if index else arg.start_pos
            end = arg.end_pos
        return self._splice(node, text, start, end, "")

    def _add_kwarg(self, node: BaseNode | Leaf, text: str, trailer: BaseNode, kwarg: str) -> str:
        """Add a keyword argument right after the call's last argument."""
        items = self._call_items(trailer)
        if not items:
            insert_at, insertion = trailer.children[0].end_pos, kwarg
        elif items[-1].type == "operator":
            # Trailing comma: the new argument gets one too
            insert_at, insertion = items[-1].end_pos, f" {kwarg},"
        else:
            insert_at, insertion = items[-1].end_pos, f", {kwarg}"
        return self._splice(node, text, insert_at, insert_at, insertion)

    def _splice(
        self,
        node: BaseNode | Leaf,
        text: str,
        start: tuple[int, int],
        end: tuple[int, int],
        insertion: str,
    ) -> str:
        """Replace the code of ``node`` between two source positions."""
        offset = self._offset(node, start)
        length = self._offset(node, end) - offset
        return text[:offset] + insertion + text[offset + length :]
