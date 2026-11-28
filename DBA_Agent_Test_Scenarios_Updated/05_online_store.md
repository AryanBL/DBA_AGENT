# Test scenario 05 --- Established online store modernization

> **Use only Section 1 to start the agent.** Keep Sections 2--4 as the
> interviewer answer sheet. Do not give Section 5 to the agent.

## 1. Opening description

A mid-sized online retailer is replacing its legacy catalog and order
module without replacing its production database infrastructure. Its PHP
storefront, warehouse integration, and reporting services already use a
managed database cluster. The new schema must support checkout,
inventory reservations, payments, shipments, returns, and order
reporting while fitting the existing operational environment.

## 2. Canonical interview answers

The production platform is MySQL 8.0.36 with InnoDB. The facts below
resolve data, money, stock, transaction, and integration details.

### 2.1 Entities, attributes, and data rules

IDs are BIGINT generated keys. Timestamps are UTC. The store sells in
USD only. Money uses DECIMAL(12,2), never floating point.

-   **Product:** `product_id` PK; `sku` VARCHAR(64) required and unique;
    `title` VARCHAR(200) required; `description` TEXT nullable; `active`
    BOOLEAN required; `created_at_utc` required.
-   **Variant:** `variant_id` PK; `product_id` FK required;
    `variant_sku` VARCHAR(64) required and globally unique; `attributes`
    JSON required; `list_price` DECIMAL(12,2) required and \>= 0;
    `active` BOOLEAN required.
-   **Warehouse:** `warehouse_id` PK; `warehouse_code` VARCHAR(20)
    required and unique; `name` VARCHAR(120) required; `active` BOOLEAN
    required.
-   **Inventory:** composite PK `(warehouse_id, variant_id)`; both FKs
    required; `on_hand` INTEGER required and \>= 0; `reserved` INTEGER
    required and \>= 0; CHECK `reserved <= on_hand`. Available quantity
    is `on_hand - reserved`.
-   **Customer:** `customer_id` PK; `email_normalized` VARCHAR(254)
    required and unique; `display_name` VARCHAR(120) required; `phone`
    VARCHAR(30) nullable; `created_at_utc` required. Email is trimmed
    and lowercased before storage.
-   **SalesOrder:** `order_id` PK; `order_number` VARCHAR(32) required
    and unique; `customer_id` FK required; `status` in
    `pending_payment`, `paid`, `partially_shipped`, `shipped`,
    `partially_returned`, `returned`, `cancelled`; `created_at_utc`
    required; `currency` CHAR(3) required and always `USD`;
    `order_total` DECIMAL(12,2) required and \>= 0. `order_total` equals
    the sum of its OrderLine quantity × unit price; tax, shipping, and
    discount are out of scope.
-   **OrderLine:** `order_line_id` PK; `order_id` FK required;
    `variant_id` FK required; `warehouse_id` FK required; `line_number`
    SMALLINT required; `quantity` INTEGER required and \> 0;
    `unit_price` DECIMAL(12,2) required and \>= 0; unique
    `(order_id, line_number)` and unique `(order_line_id, order_id)` for
    composite references. Composite FK `(warehouse_id, variant_id)`
    references Inventory. One line is fulfilled from one warehouse; if
    the same variant is sourced from two warehouses, create two order
    lines. Unit price is a historical snapshot and does not change when
    catalog prices change.
-   **Payment:** `payment_id` PK; `order_id` FK required;
    `provider_transaction_reference` VARCHAR(100) required and unique;
    `idempotency_key` VARCHAR(100) required and unique; `amount`
    DECIMAL(12,2) required and \> 0; `status` in `authorized`,
    `captured`, `failed`, `void`; `created_at_utc` required.
-   **Shipment:** `shipment_id` PK; `order_id` FK required;
    `tracking_reference` VARCHAR(100) required and unique; every
    shipment is a carrier shipment and must have a tracking reference;
    `status` in `prepared`, `dispatched`, `delivered`, `lost`,
    `cancelled`; `dispatched_at_utc` nullable; `delivered_at_utc`
    nullable; unique `(shipment_id, order_id)` for composite references.
