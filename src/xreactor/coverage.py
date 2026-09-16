from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Any, Iterable, Sequence
import warnings


SCHEMA_VERSION = 1
Scalar = bool | int | str | None


class BinKind(str, Enum):
    NORMAL = "normal"
    IGNORE = "ignore"
    ILLEGAL = "illegal"
    DEFAULT = "default"


class IllegalPolicy(str, Enum):
    RAISE = "raise"
    RECORD = "record"


class OverlapPolicy(str, Enum):
    ALLOW = "allow"
    WARN = "warn"
    ERROR = "error"


class CoverageSchemaError(ValueError):
    pass


class CoverageMergeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class IllegalHit:
    group: str
    item: str
    bin_name: str
    value: Any
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "item": self.item,
            "bin": self.bin_name,
            "value": _json_value(self.value),
            "metadata": _json_value(dict(self.metadata)),
        }


class IllegalBinError(AssertionError):
    def __init__(self, hits: Sequence[IllegalHit]) -> None:
        if not hits:
            raise ValueError("IllegalBinError requires at least one hit")
        self.hits = tuple(hits)
        first = self.hits[0]
        suffix = "" if len(self.hits) == 1 else f" (+{len(self.hits) - 1} more)"
        super().__init__(
            f"coverage group {first.group!r}, item {first.item!r}: "
            f"value {first.value!r} hit illegal bin {first.bin_name!r}{suffix}"
        )


def _validate_scalar(value: Any) -> Scalar:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Enum):
        enum_value = value.value
        if enum_value is None or isinstance(enum_value, (bool, int, str)):
            return enum_value
    raise CoverageSchemaError(
        f"coverage schema values must be bool/int/str/None, got {type(value).__name__}"
    )


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    return repr(value)


@dataclass(frozen=True, slots=True)
class ValueMatcher:
    values: tuple[Scalar, ...]

    def __post_init__(self) -> None:
        normalized = tuple(_validate_scalar(value) for value in self.values)
        if not normalized:
            raise CoverageSchemaError("value bin must contain at least one value")
        if len(set(normalized)) != len(normalized):
            raise CoverageSchemaError("value bin contains duplicate values")
        object.__setattr__(self, "values", normalized)

    def matches(self, value: Any) -> bool:
        if isinstance(value, Enum):
            value = value.value
        return value in self.values

    def to_dict(self) -> dict[str, Any]:
        return {"type": "values", "values": list(self.values)}


@dataclass(frozen=True, slots=True)
class RangeMatcher:
    ranges: tuple[tuple[int, int], ...]

    def __post_init__(self) -> None:
        normalized: list[tuple[int, int]] = []
        for low, high in self.ranges:
            if isinstance(low, bool) or isinstance(high, bool):
                raise CoverageSchemaError("range bounds must be integers, not bool")
            if not isinstance(low, int) or not isinstance(high, int):
                raise CoverageSchemaError("range bounds must be integers")
            if high < low:
                raise CoverageSchemaError(f"range [{low}:{high}] is backwards")
            normalized.append((low, high))
        if not normalized:
            raise CoverageSchemaError("range bin must contain at least one range")
        object.__setattr__(self, "ranges", tuple(normalized))

    def matches(self, value: Any) -> bool:
        if isinstance(value, Enum):
            value = value.value
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return any(low <= value <= high for low, high in self.ranges)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "ranges", "ranges": [list(item) for item in self.ranges]}


@dataclass(frozen=True, slots=True)
class WildcardMatcher:
    value: int
    mask: int
    width: int

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise CoverageSchemaError("wildcard width must be positive")
        limit = (1 << self.width) - 1
        if self.value < 0 or self.mask < 0:
            raise CoverageSchemaError("wildcard value and mask must be non-negative")
        if self.value & ~limit or self.mask & ~limit:
            raise CoverageSchemaError("wildcard value/mask do not fit width")
        object.__setattr__(self, "value", self.value & self.mask)

    def matches(self, value: Any) -> bool:
        if isinstance(value, Enum):
            value = value.value
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return False
        return (value & self.mask) == self.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "wildcard",
            "value": self.value,
            "mask": self.mask,
            "width": self.width,
        }


@dataclass(frozen=True, slots=True)
class DefaultMatcher:
    def matches(self, value: Any) -> bool:
        del value
        return False

    def to_dict(self) -> dict[str, Any]:
        return {"type": "default"}


Matcher = ValueMatcher | RangeMatcher | WildcardMatcher | DefaultMatcher


def _matcher_from_dict(data: Mapping[str, Any]) -> Matcher:
    kind = data.get("type")
    if kind == "values":
        return ValueMatcher(tuple(data["values"]))
    if kind == "ranges":
        return RangeMatcher(tuple(tuple(item) for item in data["ranges"]))
    if kind == "wildcard":
        return WildcardMatcher(data["value"], data["mask"], data["width"])
    if kind == "default":
        return DefaultMatcher()
    raise CoverageSchemaError(f"unknown matcher type {kind!r}")


