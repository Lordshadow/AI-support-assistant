INSERT INTO customers (customer_id, phone_hash, language_pref)
VALUES ('qa-customer', 'qa-phone-hash', 'en');

INSERT INTO products (product_id, name, brand, category)
VALUES ('QA-PRODUCT', 'QA Product', 'NovaRetail', 'qa');

INSERT INTO orders (
    order_id, customer_id, total_amount_inr, status, created_at
)
VALUES (
    'QA-ORDER', 'qa-customer', 2500, 'Delivered', CURRENT_TIMESTAMP
);

INSERT INTO refund_requests (
    refund_id, order_id, customer_id, amount_inr, reason, state,
    idempotency_key, created_at
)
VALUES (
    'QA-REFUND', 'QA-ORDER', 'qa-customer', 2500, 'QA migration fixture',
    'pending_approval', 'qa-refund-idempotency', CURRENT_TIMESTAMP
);

INSERT INTO knowledge_chunks (
    chunk_id, source_type, product_id, doc_id, doc_version, text, metadata
)
VALUES (
    'QA-CHUNK', 'product_doc', 'QA-PRODUCT', 'QA-DOC', 'v1',
    'Legacy migration fixture content', '{"fixture": true}'::jsonb
);