-   **ShipmentLine:** composite PK `(shipment_id, order_line_id)`; also
    stores required `order_id`; composite FK `(shipment_id, order_id)`
    to Shipment and `(order_line_id, order_id)` to OrderLine;
    `quantity_shipped` INTEGER required and \> 0. Total shipped quantity
    for an OrderLine cannot exceed its ordered quantity.
-   **ReturnRecord:** `return_id` PK; composite FK
    `(shipment_id, order_line_id)` to ShipmentLine required; `quantity`
    INTEGER required and \> 0; `reason` in `damaged`, `unwanted`,
    `wrong_item`, `other`; `status` in `requested`, `approved`,
    `received`, `rejected`; `restockable` BOOLEAN required;
    `created_at_utc` required. Cumulative accepted return quantity
    cannot exceed the quantity shipped on that ShipmentLine.

### 2.2 Relationships and cardinalities

-   Product has many Variants; each Variant belongs to one Product.
-   Warehouse and Variant have a many-to-many inventory relationship
    through Inventory.
-   Customer has many SalesOrders; each order has one Customer.
-   SalesOrder has one or more OrderLines and zero or more Payment
    attempts and Shipments.
-   A Shipment has one or more ShipmentLines; a ShipmentLine belongs to
    one OrderLine and one Shipment.
-   A ReturnRecord refers to one ShipmentLine; a ShipmentLine may have
    multiple partial ReturnRecords. The Shipment and OrderLine in a
    ShipmentLine must belong to the same SalesOrder.
-   Referenced catalog, order, payment, and shipment records are not
    hard-deleted. Deactivate catalog rows instead.
-   All foreign-key deletion behavior is RESTRICT for transactional
    history.

### 2.3 Data volume and retention

-   150,000 Products, 500,000 Variants, 12 Warehouses, 1 million
    Customers, and 3 million existing Orders.
-   About 10,000 new orders/day; 15% annual growth.
-   Current data size approximately 200 GB; retain order/payment/return
    history for seven years.
-   Product descriptions and operational records are in the database.
    Product images and shipment documents are stored in object storage;
    only references are stored.

### 2.4 Workload and reporting

-   Up to 1,000 concurrent web requests during promotions; connection
    pool about 100; dozens of concurrent writers.
-   Approximately 80% reads and 20% writes.
-   The managed cluster has two read replicas. Catalog and reporting
    reads use those replicas; checkout, payment confirmation, and
    inventory reservation always read and write against the primary.
-   Reports: daily orders, revenue, stock by warehouse, unshipped
    orders, returns, and payment reconciliation.
-   Target checkout transaction time is under 300 ms at normal load;
    validate by benchmark after deployment, not as an assumed result.

### 2.5 Transactions and consistency

-   Checkout creates the SalesOrder and OrderLines and reserves
    inventory atomically.
-   For every Inventory row, `reserved` must never exceed `on_hand`.
    Reservation uses a locking read or atomic conditional update so two
    checkouts cannot oversell the same stock.
-   On shipment, `on_hand` and `reserved` are both decremented by the
    shipped quantity in one transaction. Cancellation releases
    `reserved`.
-   Payment callbacks are idempotent using unique provider transaction
    reference and idempotency key. The sum of captured payments cannot
    exceed `SalesOrder.order_total`; enforce transactionally.
-   A failed payment does not mark the order paid.
-   `SalesOrder.order_total` is recalculated from order lines in the
    same transaction that changes the lines.
-   Total shipped quantity cannot exceed ordered quantity. Cumulative
    accepted returns cannot exceed the quantity shipped on their
    ShipmentLine; both checks are transactional.
-   When a received return is marked restockable, the corresponding
    Inventory.on_hand is incremented atomically; non-restockable returns
    do not increase stock.
-   Deadlocks are retried with bounded backoff. A failed checkout leaves
    no partial order or reservation.

### 2.6 Security and privacy

-   Separate service accounts: storefront read/write, warehouse
    integration read/write only to required tables, reporting read-only,
    and DBA administrator.
-   TLS for connections; encrypted backups; sensitive admin changes
    audited.
-   No payment-card number, CVV, bank password, or raw payment
    credentials are stored. The payment provider handles card data.
