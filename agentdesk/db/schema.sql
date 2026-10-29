PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    email_opt_in INTEGER NOT NULL DEFAULT 1,
    sms_opt_in INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS addresses (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    line1 TEXT NOT NULL,
    line2 TEXT,
    city TEXT NOT NULL,
    region TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    country_code TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    status TEXT NOT NULL CHECK (
        status IN ('processing', 'shipped', 'delivered', 'delivered-damaged', 'cancelled')
    ),
    item_id TEXT NOT NULL,
    item_name TEXT NOT NULL,
    total_cents INTEGER NOT NULL CHECK (total_cents >= 0),
    shipping_address_id TEXT NOT NULL REFERENCES addresses(id),
    address_change_count INTEGER NOT NULL DEFAULT 0,
    ordered_at TEXT NOT NULL,
    delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS shipments (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
    carrier TEXT NOT NULL,
    tracking_number TEXT NOT NULL,
    estimated_delivery TEXT,
    shipped_at TEXT,
    delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS refunds (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    item_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    kind TEXT NOT NULL DEFAULT 'cash' CHECK (kind IN ('cash', 'store_credit')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    order_id TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    operation TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('committed', 'denied', 'duplicate', 'failed')
    ),
    policy_decision_id TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_state (
    conversation_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_audit_conversation ON audit_log(conversation_id);
