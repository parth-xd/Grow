-- Stock historical prices table (OHLCV data)
CREATE TABLE IF NOT EXISTS stock_prices (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    open FLOAT,
    high FLOAT,
    low FLOAT,
    close FLOAT,
    volume BIGINT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, date)
);

-- Link theses with price snapshots
ALTER TABLE theses ADD COLUMN IF NOT EXISTS created_date DATE DEFAULT CURRENT_DATE;
ALTER TABLE theses ADD COLUMN IF NOT EXISTS current_price FLOAT;
ALTER TABLE theses ADD COLUMN IF NOT EXISTS last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- Create indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_stock_prices_symbol ON stock_prices(symbol);
CREATE INDEX IF NOT EXISTS idx_stock_prices_date ON stock_prices(date);
CREATE INDEX IF NOT EXISTS idx_stock_prices_symbol_date ON stock_prices(symbol, date);

-- Summary table for quick thesis analysis
CREATE TABLE IF NOT EXISTS thesis_analysis (
    id SERIAL PRIMARY KEY,
    thesis_id INT REFERENCES theses(id),
    symbol VARCHAR(20),
    entry_date DATE,
    entry_price FLOAT,
    target_price FLOAT,
    current_price FLOAT,
    days_held INT,
    current_return_pct FLOAT,
    max_price FLOAT,
    min_price FLOAT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_thesis_analysis_symbol ON thesis_analysis(symbol);