-   Customer email and phone are personal data; access is limited to
    authorized application roles.

### 2.7 Business rules

-   Product SKU, variant SKU, warehouse code, normalized customer email,
    order number, provider transaction reference, idempotency key, and
    tracking reference are unique.
-   Quantities are positive; inventory amounts are nonnegative; reserved
    never exceeds on-hand.
-   Order-line prices and payment amounts use exact DECIMAL values in
    USD.
-   Payment references are idempotent; captured payments cannot exceed
    order total; shipment quantities cannot exceed ordered quantities;
    returns cannot exceed shipped quantities.
-   Valid status and reason values are exactly those listed above.
    `partially_returned` means at least one accepted return exists but
    not all shipped quantity has been accepted; `returned` means all
    shipped quantity has been accepted. A ReturnRecord in `received`
    state with `restockable=true` increases inventory; all other return
    states leave inventory unchanged. A Shipment in `dispatched`,
    `delivered`, or `lost` state requires `dispatched_at_utc`;
    `delivered` also requires `delivered_at_utc`.
-   Tax, shipping-price calculation, discount campaigns, multi-currency,
    gift cards, payment refunds, and card storage are out of scope for
    this schema test. Return merchandise is tracked, but refund
    settlement is handled by the external payment provider and is not
    modeled here.
-   Advanced full-text search is handled by an external search service;
    database search uses ordinary indexed filters.

### 2.8 Deployment and operations

-   Required target: MySQL Community/Enterprise 8.0.36 or later in the
    8.0 line, InnoDB, strict SQL mode, GTID-based replication.
-   The existing managed cluster, backup/restore, monitoring, support
    contract, and warehouse integration all depend on MySQL 8.0. No
    engine migration is approved or funded.
-   PHP uses PDO MySQL. The application connects through the existing
    connection pool.
-   Managed primary plus read replicas. RPO is five minutes; RTO is 30
    minutes.
-   MariaDB is not assumed to be a drop-in replacement; the deployed
    platform is specifically MySQL 8.0.

## 3. Exact answers to likely follow-up questions

-   **Which exact engine?** MySQL 8.0.36 or a later compatible 8.0
    patch; InnoDB and strict SQL mode.
-   **Can reporting use replicas?** Yes. Checkout and inventory
    reservation must use the primary.
-   **What currency?** USD only; exact DECIMAL(12,2).
-   **Can reserved exceed on-hand?** Never.
-   **Are payment card details stored?** No.
-   **Is MariaDB acceptable?** No. The managed platform and integration
    are specifically MySQL 8.0.
-   **Are tax, shipping, discounts, or multi-currency included?** No,
    all are out of scope.
-   **Anything not listed?** Out of scope; do not infer requirements.

## 4. Interviewer procedure

1.  Start a new session using only Section 1.
2.  Answer dynamic questions using Sections 2--3.
3.  Distinguish MySQL 8 from MariaDB if the agent asks.
4.  Do not reveal Section 5 before DBMS selection and design review.

## 5. Expected outcome --- evaluator only

**Do not send this section to the agent.**

-   **Expected `selected`:** `MySQL/MariaDB` (the specific target is
    MySQL 8.0.36+)
-   **Expectation strength:** Binding.

### Why

The existing managed MySQL 8 cluster, InnoDB, GTID replication, PHP PDO
MySQL integration, warehouse integration, and no-migration policy are
binding deployment constraints. The agent must not describe MySQL and
MariaDB as identical.

### Design and SQL acceptance checks

-   Inventory composite key `(warehouse_id, variant_id)` and
    `reserved <= on_hand`.
-   Transactionally safe reservation, shipment decrement, cancellation
    release, and return-quantity ceiling.
-   Unique payment/provider/idempotency references and exact decimal
    money.
-   Seed negatives: duplicate SKU, duplicate provider reference,
    negative quantity/amount, reserved \> on_hand, orphan OrderLine,
    ShipmentLine linking different orders, invalid status, shipment
    quantity above ordered quantity, approved return quantity above
    shipped quantity, and captured payments above order total.
-   SQL must be MySQL 8 syntax; CHECK constraints must be enforced by
    the selected MySQL release. Do not use PostgreSQL-only syntax.
