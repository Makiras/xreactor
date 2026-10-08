"""Experimental class-based functional coverage v2 authoring API.

Public names are scoped to this namespace. The existing xreactor coverage API
and its execution/counting implementation remain available.
"""
from ..coverage import IllegalPolicy, OverlapPolicy
from ._compiler import CompiledGroup
from ._declarations import (
    Bin, BinRule, BinSelection, BoundCross, BoundPoint, CoverPoint,
    CoverageFragment, CoverageReferenceError, Cross, DefinitionError,
    FieldRef, Fields, Gate, Iff, PointDeclaration, SampleTypeError,
    SignalBinding, SignalBindingBase, covergroup, coverpoint, wire,
)
from ._runtime import CoverGroup, CoverageSnapshot

__all__ = [
    "Bin", "BinRule", "BinSelection", "BoundCross", "BoundPoint", "CompiledGroup",
    "CoverGroup", "CoverPoint", "CoverageFragment", "CoverageReferenceError",
    "CoverageSnapshot", "Cross", "DefinitionError", "FieldRef", "Fields", "Gate",
    "Iff", "IllegalPolicy", "OverlapPolicy", "PointDeclaration", "SampleTypeError",
    "SignalBinding", "SignalBindingBase", "covergroup", "coverpoint", "wire",
]
