"""Deterministically add evaluation-only records to the vendored jaffle-shop seeds.

jaffle-shop has no order status, refunds or internal/test accounts, so faults that
need a business filter (F-FILTER, F-SHARED-DEF) have nothing to act on. This
script adds:

* 8 QA test customers ("QA Test Account NN") and 120 orders they placed at the
  Brooklyn store during a POS load-test week (2025-03-10 .. 2025-03-16), with
  matching order items. The business definition excludes these.
* raw_refunds.csv: ~1.5% of real orders refunded 1-10 days after ordering.
  The business definition excludes refunded orders from every metric.

Original rows are untouched; new rows are appended. Rerunning is a no-op.
"""
from __future__ import annotations

import csv
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent.parent / "reference_project" / "seeds" / "jaffle-data"
RNG_SEED = 20261001
BROOKLYN = "40e6ddd6-b8f6-4e17-8bd6-5e53966809d2"
BROOKLYN_TAX = 0.04
N_TEST_CUSTOMERS = 8
N_TEST_ORDERS = 120
REFUND_RATE = 0.015
REFUND_REASONS = ["wrong item", "late delivery", "quality complaint", "duplicate charge"]
MARKER = "QA Test Account"


def _uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _read(name: str) -> list[dict]:
    with open(SEED_DIR / name, newline="") as f:
        return list(csv.DictReader(f))


def _line_terminator(name: str) -> str:
    # The vendored jaffle-shop CSVs use CRLF; mixing endings breaks CSV sniffing.
    with open(SEED_DIR / name, "rb") as f:
        return "\r\n" if b"\r\n" in f.readline() else "\n"


def _append(name: str, rows: list[dict], fields: list[str]) -> None:
    terminator = _line_terminator(name)
    with open(SEED_DIR / name, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=fields, lineterminator=terminator).writerows(rows)


def main() -> None:
    customers = _read("raw_customers.csv")
    if any(c["name"].startswith(MARKER) for c in customers):
        print("seeds already augmented; nothing to do")
        return
    rng = random.Random(RNG_SEED)
    products = _read("raw_products.csv")

    test_customers = [
        {"id": _uuid(rng), "name": f"{MARKER} {i:02d}"} for i in range(1, N_TEST_CUSTOMERS + 1)
    ]
    orders, items = [], []
    week_start = datetime(2025, 3, 10)
    for _ in range(N_TEST_ORDERS):
        order_id = _uuid(rng)
        ordered_at = week_start + timedelta(days=rng.randrange(7), hours=rng.randint(9, 17), minutes=rng.randrange(60))
        chosen = [rng.choice(products) for _ in range(rng.randint(1, 3))]
        subtotal = sum(int(p["price"]) for p in chosen)
        tax = round(subtotal * BROOKLYN_TAX)
        orders.append({
            "id": order_id,
            "customer": rng.choice(test_customers)["id"],
            "ordered_at": ordered_at.strftime("%Y-%m-%dT%H:%M:%S"),
            "store_id": BROOKLYN,
            "subtotal": subtotal,
            "tax_paid": tax,
            "order_total": subtotal + tax,
        })
        items += [{"id": _uuid(rng), "order_id": order_id, "sku": p["sku"]} for p in chosen]

    real_orders = _read("raw_orders.csv")
    refunds = []
    for o in real_orders:
        if rng.random() < REFUND_RATE:
            refunded_at = datetime.fromisoformat(o["ordered_at"]) + timedelta(days=rng.randint(1, 10))
            refunds.append({
                "order_id": o["id"],
                "refunded_at": refunded_at.strftime("%Y-%m-%dT%H:%M:%S"),
                "reason": rng.choice(REFUND_REASONS),
            })

    _append("raw_customers.csv", test_customers, ["id", "name"])
    _append("raw_orders.csv", orders, ["id", "customer", "ordered_at", "store_id", "subtotal", "tax_paid", "order_total"])
    _append("raw_items.csv", items, ["id", "order_id", "sku"])
    with open(SEED_DIR / "raw_refunds.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["order_id", "refunded_at", "reason"], lineterminator="\n")
        w.writeheader()
        w.writerows(refunds)
    print(f"added {len(test_customers)} test customers, {len(orders)} test orders, "
          f"{len(items)} test items, {len(refunds)} refunds")


if __name__ == "__main__":
    main()
