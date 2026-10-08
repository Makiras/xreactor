"""Typed authoring API backed by the existing CoverGroup and native collector."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Generic, Literal, Self, TypeVar

from ..coverage import CoverGroup as CoreCoverGroup, IllegalPolicy
from ..signals import signal_width
from ._compiler import CompiledGroup, compile_group, _json
from ._declarations import (
    DefinitionError, SampleTypeError, SignalBindingBase, SignalBinding, normalize, scalar_type,
)

S = TypeVar("S")


def _validated_snapshot(value, plan, path):
    expected, children = plan
    if type(value) is not expected:
        raise SampleTypeError(f"{path}: expected {expected.__name__}, got {type(value).__name__}")
    if scalar_type(expected):
        return normalize(value)
    return {name: _validated_snapshot(getattr(value, name), child, f"{path}.{name}")
            for name, child in children}


@dataclass(frozen=True)
class CoverageSnapshot:
    _json: str

    @property
    def samples(self) -> int:
        return json.loads(self._json)["samples"]

    @property
    def coverage(self) -> float:
        return json.loads(self._json)["coverage"]

    def to_json(self) -> str:
        return self._json

    def to_dict(self) -> dict:
        return json.loads(self._json)


class CoverGroup(Generic[S]):
    """Typed declaration frontend owning exactly one existing runtime engine."""

    def __init_subclass__(cls, **options):
        super().__init_subclass__()
        allowed = {"schema_id", "contract", "iff"}
        if options.keys() - allowed:
            raise TypeError(f"unknown coverage class options: {sorted(options.keys() - allowed)}")
        cls._coverage_group_options = dict(options)

    def __init__(self, *, instance: str, illegal_policy: IllegalPolicy = IllegalPolicy.RAISE,
                 run_id: str | None = None) -> None:
        self._compiled = type(self).compile()
        self._engine = self._compiled.schema.instantiate(instance, illegal_policy=illegal_policy,
                                                         run_id=run_id, contract=self._compiled.sampling_contract)
        self._binding_json: str | None = None

    @classmethod
    def compile(cls) -> CompiledGroup[S]:
        return compile_group(cls)

    @property
    def runtime(self) -> CoreCoverGroup:
        """The sole counter store, also passed to Execution and CoverageDatabase."""
        return self._engine

    @property
    def samples(self) -> int:
        self.sync()
        return self._engine.samples

    @property
    def gated(self) -> int:
        self.sync()
        return self._engine.gated

    @property
    def coverage(self) -> float:
        return self._engine.coverage

    def sync(self) -> None:
        self._engine.sync()

    def reset(self) -> None:
        self._engine.reset()

    def clear_history(self) -> None:
        self._engine.clear_history()

    def report(self) -> dict:
        return self._engine.report()

    def sample(self, sample: S) -> None:
        snapshot = _validated_snapshot(sample, self._compiled._validation, type(self).__name__)
        self._engine.sample(snapshot, details=False)

    def snapshot(self) -> CoverageSnapshot:
        return CoverageSnapshot(json.dumps(self.report(), ensure_ascii=False, sort_keys=True))

    def binding_contract_json(self) -> str | None:
        """Readable physical bindings without signal pointers or engine IDs."""
        return self._binding_json

    def bind(self, *, trigger: object, fields: Sequence[SignalBindingBase],
             strategy: Literal["auto", "native", "python"] = "auto", abort: object | None = None,
             accumulate: bool = False, overlap: bool = False,
             max_active: int | None = None) -> Self:
        if self._engine._collector is not None:
            raise RuntimeError("cannot rebind active coverage")
        expected = {field.path: field for field in self._compiled._fields}
        configured, bindings = {}, []
        for binding in fields:
            if not isinstance(binding, SignalBinding):
                raise DefinitionError("E_BINDING", type(self).__name__, "use wire(field_ref, signal)")
            field = binding.field
            if field.root is not self._compiled.sample_type or field.path not in expected:
                raise DefinitionError("E_BINDING_ROOT", ".".join(field.path), "field is not used by this group")
            if field.value_type is not expected[field.path].value_type:
                raise DefinitionError("E_BINDING_TYPE", ".".join(field.path), "field type differs from model")
            if field.value_type not in (int, bool):
                raise DefinitionError("E_BINDING_TYPE", ".".join(field.path),
                                      "clock-bound v2 inputs currently require int or bool")
            name = ".".join(field.path)
            if name in configured:
                raise DefinitionError("E_DUPLICATE_BINDING", name, "field is bound twice")
            width = signal_width(binding.source)
            if field.value_type is bool and width != 1:
                raise DefinitionError("E_BINDING_WIDTH", name, "bool requires exactly one physical bit")
            if binding.source_id is not None and (not isinstance(binding.source_id, str) or not binding.source_id):
                raise DefinitionError("E_SOURCE_ID", name, "source_id must be a nonempty stable string")
            configured[name] = binding.source
            bindings.append({"field": name, "width": width, "source_id": binding.source_id})
        missing = {".".join(path) for path in expected} - configured.keys()
        if missing:
            raise DefinitionError("E_MISSING_BINDING", type(self).__name__, f"unbound fields: {sorted(missing)}")
        if any(item["source_id"] is None for item in bindings) and not json.loads(self._compiled._input_json)["observer_contract_explicit"]:
            raise DefinitionError("E_CONTRACT", type(self).__name__,
                                  "opaque signal identities require an explicit versioned observer contract")
        # Stable field and source identities form the contract; backend choice does not.
        binding_digest = sha256(_json(sorted(bindings, key=lambda item: item["field"])).encode()).hexdigest()
        contract = f"{self._compiled.sampling_contract}|binding={binding_digest}"
        self._engine.bind(trigger=trigger, fields=configured, strategy=strategy, abort=abort,
                          accumulate=accumulate, contract=contract, overlap=overlap, max_active=max_active)
        self._binding_json = json.dumps({"binding_digest": binding_digest,
                                        "observer_contract": self._compiled.contract,
                                        "bindings": sorted(bindings, key=lambda item: item["field"]),
                                        "opaque_sources": sorted(item["field"] for item in bindings if item["source_id"] is None)},
                                       ensure_ascii=False, indent=2, sort_keys=True)
        return self
