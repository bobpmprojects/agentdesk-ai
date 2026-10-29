"""Deterministic synthetic Northwind Goods seed data."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from agentdesk.config import Settings
from agentdesk.db.connection import initialize_database


STATUSES = ("processing", "shipped", "delivered", "delivered-damaged")
ITEMS = ("Blender", "Kettle", "Toaster", "Desk Lamp")


def stable_id(kind: str, number: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"agentdesk:{kind}:{number}"))


def seed_database(path: Path) -> dict[str, object]:
    connection = initialize_database(path, recreate=True)
    base = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)

    with connection:
        for customer_number in range(1, 51):
            customer_id = stable_id("customer", customer_number)
            address_id = stable_id("address", customer_number)
            connection.execute(
                """
                INSERT INTO customers (id, name, email)
                VALUES (?, ?, ?)
                """,
                (
                    customer_id,
                    f"Customer {customer_number:03d}",
                    f"customer{customer_number:03d}@northwind.test",
                ),
            )
            connection.execute(
                """
                INSERT INTO addresses (
                    id, customer_id, line1, city, region, postal_code, country_code
                ) VALUES (?, ?, ?, ?, ?, ?, 'US')
                """,
                (
                    address_id,
                    customer_id,
                    f"{100 + customer_number} Market Street",
                    "Portland",
                    "OR",
                    f"97{customer_number:03d}",
                ),
            )

        for order_number in range(1, 151):
            customer_number = ((order_number - 1) // 3) + 1
            customer_id = stable_id("customer", customer_number)
            address_id = stable_id("address", customer_number)
            status = STATUSES[(order_number - 1) % len(STATUSES)]
            item_name = ITEMS[(order_number - 1) % len(ITEMS)]
            if status == "delivered-damaged":
                total_cents = 35_000 if order_number % 8 == 4 else 14_900
            elif order_number == 3:
                total_cents = 20_000
            else:
                total_cents = (79 + (order_number % 7) * 10) * 100
            ordered_at = base - timedelta(days=order_number % 12)
            delivered_at = (
                base + timedelta(days=2)
                if status in {"delivered", "delivered-damaged"}
                else None
            )
            order_id = f"ORD-{order_number:04d}"
            connection.execute(
                """
                INSERT INTO orders (
                    id, customer_id, status, item_id, item_name, total_cents,
                    shipping_address_id, ordered_at, delivered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    customer_id,
                    status,
                    f"ITEM-{order_number:04d}",
                    item_name,
                    total_cents,
                    address_id,
                    ordered_at.isoformat(),
                    delivered_at.isoformat() if delivered_at else None,
                ),
            )
            if status != "processing":
                connection.execute(
                    """
                    INSERT INTO shipments (
                        id, order_id, carrier, tracking_number, estimated_delivery,
                        shipped_at, delivered_at
                    ) VALUES (?, ?, 'Northwind Parcel', ?, ?, ?, ?)
                    """,
                    (
                        stable_id("shipment", order_number),
                        order_id,
                        f"NW{order_number:010d}",
                        (base + timedelta(days=4)).date().isoformat(),
                        (base + timedelta(days=1)).isoformat(),
                        delivered_at.isoformat() if delivered_at else None,
                    ),
                )

    counts = {
        "customers": connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
        "orders": connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        "order_states": {
            row["status"]: row["count"]
            for row in connection.execute(
                "SELECT status, COUNT(*) AS count FROM orders GROUP BY status ORDER BY status"
            )
        },
    }
    connection.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Recreate AgentDesk synthetic data")
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    path = args.database or Settings().database_path
    counts = seed_database(path)
    print(f"Database: {path}")
    print(f"Customers: {counts['customers']}")
    print(f"Orders: {counts['orders']}")
    print(f"States: {counts['order_states']}")


if __name__ == "__main__":
    main()
