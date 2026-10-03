PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS archive_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY,
    content_sha256 TEXT NOT NULL UNIQUE,
    source_system TEXT NOT NULL,
    report TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_scope_json TEXT NOT NULL CHECK (json_valid(source_scope_json)),
    member_count INTEGER NOT NULL,
    line_count INTEGER NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS legacy_members (
    id INTEGER PRIMARY KEY,
    source_system TEXT NOT NULL,
    source_member_id TEXT NOT NULL,
    source_member_id_raw TEXT NOT NULL,
    name_raw TEXT NOT NULL,
    phone_raw TEXT NOT NULL,
    last_captured_at TEXT NOT NULL,
    UNIQUE (source_system, source_member_id)
);
CREATE INDEX IF NOT EXISTS idx_legacy_member_phone ON legacy_members(phone_raw);
CREATE INDEX IF NOT EXISTS idx_legacy_member_name ON legacy_members(name_raw);

CREATE TABLE IF NOT EXISTS member_list_snapshots (
    import_batch_id INTEGER NOT NULL REFERENCES import_batches(id),
    member_id INTEGER NOT NULL REFERENCES legacy_members(id),
    source_file TEXT NOT NULL,
    list_amount_raw TEXT NOT NULL,
    raw_json TEXT NOT NULL CHECK(json_valid(raw_json)),
    PRIMARY KEY(import_batch_id,member_id)
);

CREATE TABLE IF NOT EXISTS source_snapshots (
    id INTEGER PRIMARY KEY,
    import_batch_id INTEGER NOT NULL REFERENCES import_batches(id),
    member_id INTEGER NOT NULL REFERENCES legacy_members(id),
    source_url TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL,
    raw_json TEXT NOT NULL CHECK (json_valid(raw_json)),
    UNIQUE (import_batch_id, member_id)
);

CREATE TABLE IF NOT EXISTS legacy_documents (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES legacy_members(id),
    store_name_raw TEXT NOT NULL,
    document_type_raw TEXT NOT NULL,
    document_number_raw TEXT NOT NULL,
    document_date TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    snapshot_id INTEGER NOT NULL REFERENCES source_snapshots(id),
    report_amount_minor INTEGER NOT NULL,
    last_captured_at TEXT NOT NULL,
    UNIQUE (member_id, store_name_raw, document_type_raw, document_number_raw, document_date)
);
CREATE INDEX IF NOT EXISTS idx_legacy_document_member_date
ON legacy_documents(member_id, document_date DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_legacy_document_date ON legacy_documents(document_date);

CREATE TABLE IF NOT EXISTS document_versions (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES legacy_documents(id),
    snapshot_id INTEGER NOT NULL REFERENCES source_snapshots(id),
    content_sha256 TEXT NOT NULL,
    rows_json TEXT NOT NULL CHECK (json_valid(rows_json)),
    UNIQUE(document_id, snapshot_id)
);

CREATE TABLE IF NOT EXISTS legacy_items (
    document_id INTEGER NOT NULL REFERENCES legacy_documents(id),
    item_ordinal INTEGER NOT NULL CHECK(item_ordinal > 0),
    report_sequence_raw TEXT NOT NULL,
    product_code_raw TEXT NOT NULL,
    product_name_raw TEXT NOT NULL,
    quantity_decimal TEXT NOT NULL,
    quantity_raw TEXT NOT NULL,
    unit_price_minor INTEGER,
    amount_minor INTEGER NOT NULL,
    amount_ex_tax_minor INTEGER NOT NULL,
    points_raw TEXT NOT NULL,
    salesperson_raw TEXT NOT NULL,
    customer_name_raw TEXT NOT NULL,
    remarks_raw TEXT NOT NULL,
    promotion_raw TEXT NOT NULL,
    source_row_json TEXT NOT NULL CHECK(json_valid(source_row_json)),
    net_sign INTEGER NOT NULL CHECK(net_sign IN (-1,1)),
    PRIMARY KEY (document_id, item_ordinal)
);
CREATE INDEX IF NOT EXISTS idx_legacy_item_product_code ON legacy_items(product_code_raw);

CREATE TABLE IF NOT EXISTS mp_pos_member_links (
    archive_member_id INTEGER NOT NULL REFERENCES legacy_members(id),
    mp_pos_tenant_id INTEGER NOT NULL,
    mp_pos_member_id INTEGER NOT NULL,
    match_method TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    PRIMARY KEY(archive_member_id, mp_pos_tenant_id)
);

CREATE TABLE IF NOT EXISTS crawl_jobs (
    source_member_id TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'running', 'complete', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    line_count INTEGER,
    error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(source_member_id, period_start, period_end)
);

CREATE VIEW IF NOT EXISTS member_consumptions AS
SELECT m.id AS archive_member_id, m.source_member_id, m.name_raw AS member_name,
       m.phone_raw AS member_phone, d.id AS document_id, d.document_date,
       d.store_name_raw, d.document_type_raw, d.document_number_raw,
       i.item_ordinal, i.product_code_raw, i.product_name_raw,
       i.quantity_decimal, i.unit_price_minor, i.amount_minor, i.amount_ex_tax_minor,
       i.net_sign, i.amount_minor*i.net_sign AS net_amount_minor,
       i.points_raw, i.salesperson_raw, i.customer_name_raw, i.remarks_raw,
       i.promotion_raw, d.snapshot_id
FROM legacy_members m
JOIN legacy_documents d ON d.member_id = m.id
JOIN legacy_items i ON i.document_id = d.id;


CREATE TABLE IF NOT EXISTS source_amount_exceptions (
    import_batch_id INTEGER NOT NULL REFERENCES import_batches(id),
    member_id INTEGER NOT NULL REFERENCES legacy_members(id),
    snapshot_id INTEGER NOT NULL UNIQUE REFERENCES source_snapshots(id),
    reason TEXT NOT NULL,
    list_amount_minor INTEGER NOT NULL,
    detail_net_amount_minor INTEGER NOT NULL,
    detail_raw_amount_minor INTEGER NOT NULL,
    difference_minor INTEGER NOT NULL,
    line_count INTEGER NOT NULL,
    document_count INTEGER NOT NULL,
    rows_json TEXT NOT NULL CHECK(json_valid(rows_json)),
    validation_error TEXT NOT NULL,
    PRIMARY KEY(import_batch_id,member_id)
);
