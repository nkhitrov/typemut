"""TypeVarVariance operator — mutate variance flags on TypeVar declarations."""

from __future__ import annotations

from parso.python.tree import BaseNode, Leaf

from typemut.discovery import AnnotationContext, _node_code
from typemut.operators.base import Mutation, TypeMutationOperator
from typemut.registry import Registry


class TypeVarVariance(TypeMutationOperator):
    name = "TypeVarVariance"

    def find_mutations(
        self,
        node: BaseNode | Leaf,
        context: AnnotationContext,
        registry: Registry,
    ) -> list[Mutation]:
        if context != AnnotationContext.TYPEVAR:
            return []

        original = _node_code(node)
        args_node = _find_args_trailer(node)
        if args_node is None:
            return []

        has_covariant, has_contravariant = _detect_variance(args_node)
        mutations: list[Mutation] = []
        line = node.start_pos[0]
        col = node.start_pos[1]

        if has_covariant:
            # Mutation 1: remove covariant=True
            mutated = _remove_kwarg(original, "covariant")
            mutations.append(
                Mutation(
                    file="",
                    operator=self.name,
                    line=line,
                    col=col,
                    original=original,
                    mutated=mutated,
                    description="Remove covariant=True",
                )
            )
            # Mutation 2: swap to contravariant=True
            mutated = _replace_kwarg(original, "covariant", "contravariant")
            mutations.append(
                Mutation(
                    file="",
                    operator=self.name,
                    line=line,
                    col=col,
                    original=original,
                    mutated=mutated,
                    description="Replace covariant=True with contravariant=True",
                )
            )
        elif has_contravariant:
            # Mutation 1: remove contravariant=True
            mutated = _remove_kwarg(original, "contravariant")
            mutations.append(
                Mutation(
                    file="",
                    operator=self.name,
                    line=line,
                    col=col,
                    original=original,
                    mutated=mutated,
                    description="Remove contravariant=True",
                )
            )
            # Mutation 2: swap to covariant=True
            mutated = _replace_kwarg(original, "contravariant", "covariant")
            mutations.append(
                Mutation(
                    file="",
                    operator=self.name,
                    line=line,
                    col=col,
                    original=original,
                    mutated=mutated,
                    description="Replace contravariant=True with covariant=True",
                )
            )
        else:
            # No variance — add covariant=True and contravariant=True
            mutated_co = _add_kwarg(original, "covariant=True")
            mutations.append(
                Mutation(
                    file="",
                    operator=self.name,
                    line=line,
                    col=col,
                    original=original,
                    mutated=mutated_co,
                    description="Add covariant=True",
                )
            )
            mutated_contra = _add_kwarg(original, "contravariant=True")
            mutations.append(
                Mutation(
                    file="",
                    operator=self.name,
                    line=line,
                    col=col,
                    original=original,
                    mutated=mutated_contra,
                    description="Add contravariant=True",
                )
            )

        return mutations


def _find_args_trailer(node: BaseNode | Leaf) -> BaseNode | None:
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


def _detect_variance(trailer: BaseNode) -> tuple[bool, bool]:
    """Detect covariant=True and contravariant=True in a call's arguments."""
    code = _node_code(trailer)
    has_covariant = "covariant=True" in code
    has_contravariant = "contravariant=True" in code
    return has_covariant, has_contravariant


def _remove_kwarg(text: str, kwarg_name: str) -> str:
    """Remove a keyword argument like 'covariant=True' from a call string."""
    import re

    # Remove ', kwarg=True' or 'kwarg=True, ' patterns
    # Pattern: leading comma + spaces + kwarg=True
    result = re.sub(r",\s*" + kwarg_name + r"=True", "", text)
    if result != text:
        return result
    # Pattern: kwarg=True + trailing comma + spaces
    result = re.sub(kwarg_name + r"=True\s*,\s*", "", text)
    return result


def _replace_kwarg(text: str, old_kwarg: str, new_kwarg: str) -> str:
    """Replace one kwarg name with another, keeping =True."""
    return text.replace(old_kwarg + "=True", new_kwarg + "=True")


def _add_kwarg(text: str, kwarg: str) -> str:
    """Add a keyword argument before the closing paren of a call."""
    # Find the last ')' and insert before it
    idx = text.rfind(")")
    if idx == -1:
        return text
    # Check if there are existing args (non-empty parens)
    open_idx = text.find("(")
    if open_idx == -1:
        return text
    inner = text[open_idx + 1 : idx].strip()
    if inner:
        return text[:idx] + ", " + kwarg + text[idx:]
    else:
        return text[:idx] + kwarg + text[idx:]
