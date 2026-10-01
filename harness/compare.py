"""Tolerance comparison and keyed table diffs.

Used for: golden vs reference verification (M2), golden vs faulted output (fault
verification and attribution), and flagging reconciliation query results.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import duckdb


def rel_diff(model_value, reference_value, abs_floor: float = 1e-6) -> float:
    """Relative difference |m - r| / |r|. Missing on one side counts as 100% off."""
    if model_value is None and reference_value is None:
        return 0.0
    if model_value is None or reference_value is None:
        return math.inf
    m, r = float(model_value), float(reference_value)
    if math.isnan(m) or math.isnan(r):
        return 0.0 if (math.isnan(m) and math.isnan(r)) else math.inf
    if abs(m - r) <= abs_floor:
        return 0.0
    if r == 0:
        return math.inf
    return abs(m - r) / abs(r)


def exceeds(model_value, reference_value, tolerance: float, abs_floor: float = 1e-6) -> bool:
    return rel_diff(model_value, reference_value, abs_floor) > tolerance


@dataclass
class TableDiff:
    rows_only_left: int = 0
    rows_only_right: int = 0
    duplicate_keys_left: int = 0
    duplicate_keys_right: int = 0
    columns_differing: dict[str, int] = field(default_factory=dict)
    max_rel_diff: dict[str, float] = field(default_factory=dict)
    schema_mismatch: list[str] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        return not (self.rows_only_left or self.rows_only_right or self.duplicate_keys_left
                    or self.duplicate_keys_right or self.columns_differing or self.schema_mismatch)

    @property
    def affected_columns(self) -> list[str]:
        return sorted(self.columns_differing)

    def as_dict(self) -> dict:
        return {
            "identical": self.identical,
            "rows_only_left": self.rows_only_left,
            "rows_only_right": self.rows_only_right,
            "duplicate_keys_left": self.duplicate_keys_left,
            "duplicate_keys_right": self.duplicate_keys_right,
            "columns_differing": self.columns_differing,
            "max_rel_diff": {k: (None if math.isinf(v) else v) for k, v in self.max_rel_diff.items()},
            "schema_mismatch": self.schema_mismatch,
        }


def _columns(con: duckdb.DuckDBPyConnection, relation: str) -> list[str]:
    return [r[0] for r in con.execute(f"select * from {relation} limit 0").description]


def diff_tables(
    con: duckdb.DuckDBPyConnection,
    left: str,
    right: str,
    keys: list[str],
    rel_tolerance: float = 1e-9,
    abs_floor: float = 1e-6,
) -> TableDiff:
    """Diff two relations joined on `keys`. Numeric columns use a relative tolerance."""
    d = TableDiff()
    lcols, rcols = _columns(con, left), _columns(con, right)
    if set(lcols) != set(rcols):
        d.schema_mismatch = sorted(set(lcols) ^ set(rcols))
    shared = [c for c in lcols if c in rcols and c not in keys]
    key_list = ", ".join(keys)
    for side, rel in (("left", left), ("right", right)):
        dupes = con.execute(
            f"select coalesce(sum(n - 1), 0) from (select count(*) n from {rel} group by {key_list} having count(*) > 1)"
        ).fetchone()[0]
        setattr(d, f"duplicate_keys_{side}", int(dupes))
    # Collapse duplicate keys by summing numerics so the value diff stays meaningful.
    types = dict(con.execute(f"select column_name, column_type from (describe {left})").fetchall())

    def collapsed(rel: str) -> str:
        sel = []
        for c in shared:
            t = types.get(c, "VARCHAR").upper()
            if any(x in t for x in ("INT", "DECIMAL", "DOUBLE", "FLOAT", "NUMERIC", "HUGEINT", "REAL")):
                sel.append(f"sum({c}) as {c}")
            else:
                sel.append(f"min({c}) as {c}")
        cols = ", ".join([*keys, *sel])
        return f"(select {cols} from {rel} group by {key_list})"

    on = " and ".join(f"l.{k} is not distinct from r.{k}" for k in keys)
    joined = f"{collapsed(left)} l full outer join {collapsed(right)} r on {on}"
    l_null = " and ".join(f"l.{k} is null" for k in keys)
    r_null = " and ".join(f"r.{k} is null" for k in keys)
    d.rows_only_left = con.execute(f"select count(*) from {joined} where {r_null}").fetchone()[0]
    d.rows_only_right = con.execute(f"select count(*) from {joined} where {l_null}").fetchone()[0]
    rows = con.execute(
        f"select {', '.join(f'l.{c}, r.{c}' for c in shared)} from {joined} "
        f"where not ({l_null}) and not ({r_null})"
    ).fetchall()
    for i, c in enumerate(shared):
        n_diff, worst = 0, 0.0
        for row in rows:
            lv, rv = row[2 * i], row[2 * i + 1]
            if isinstance(lv, (int, float)) or isinstance(rv, (int, float)) or _is_decimal(lv) or _is_decimal(rv):
                rd = rel_diff(lv, rv, abs_floor)
                if rd > rel_tolerance:
                    n_diff += 1
                    worst = max(worst, rd)
            elif lv != rv and not (lv is None and rv is None):
                n_diff += 1
                worst = math.inf
        if n_diff:
            d.columns_differing[c] = n_diff
            d.max_rel_diff[c] = worst
    return d


def _is_decimal(v) -> bool:
    return type(v).__name__ == "Decimal"