@dataclass(frozen=True, slots=True)
class BinSpec:
    matcher: Matcher
    kind: BinKind = BinKind.NORMAL
    at_least: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", BinKind(self.kind))
        if self.at_least <= 0:
            raise CoverageSchemaError("bin at_least must be positive")
        if isinstance(self.matcher, DefaultMatcher) and self.kind is not BinKind.DEFAULT:
            raise CoverageSchemaError("default matcher must use default bin kind")
        if self.kind is BinKind.DEFAULT and not isinstance(self.matcher, DefaultMatcher):
            raise CoverageSchemaError("default bin kind requires default matcher")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "at_least": self.at_least,
            "matcher": self.matcher.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BinSpec":
        return cls(
            _matcher_from_dict(data["matcher"]),
            BinKind(data["kind"]),
            data["at_least"],
        )


class Bin:
    """Serializable factories for hardware functional-coverage bins."""

    @staticmethod
    def values(*values: Scalar, at_least: int = 1) -> BinSpec:
        return BinSpec(ValueMatcher(tuple(values)), at_least=at_least)

    @staticmethod
    def range(low: int, high: int, *, at_least: int = 1) -> BinSpec:
        return BinSpec(RangeMatcher(((low, high),)), at_least=at_least)

    @staticmethod
    def ranges(*ranges: tuple[int, int], at_least: int = 1) -> BinSpec:
        return BinSpec(RangeMatcher(tuple(ranges)), at_least=at_least)

    @staticmethod
    def masked(
        value: int,
        mask: int,
        *,
        width: int | None = None,
        at_least: int = 1,
    ) -> BinSpec:
        inferred = max(value.bit_length(), mask.bit_length(), 1)
        return BinSpec(
            WildcardMatcher(value, mask, inferred if width is None else width),
            at_least=at_least,
        )

    @staticmethod
    def default() -> BinSpec:
        return BinSpec(DefaultMatcher(), BinKind.DEFAULT)

    @staticmethod
    def ignore(spec: BinSpec) -> BinSpec:
        if spec.kind is BinKind.DEFAULT:
            raise CoverageSchemaError("default bin cannot be ignored")
        return replace(spec, kind=BinKind.IGNORE)

    @staticmethod
    def illegal(spec: BinSpec) -> BinSpec:
        if spec.kind is BinKind.DEFAULT:
            raise CoverageSchemaError("default bin cannot be illegal")
        return replace(spec, kind=BinKind.ILLEGAL)

    @staticmethod
    def array(
        prefix: str,
        low: int,
        high: int,
        *,
        count: int | None = None,
        at_least: int = 1,
    ) -> dict[str, BinSpec]:
        if not prefix:
            raise CoverageSchemaError("array-bin prefix must not be empty")
        if high < low:
            raise CoverageSchemaError("array-bin range is backwards")
        size = high - low + 1
        bins = size if count is None else count
        if bins <= 0:
            raise CoverageSchemaError("array-bin count must be positive")
        bins = min(bins, size)
        quotient, remainder = divmod(size, bins)
        result: dict[str, BinSpec] = {}
        start = low
        for index in range(bins):
            span = quotient + (1 if index < remainder else 0)
            stop = start + span - 1
            result[f"{prefix}[{index}]"] = Bin.range(
                start, stop, at_least=at_least
            )
            start = stop + 1
        return result


@dataclass(frozen=True, slots=True)
class Iff:
    source: str
    values: tuple[Scalar, ...] = (True,)
    invert: bool = False
    _source_parts: tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.source:
            raise CoverageSchemaError("iff source must not be empty")
        normalized = tuple(_validate_scalar(value) for value in self.values)
        if not normalized:
            raise CoverageSchemaError("iff requires at least one accepted value")
        object.__setattr__(self, "values", normalized)
        object.__setattr__(self, "_source_parts", tuple(self.source.split(".")))

    @classmethod
    def equals(cls, source: str, value: Scalar) -> "Iff":
        return cls(source, (value,))

    @classmethod
    def not_equals(cls, source: str, value: Scalar) -> "Iff":
        return cls(source, (value,), True)

    def enabled(self, sample: Any) -> bool:
        value = _extract(sample, self._source_parts)
        if isinstance(value, Enum):
            value = value.value
        matched = value in self.values
        return not matched if self.invert else matched

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "values": list(self.values),
            "invert": self.invert,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "Iff | None":
        if data is None:
            return None
        return cls(data["source"], tuple(data["values"]), data["invert"])


def _extract(sample: Any, source: str | tuple[str, ...]) -> Any:
    parts = (source,) if isinstance(source, str) and "." not in source else (
        tuple(source.split(".")) if isinstance(source, str) else source
    )
    value = sample
    for part in parts:
        if isinstance(value, dict):
            try:
                value = value[part]
            except KeyError as error:
                label = source if isinstance(source, str) else ".".join(source)
                raise KeyError(f"coverage sample has no field {label!r}") from error
        else:
            try:
                value = getattr(value, part)
            except AttributeError as error:
                if isinstance(value, Mapping):
                    try:
                        value = value[part]
                        continue
                    except KeyError:
                        label = source if isinstance(source, str) else ".".join(source)
                        raise KeyError(
                            f"coverage sample has no field {label!r}"
                        ) from error
                label = source if isinstance(source, str) else ".".join(source)
                raise AttributeError(
                    f"coverage sample has no attribute path {label!r}"
                ) from error
    return value


