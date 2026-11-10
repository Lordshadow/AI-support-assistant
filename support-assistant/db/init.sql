-- PostgreSQL + pgvector Initialization Script for NovaRetail Customer Support Assistant
-- Complies with Specification Sections 4, 5.1, 5.2, and 8.

-- 1. Enable Required Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. Products Table
CREATE TABLE IF NOT EXISTS products (
    product_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    brand VARCHAR(128) NOT NULL,
    category VARCHAR(64) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    faqs JSONB NOT NULL DEFAULT '[]'::jsonb,
    aliases TEXT[] DEFAULT '{}',
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Fast Trigram Index for fuzzy product name & alias resolution (Section 8.2)
CREATE INDEX IF NOT EXISTS idx_products_name_trgm ON products USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);

-- 3. Product Specifications Table (Structured Specs)
CREATE TABLE IF NOT EXISTS product_specs (
    spec_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id VARCHAR(64) NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
    spec_key VARCHAR(128) NOT NULL,
    spec_value TEXT NOT NULL,
    unit VARCHAR(32),
    UNIQUE(product_id, spec_key)
);
CREATE INDEX IF NOT EXISTS idx_specs_product_id ON product_specs(product_id);

-- 4. Product Live Pricing & Stock Table (Section 5.1 - Live & un-stale)
CREATE TABLE IF NOT EXISTS product_prices (
    product_id VARCHAR(64) PRIMARY KEY REFERENCES products(product_id) ON DELETE CASCADE,
    price INT NOT NULL,
    discount_price INT,
    currency VARCHAR(8) DEFAULT 'INR',
    in_stock BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 5. Knowledge Chunks Table (RAG Vector Store)
-- Dimension: 1024 (Compatible with BGE-M3 and NVIDIA NIM multilingual embedding models)
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id VARCHAR(64) PRIMARY KEY,
    source_type VARCHAR(32) NOT NULL,      -- 'product_doc', 'faq', 'policy_clause'
    product_id VARCHAR(64) REFERENCES products(product_id) ON DELETE SET NULL,
    doc_id VARCHAR(64) NOT NULL,
    doc_version VARCHAR(32) NOT NULL,
    text TEXT NOT NULL,
    embedding vector(1024),                 -- Dense vector representation
    metadata JSONB DEFAULT '{}'::jsonb,     -- Tags: clause_id, section, keywords
    effective_date DATE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- HNSW Vector Index for sub-millisecond approximate nearest neighbor search
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw 
ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Filtered RAG Index: guarantees instant WHERE product_id = 'P1041' filtering (Section 8.2)
CREATE INDEX IF NOT EXISTS idx_chunks_product_id ON knowledge_chunks(product_id);
CREATE INDEX IF NOT EXISTS idx_chunks_source_type ON knowledge_chunks(source_type);

-- 6. Policy Documents Table
CREATE TABLE IF NOT EXISTS policy_documents (
    doc_id VARCHAR(64) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    version VARCHAR(32) NOT NULL,
    status VARCHAR(32) DEFAULT 'published', -- 'draft', 'published', 'archived'
    effective_date DATE NOT NULL,
    uploaded_by VARCHAR(128),
    published_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 7. Customers Table
CREATE TABLE IF NOT EXISTS customers (
    customer_id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'tenant_novaretail',
    phone_hash VARCHAR(64) NOT NULL UNIQUE, -- SHA-256 hash for DPDP compliance
    email VARCHAR(255) NOT NULL UNIQUE,
    full_name VARCHAR(255) NOT NULL,
    language_pref VARCHAR(16) DEFAULT 'en', -- 'en', 'ta', 'tanglish'
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_customers_tenant ON customers(tenant_id);

-- 8. Customer Orders Table
CREATE TABLE IF NOT EXISTS orders (
    order_id VARCHAR(64) PRIMARY KEY,
    customer_id VARCHAR(64) NOT NULL REFERENCES customers(customer_id),
    total_amount_inr NUMERIC(12, 2) NOT NULL,
    status VARCHAR(32) NOT NULL,            -- 'Processing', 'Shipped', 'Delivered', 'Cancelled'
    tracking_number VARCHAR(128),
    courier_name VARCHAR(64),
    shipping_address TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    delivered_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);

-- 9. Order Items Table
CREATE TABLE IF NOT EXISTS order_items (
    item_id VARCHAR(64) PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_id VARCHAR(64) REFERENCES products(product_id),
    product_name VARCHAR(255) NOT NULL,
    category VARCHAR(64) NOT NULL,
    price NUMERIC(12, 2) NOT NULL,
    quantity INT DEFAULT 1,
    is_digital BOOLEAN DEFAULT FALSE,
    is_refunded BOOLEAN DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);

-- 10. Refund Requests Table (Section 10)
CREATE TABLE IF NOT EXISTS refund_requests (
    refund_id VARCHAR(64) PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL REFERENCES orders(order_id),
    customer_id VARCHAR(64) NOT NULL REFERENCES customers(customer_id),
    amount_inr NUMERIC(12, 2) NOT NULL,
    reason TEXT NOT NULL,
    state VARCHAR(32) NOT NULL,             -- 'processed', 'pending_approval', 'approved', 'rejected'
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    decided_by VARCHAR(128),                -- Staff ID who approved/rejected
    decided_at TIMESTAMPTZ,
    note TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_refund_customer ON refund_requests(customer_id);
CREATE INDEX IF NOT EXISTS idx_refund_state ON refund_requests(state);

-- 11. Per-Turn Audit Traces Table (Section 14 & R5 Explainability)
CREATE TABLE IF NOT EXISTS traces (
    trace_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conv_id VARCHAR(64) NOT NULL,
    msg_id VARCHAR(64) NOT NULL,
    step VARCHAR(64) NOT NULL,              -- 'router', 'retrieval', 'tool_call', 'grounding'
    payload JSONB NOT NULL,
    ts TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_traces_conv ON traces(conv_id);

-- 12. Tenant Configuration Table
CREATE TABLE IF NOT EXISTS tenant_config (
    tenant_id VARCHAR(64) PRIMARY KEY,
    config JSONB NOT NULL,
    version INT DEFAULT 1,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