@dataclass(frozen=True, slots=True)
class NamedBin:
    name: str
    spec: BinSpec

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, **self.spec.to_dict()}


@dataclass(frozen=True, slots=True)
class CoverPointDef:
    name: str
    bins: Mapping[str, BinSpec]
    source: str | None = None
    iff: Iff | None = None
    weight: int = 1
    goal: float = 100.0
    overlap: OverlapPolicy | str = OverlapPolicy.WARN
    description: str = ""
    _named_bins: tuple[NamedBin, ...] = field(init=False, repr=False)
    _normal_bins: tuple[NamedBin, ...] = field(init=False, repr=False)
    _ignore_bins: tuple[NamedBin, ...] = field(init=False, repr=False)
    _illegal_bins: tuple[NamedBin, ...] = field(init=False, repr=False)
    _default_bins: tuple[NamedBin, ...] = field(init=False, repr=False)
    _source_parts: tuple[str, ...] = field(init=False, repr=False)
    _normal_exact: Mapping[Scalar, tuple[str, ...]] = field(init=False, repr=False)
    _normal_dynamic: tuple[NamedBin, ...] = field(init=False, repr=False)
    _ignore_exact: Mapping[Scalar, tuple[str, ...]] = field(init=False, repr=False)
    _ignore_dynamic: tuple[NamedBin, ...] = field(init=False, repr=False)
    _illegal_exact: Mapping[Scalar, tuple[str, ...]] = field(init=False, repr=False)
    _illegal_dynamic: tuple[NamedBin, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.name:
            raise CoverageSchemaError("cover point name must not be empty")
        if not isinstance(self.description, str):
            raise CoverageSchemaError("cover point description must be a string")
        if self.weight < 0:
            raise CoverageSchemaError("cover point weight must not be negative")
        _validate_percentage(self.goal, "cover point goal")
        policy = OverlapPolicy(self.overlap)
        object.__setattr__(self, "overlap", policy)
        named = tuple(NamedBin(name, spec) for name, spec in self.bins.items())
        if not named:
            raise CoverageSchemaError(f"cover point {self.name!r} has no bins")
        names = [item.name for item in named]
        if any(not name for name in names) or len(set(names)) != len(names):
            raise CoverageSchemaError(
                f"cover point {self.name!r} has empty or duplicate bin names"
            )
        if sum(item.spec.kind is BinKind.DEFAULT for item in named) > 1:
            raise CoverageSchemaError(
                f"cover point {self.name!r} has multiple default bins"
            )
        if not any(item.spec.kind is BinKind.NORMAL for item in named):
            raise CoverageSchemaError(
                f"cover point {self.name!r} requires a normal bin"
            )
        object.__setattr__(self, "bins", MappingProxyType(dict(self.bins)))
        object.__setattr__(self, "_named_bins", named)
        source = self.name if self.source is None else self.source
        object.__setattr__(self, "_source_parts", tuple(source.split(".")))
        object.__setattr__(
            self,
            "_normal_bins",
            tuple(item for item in named if item.spec.kind is BinKind.NORMAL),
        )
        object.__setattr__(
            self,
            "_ignore_bins",
            tuple(item for item in named if item.spec.kind is BinKind.IGNORE),
        )
        object.__setattr__(
            self,
            "_illegal_bins",
            tuple(item for item in named if item.spec.kind is BinKind.ILLEGAL),
        )
        object.__setattr__(
            self,
            "_default_bins",
            tuple(item for item in named if item.spec.kind is BinKind.DEFAULT),
        )
        for prefix, selected in (
            ("normal", self._normal_bins),
            ("ignore", self._ignore_bins),
            ("illegal", self._illegal_bins),
        ):
            exact, dynamic = _compile_bin_matchers(selected)
            object.__setattr__(self, f"_{prefix}_exact", exact)
            object.__setattr__(self, f"_{prefix}_dynamic", dynamic)
        overlaps = _normal_overlaps(named)
        if overlaps:
            message = (
                f"cover point {self.name!r} has overlapping normal bins: "
                + ", ".join(f"{left}/{right}" for left, right in overlaps)
            )
            if policy is OverlapPolicy.ERROR:
                raise CoverageSchemaError(message)
            if policy is OverlapPolicy.WARN:
                warnings.warn(message, UserWarning, stacklevel=2)

    @property
    def normal_bins(self) -> tuple[NamedBin, ...]:
        return self._normal_bins

    def to_dict(self) -> dict[str, Any]:
        result = {
            "name": self.name,
            "source": self.name if self.source is None else self.source,
            "iff": None if self.iff is None else self.iff.to_dict(),
            "weight": self.weight,
            "goal": self.goal,
            "overlap": self.overlap.value,
            "bins": [item.to_dict() for item in sorted(self._named_bins, key=lambda x: x.name)],
        }
        if self.description:
            result["description"] = self.description
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverPointDef":
        bins = {
            item["name"]: BinSpec.from_dict(item)
            for item in data["bins"]
        }
        return cls(
            data["name"],
            bins,
            source=data["source"],
            iff=Iff.from_dict(data.get("iff")),
            weight=data["weight"],
            goal=data["goal"],
            overlap=data.get("overlap", "allow"),
            description=data.get("description", ""),
        )


@dataclass(frozen=True, slots=True)
class CrossDef:
    name: str
    points: tuple[str, ...]
    include: tuple[tuple[str, ...], ...] | None = None
    ignore: tuple[tuple[str, ...], ...] = ()
    illegal: tuple[tuple[str, ...], ...] = ()
    iff: Iff | None = None
    at_least: int = 1
    weight: int = 1
    goal: float = 100.0
    max_auto_bins: int = 4096
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise CoverageSchemaError("cross name must not be empty")
        if not isinstance(self.description, str):
            raise CoverageSchemaError("cross description must be a string")
        if len(self.points) < 2 or len(set(self.points)) != len(self.points):
            raise CoverageSchemaError("cross requires at least two distinct points")
        if self.at_least <= 0:
            raise CoverageSchemaError("cross at_least must be positive")
        if self.weight < 0:
            raise CoverageSchemaError("cross weight must not be negative")
        if self.max_auto_bins <= 0:
            raise CoverageSchemaError("max_auto_bins must be positive")
        _validate_percentage(self.goal, "cross goal")

    def to_dict(self) -> dict[str, Any]:
        result = {
            "name": self.name,
            "points": list(self.points),
            "include": None if self.include is None else [list(x) for x in self.include],
            "ignore": [list(x) for x in self.ignore],
            "illegal": [list(x) for x in self.illegal],
            "iff": None if self.iff is None else self.iff.to_dict(),
            "at_least": self.at_least,
            "weight": self.weight,
            "goal": self.goal,
            "max_auto_bins": self.max_auto_bins,
        }
        if self.description:
            result["description"] = self.description
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CrossDef":
        include = data.get("include")
        return cls(
            name=data["name"],
            points=tuple(data["points"]),
            include=None if include is None else tuple(tuple(x) for x in include),
            ignore=tuple(tuple(x) for x in data.get("ignore", ())),
            illegal=tuple(tuple(x) for x in data.get("illegal", ())),
            iff=Iff.from_dict(data.get("iff")),
            at_least=data["at_least"],
            weight=data["weight"],
            goal=data["goal"],
            max_auto_bins=data["max_auto_bins"],
            description=data.get("description", ""),
        )


@dataclass(frozen=True, slots=True)
class _ResolvedCross:
    definition: CrossDef
    eligible: tuple[tuple[str, ...], ...]
    eligible_set: frozenset[tuple[str, ...]]
    ignored: frozenset[tuple[str, ...]]
    illegal: frozenset[tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class CoverGroupDef:
    name: str
    points: tuple[CoverPointDef, ...]
    crosses: tuple[CrossDef, ...] = ()
    iff: Iff | None = None
    goal: float = 100.0
    description: str = ""
    _resolved_crosses: tuple[_ResolvedCross, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.name:
            raise CoverageSchemaError("cover group name must not be empty")
        if not isinstance(self.description, str):
            raise CoverageSchemaError("cover group description must be a string")
        _validate_percentage(self.goal, "cover group goal")
        if not self.points:
            raise CoverageSchemaError("cover group requires at least one point")
        point_map = _unique_by_name(self.points, "cover point")
        cross_map = _unique_by_name(self.crosses, "cross")
        if set(point_map) & set(cross_map):
            raise CoverageSchemaError("point and cross names must be distinct")
        if not any(item.weight > 0 for item in (*self.points, *self.crosses)):
            raise CoverageSchemaError("cover group requires a positive-weight item")
        resolved = tuple(_resolve_cross(item, point_map) for item in self.crosses)
        object.__setattr__(self, "_resolved_crosses", resolved)

    @property
    def digest(self) -> str:
        payload = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result = {
            "version": SCHEMA_VERSION,
            "name": self.name,
            "iff": None if self.iff is None else self.iff.to_dict(),
            "goal": self.goal,
            "points": [item.to_dict() for item in sorted(self.points, key=lambda x: x.name)],
            "crosses": [item.to_dict() for item in sorted(self.crosses, key=lambda x: x.name)],
        }
        if self.description:
            result["description"] = self.description
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverGroupDef":
        version = data.get("version")
        if version != SCHEMA_VERSION:
            raise CoverageSchemaError(
                f"unsupported coverage schema version {version!r}"
            )
        return cls(
            name=data["name"],
            points=tuple(CoverPointDef.from_dict(item) for item in data["points"]),
            crosses=tuple(CrossDef.from_dict(item) for item in data.get("crosses", ())),
            iff=Iff.from_dict(data.get("iff")),
            goal=data["goal"],
            description=data.get("description", ""),
        )

    def instantiate(
        self,
        instance: str,
        *,
        illegal_policy: IllegalPolicy | str = IllegalPolicy.RAISE,
    ) -> "CoverGroup":
        return CoverGroup(self, instance, illegal_policy=illegal_policy)


def _validate_percentage(value: float, label: str) -> None:
    if not 0.0 <= value <= 100.0:
        raise CoverageSchemaError(f"{label} must be between 0 and 100")


def _unique_by_name(items: Iterable[Any], label: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        if item.name in result:
            raise CoverageSchemaError(f"duplicate {label} name {item.name!r}")
        result[item.name] = item
    return result


def _resolve_cross(
    cross: CrossDef, points: Mapping[str, CoverPointDef]
) -> _ResolvedCross:
    try:
        dimensions = tuple(
            tuple(bin_.name for bin_ in points[name].normal_bins)
            for name in cross.points
        )
    except KeyError as error:
        raise CoverageSchemaError(
            f"cross {cross.name!r} references unknown point {error.args[0]!r}"
        ) from error
    allowed = tuple(product(*dimensions))
    allowed_set = set(allowed)
    if cross.include is None:
        if len(allowed) > cross.max_auto_bins:
            raise CoverageSchemaError(
                f"cross {cross.name!r} would create {len(allowed)} bins, above "
                f"max_auto_bins={cross.max_auto_bins}; use explicit include"
            )
        selected = allowed
    else:
        selected = cross.include
    ignored = frozenset(cross.ignore)
    illegal = frozenset(cross.illegal)
    for label, tuples in (
        ("include", selected),
        ("ignore", ignored),
        ("illegal", illegal),
    ):
        for item in tuples:
            if len(item) != len(cross.points) or item not in allowed_set:
                raise CoverageSchemaError(
                    f"cross {cross.name!r} has invalid {label} tuple {item!r}"
                )
    eligible = tuple(
        item for item in selected if item not in ignored and item not in illegal
    )
    if len(set(eligible)) != len(eligible):
        raise CoverageSchemaError(f"cross {cross.name!r} has duplicate include bins")
    if not eligible:
        raise CoverageSchemaError(f"cross {cross.name!r} has no eligible bins")
    return _ResolvedCross(cross, eligible, frozenset(eligible), ignored, illegal)


def _matcher_overlaps(left: Matcher, right: Matcher) -> bool:
    if isinstance(left, DefaultMatcher) or isinstance(right, DefaultMatcher):
        return False
    if isinstance(left, ValueMatcher):
        return any(right.matches(value) for value in left.values)
    if isinstance(right, ValueMatcher):
        return any(left.matches(value) for value in right.values)
    if isinstance(left, RangeMatcher) and isinstance(right, RangeMatcher):
        return any(
            max(a_low, b_low) <= min(a_high, b_high)
            for a_low, a_high in left.ranges
            for b_low, b_high in right.ranges
        )
    if isinstance(left, WildcardMatcher) and isinstance(right, WildcardMatcher):
        return ((left.value ^ right.value) & left.mask & right.mask) == 0
    wildcard = left if isinstance(left, WildcardMatcher) else right
    ranges = right if isinstance(left, WildcardMatcher) else left
    assert isinstance(wildcard, WildcardMatcher)
    assert isinstance(ranges, RangeMatcher)
    # Exact enumeration is bounded to keep schema finalization predictable.
    for low, high in ranges.ranges:
        if high - low <= 4096 and any(wildcard.matches(v) for v in range(low, high + 1)):
            return True
    return False


def _normal_overlaps(named: Sequence[NamedBin]) -> tuple[tuple[str, str], ...]:
    normal = [item for item in named if item.spec.kind is BinKind.NORMAL]
    result: list[tuple[str, str]] = []
    for index, left in enumerate(normal):
        for right in normal[index + 1 :]:
            if _matcher_overlaps(left.spec.matcher, right.spec.matcher):
                result.append((left.name, right.name))
    return tuple(result)


def _compile_bin_matchers(
    bins: Sequence[NamedBin],
) -> tuple[Mapping[Scalar, tuple[str, ...]], tuple[NamedBin, ...]]:
    exact: dict[Scalar, list[str]] = {}
    dynamic: list[NamedBin] = []
    for item in bins:
        matcher = item.spec.matcher
        if isinstance(matcher, ValueMatcher):
            for value in matcher.values:
                exact.setdefault(value, []).append(item.name)
        else:
            dynamic.append(item)
    return (
        MappingProxyType({value: tuple(names) for value, names in exact.items()}),
        tuple(dynamic),
    )


def _match_compiled(
    value: Any,
    exact: Mapping[Scalar, tuple[str, ...]],
    dynamic: Sequence[NamedBin],
    schema_order: Sequence[NamedBin],
) -> tuple[str, ...]:
    if isinstance(value, Enum):
        value = value.value
    try:
        matched = exact.get(value, ())
    except TypeError:
        matched = ()
    if not dynamic:
        return matched
    dynamic_matches = tuple(
        item.name for item in dynamic if item.spec.matcher.matches(value)
    )
    selected = frozenset((*matched, *dynamic_matches))
    return tuple(item.name for item in schema_order if item.name in selected)


@dataclass(slots=True)
class _ItemStats:
    samples: int = 0
    gated: int = 0
    ignored: int = 0
    unmatched: int = 0
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "gated": self.gated,
            "ignored": self.ignored,
            "unmatched": self.unmatched,
            "counts": dict(sorted(self.counts.items())),
        }


@dataclass(frozen=True, slots=True)
class CoverageSample:
    group: str
    point_bins: Mapping[str, tuple[str, ...]]
    cross_bins: Mapping[str, tuple[tuple[str, ...], ...]]
    gated: bool = False
    illegal_hits: tuple[IllegalHit, ...] = ()


@dataclass(frozen=True, slots=True)
class _PointPlan:
    point: CoverPointDef
    value: Any
    increments: tuple[str, ...] = ()
    normal: tuple[str, ...] = ()
    gated: bool = False
    ignored: bool = False
    unmatched: bool = False
    illegal: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _CrossPlan:
    cross: _ResolvedCross
    increments: tuple[tuple[str, ...], ...] = ()
    normal: tuple[tuple[str, ...], ...] = ()
    gated: bool = False
    ignored: int = 0
    unmatched: int = 0
    illegal: tuple[tuple[str, ...], ...] = ()


class CoverGroup:
    """Mutable, thread-safe counters for one immutable covergroup schema."""

    def __init__(
        self,
        definition: CoverGroupDef,
        instance: str,
        *,
        illegal_policy: IllegalPolicy | str = IllegalPolicy.RAISE,
    ) -> None:
        if not instance:
            raise ValueError("coverage instance name must not be empty")
        self.definition = definition
        self.instance = instance
        self.illegal_policy = IllegalPolicy(illegal_policy)
        self.samples = 0
        self.gated = 0
        self._points = {
            point.name: _ItemStats(counts={item.name: 0 for item in point._named_bins})
            for point in definition.points
        }
        self._crosses = {
            cross.definition.name: _ItemStats(
                counts={_tuple_key(item): 0 for item in cross.eligible}
                | {_tuple_key(item): 0 for item in cross.ignored}
                | {_tuple_key(item): 0 for item in cross.illegal}
            )
            for cross in definition._resolved_crosses
        }
        self._illegal_hits: list[IllegalHit] = []
        self._lock = RLock()

    def sample(
        self,
        sample: Any,
        *,
        metadata: Mapping[str, Any] | None = None,
        details: bool = True,
    ) -> CoverageSample | None:
        """Atomically sample one transaction.

        Set ``details=False`` on throughput-sensitive collectors that do not
        consume the per-sample hit description. Counters, gating, illegal-bin
        checks, and atomic commit semantics are unchanged.
        """

        with self._lock:
            if self.definition.iff is not None and not self.definition.iff.enabled(sample):
                self.gated += 1
                if details:
                    return CoverageSample(self.instance, {}, {}, gated=True)
                return None

            point_plans = tuple(self._plan_point(point, sample) for point in self.definition.points)
            plan_by_name = {plan.point.name: plan for plan in point_plans}
            cross_plans = tuple(
                self._plan_cross(cross, plan_by_name, sample)
                for cross in self.definition._resolved_crosses
            )

            illegal_hits: list[IllegalHit] = []
            has_illegal = any(plan.illegal for plan in point_plans) or any(
                plan.illegal for plan in cross_plans
            )
            meta = dict(metadata) if has_illegal and metadata is not None else {}
            for plan in point_plans:
                illegal_hits.extend(
                    IllegalHit(self.instance, plan.point.name, name, plan.value, meta)
                    for name in plan.illegal
                )
            for plan in cross_plans:
                illegal_hits.extend(
                    IllegalHit(
                        self.instance,
                        plan.cross.definition.name,
                        _tuple_key(item),
                        item,
                        meta,
                    )
                    for item in plan.illegal
                )

            # Commit only after all extraction and matching completed.
            self.samples += 1
            for plan in point_plans:
                stats = self._points[plan.point.name]
                if plan.gated:
                    stats.gated += 1
                    continue
                stats.samples += 1
                stats.ignored += int(plan.ignored)
                stats.unmatched += int(plan.unmatched)
                for name in plan.increments:
                    stats.counts[name] += 1
            for plan in cross_plans:
                stats = self._crosses[plan.cross.definition.name]
                if plan.gated:
                    stats.gated += 1
                    continue
                stats.samples += 1
                stats.ignored += plan.ignored
                stats.unmatched += plan.unmatched
                for item in plan.increments:
                    stats.counts[_tuple_key(item)] += 1
            self._illegal_hits.extend(illegal_hits)

            if illegal_hits and self.illegal_policy is IllegalPolicy.RAISE:
                raise IllegalBinError(illegal_hits)
            if not details:
                return None
            return CoverageSample(
                self.instance,
                MappingProxyType({plan.point.name: plan.normal for plan in point_plans}),
                MappingProxyType({
                    plan.cross.definition.name: plan.normal for plan in cross_plans
                }),
                illegal_hits=tuple(illegal_hits),
            )

    def _plan_point(self, point: CoverPointDef, sample: Any) -> _PointPlan:
        if point.iff is not None and not point.iff.enabled(sample):
            return _PointPlan(point, None, gated=True)
        value = _extract(sample, point._source_parts)
        illegal = _match_compiled(
            value,
            point._illegal_exact,
            point._illegal_dynamic,
            point._illegal_bins,
        )
        if illegal:
            return _PointPlan(point, value, increments=illegal, illegal=illegal)
        ignored = _match_compiled(
            value,
            point._ignore_exact,
            point._ignore_dynamic,
            point._ignore_bins,
        )
        if ignored:
            return _PointPlan(point, value, increments=ignored, ignored=True)
        normal = _match_compiled(
            value,
            point._normal_exact,
            point._normal_dynamic,
            point._normal_bins,
        )
        if normal:
            return _PointPlan(point, value, increments=normal, normal=normal)
        defaults = tuple(item.name for item in point._default_bins)
        return _PointPlan(
            point,
            value,
            increments=defaults,
            unmatched=not bool(defaults),
        )

    def _plan_cross(
        self,
        cross: _ResolvedCross,
        points: Mapping[str, _PointPlan],
        sample: Any,
    ) -> _CrossPlan:
        definition = cross.definition
        if definition.iff is not None and not definition.iff.enabled(sample):
            return _CrossPlan(cross, gated=True)
        dimensions = tuple(points[name].normal for name in definition.points)
        if any(not dimension for dimension in dimensions):
            return _CrossPlan(cross, unmatched=1)
        combinations = tuple(product(*dimensions))
        illegal = tuple(item for item in combinations if item in cross.illegal)
        ignored = tuple(item for item in combinations if item in cross.ignored)
        normal = tuple(
            item
            for item in combinations
            if item not in cross.illegal
            and item not in cross.ignored
            and item in cross.eligible_set
        )
        increments = (*illegal, *ignored, *normal)
        unmatched = len(combinations) - len(increments)
        return _CrossPlan(
            cross,
            increments=tuple(increments),
            normal=normal,
            ignored=len(ignored),
            unmatched=unmatched,
            illegal=illegal,
        )

    @property
    def illegal_hits(self) -> tuple[IllegalHit, ...]:
        with self._lock:
            return tuple(self._illegal_hits)

    def point_coverage(self, name: str) -> float:
        point = next((item for item in self.definition.points if item.name == name), None)
        if point is None:
            raise KeyError(name)
        with self._lock:
            stats = self._points[name]
            covered = sum(
                stats.counts[item.name] >= item.spec.at_least
                for item in point.normal_bins
            )
            return covered * 100.0 / len(point.normal_bins)

    def cross_coverage(self, name: str) -> float:
        cross = next(
            (item for item in self.definition._resolved_crosses if item.definition.name == name),
            None,
        )
        if cross is None:
            raise KeyError(name)
        with self._lock:
            stats = self._crosses[name]
            covered = sum(
                stats.counts[_tuple_key(item)] >= cross.definition.at_least
                for item in cross.eligible
            )
            return covered * 100.0 / len(cross.eligible)

    @property
    def coverage(self) -> float:
        with self._lock:
            weighted = 0.0
            total_weight = 0
            for point in self.definition.points:
                if point.weight:
                    weighted += self.point_coverage(point.name) * point.weight
                    total_weight += point.weight
            for cross in self.definition._resolved_crosses:
                if cross.definition.weight:
                    weighted += (
                        self.cross_coverage(cross.definition.name)
                        * cross.definition.weight
                    )
                    total_weight += cross.definition.weight
            return weighted / total_weight

    @property
    def covered(self) -> bool:
        return self.coverage + 1e-12 >= self.definition.goal

    def uncovered(self) -> tuple[str, ...]:
        result: list[str] = []
        with self._lock:
            for point in self.definition.points:
                stats = self._points[point.name]
                result.extend(
                    f"{point.name}.{item.name}"
                    for item in point.normal_bins
                    if stats.counts[item.name] < item.spec.at_least
                )
            for cross in self.definition._resolved_crosses:
                stats = self._crosses[cross.definition.name]
                result.extend(
                    f"{cross.definition.name}.{_tuple_key(item)}"
                    for item in cross.eligible
                    if stats.counts[_tuple_key(item)] < cross.definition.at_least
                )
        return tuple(result)

    def assert_coverage(self, minimum: float | None = None) -> None:
        target = self.definition.goal if minimum is None else minimum
        _validate_percentage(target, "coverage minimum")
        actual = self.coverage
        if actual + 1e-12 < target:
            raise AssertionError(
                f"coverage instance {self.instance!r} is {actual:.2f}%, below "
                f"{target:.2f}%; uncovered bins: {', '.join(self.uncovered())}"
            )
        if self._illegal_hits:
            raise IllegalBinError(self._illegal_hits)

    def reset(self) -> None:
        with self._lock:
            self.samples = 0
            self.gated = 0
            for stats in (*self._points.values(), *self._crosses.values()):
                stats.samples = stats.gated = stats.ignored = stats.unmatched = 0
                for name in stats.counts:
                    stats.counts[name] = 0
            self._illegal_hits.clear()

    def report(self) -> dict[str, Any]:
        with self._lock:
            points = []
            for point in self.definition.points:
                stats = self._points[point.name]
                item = stats.to_dict()
                item.update({
                    "name": point.name,
                    "coverage": self.point_coverage(point.name),
                    "goal": point.goal,
                })
                points.append(item)
            crosses = []
            for cross in self.definition._resolved_crosses:
                stats = self._crosses[cross.definition.name]
                item = stats.to_dict()
                item.update({
                    "name": cross.definition.name,
                    "coverage": self.cross_coverage(cross.definition.name),
                    "goal": cross.definition.goal,
                })
                crosses.append(item)
            return {
                "schema": self.definition.to_dict(),
                "schema_digest": self.definition.digest,
                "instance": self.instance,
                "illegal_policy": self.illegal_policy.value,
                "samples": self.samples,
                "gated": self.gated,
                "coverage": self.coverage,
                "goal": self.definition.goal,
                "covered": self.covered,
                "points": points,
                "crosses": crosses,
                "illegal_hits": [item.to_dict() for item in self._illegal_hits],
            }

    @classmethod
    def from_report(cls, report: Mapping[str, Any]) -> "CoverGroup":
        definition = CoverGroupDef.from_dict(report["schema"])
        if definition.digest != report["schema_digest"]:
            raise CoverageMergeError("coverage report schema digest is invalid")
        group = cls(
            definition,
            report["instance"],
            illegal_policy=report.get("illegal_policy", "raise"),
        )
        group.samples = report["samples"]
        group.gated = report["gated"]
        for item in report["points"]:
            group._restore_stats(group._points[item["name"]], item)
        for item in report["crosses"]:
            group._restore_stats(group._crosses[item["name"]], item)
        group._illegal_hits = [
            IllegalHit(
                item["group"],
                item["item"],
                item["bin"],
                item["value"],
                item.get("metadata", {}),
            )
            for item in report.get("illegal_hits", ())
        ]
        return group

    @staticmethod
    def _restore_stats(stats: _ItemStats, data: Mapping[str, Any]) -> None:
        if set(stats.counts) != set(data["counts"]):
            raise CoverageMergeError("coverage report counters do not match schema")
        stats.samples = data["samples"]
        stats.gated = data["gated"]
        stats.ignored = data["ignored"]
        stats.unmatched = data["unmatched"]
        stats.counts.update({name: int(value) for name, value in data["counts"].items()})

    def merge(self, other: "CoverGroup", *, require_instance: bool = True) -> None:
        snapshot = other.report()
        if self.definition.digest != snapshot["schema_digest"]:
            raise CoverageMergeError(
                f"schema mismatch merging {self.instance!r} and {snapshot['instance']!r}"
            )
        if require_instance and self.instance != snapshot["instance"]:
            raise CoverageMergeError(
                f"instance mismatch {self.instance!r} != {snapshot['instance']!r}"
            )
        with self._lock:
            self.samples += snapshot["samples"]
            self.gated += snapshot["gated"]
            for item in snapshot["points"]:
                _add_stats(self._points[item["name"]], item)
            for item in snapshot["crosses"]:
                _add_stats(self._crosses[item["name"]], item)
            self._illegal_hits.extend(
                IllegalHit(
                    item["group"], item["item"], item["bin"], item["value"],
                    item.get("metadata", {}),
                )
                for item in snapshot["illegal_hits"]
            )


def _add_stats(stats: _ItemStats, data: Mapping[str, Any]) -> None:
    if set(stats.counts) != set(data["counts"]):
        raise CoverageMergeError("coverage counters do not match schema")
    stats.samples += data["samples"]
    stats.gated += data["gated"]
    stats.ignored += data["ignored"]
    stats.unmatched += data["unmatched"]
    for name, count in data["counts"].items():
        stats.counts[name] += count


def _tuple_key(item: tuple[str, ...]) -> str:
    return " × ".join(item)


class CoverageDatabase:
    def __init__(self, groups: Iterable[CoverGroup] = ()) -> None:
        self._groups: dict[str, CoverGroup] = {}
        self._lock = RLock()
        for group in groups:
            self.add(group)

    def add(self, group: CoverGroup) -> CoverGroup:
        with self._lock:
            if group.instance in self._groups:
                raise ValueError(f"duplicate coverage instance {group.instance!r}")
            self._groups[group.instance] = group
        return group

    def __getitem__(self, instance: str) -> CoverGroup:
        return self._groups[instance]

    @property
    def groups(self) -> Mapping[str, CoverGroup]:
        with self._lock:
            return MappingProxyType(dict(self._groups))

    @property
    def coverage(self) -> float:
        with self._lock:
            if not self._groups:
                return 0.0
            return sum(group.coverage for group in self._groups.values()) / len(self._groups)

    def merge(self, other: "CoverageDatabase") -> None:
        incoming = other.report()["groups"]
        with self._lock:
            for item in incoming:
                instance = item["instance"]
                group = CoverGroup.from_report(item)
                if instance in self._groups:
                    self._groups[instance].merge(group)
                else:
                    self._groups[instance] = group

    def type_reports(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            grouped: dict[str, CoverGroup] = {}
            for group in self._groups.values():
                digest = group.definition.digest
                if digest not in grouped:
                    grouped[digest] = CoverGroup.from_report(group.report())
                    grouped[digest].instance = f"type:{group.definition.name}"
                else:
                    grouped[digest].merge(group, require_instance=False)
            return tuple(group.report() for group in grouped.values())

    def report(self) -> dict[str, Any]:
        with self._lock:
            return {
                "format": "xreactor-functional-coverage",
                "version": 1,
                "coverage": self.coverage,
                "groups": [group.report() for group in self._groups.values()],
            }

    def write_json(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.report(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return destination

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverageDatabase":
        if data.get("format") != "xreactor-functional-coverage" or data.get("version") != 1:
            raise CoverageMergeError("unsupported functional coverage database format")
        return cls(CoverGroup.from_report(item) for item in data["groups"])

    @classmethod
    def read_json(cls, path: str | Path) -> "CoverageDatabase":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
