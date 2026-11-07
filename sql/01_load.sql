-- Signal Over Noise: PostgreSQL version of the pipeline (same logic and numbers as the Python/DuckDB script)
-- Run from the folder that holds HI-Small_Trans.csv:  psql -d aml -f sql/01_load.sql

-- 1) Staging: everything as text, exactly as in the CSV
DROP TABLE IF EXISTS stg_txn CASCADE;
CREATE TABLE stg_txn (
  ts TEXT, from_bank TEXT, from_acct TEXT, to_bank TEXT, to_acct TEXT,
  amt_received TEXT, recv_ccy TEXT, amt_paid TEXT, pay_ccy TEXT,
  pay_format TEXT, is_laundering TEXT
);
\copy stg_txn FROM 'HI-Small_Trans.csv' CSV HEADER

-- 2) Typed table with composite account keys (bank + account)
DROP TABLE IF EXISTS txn CASCADE;
CREATE TABLE txn AS
SELECT TO_TIMESTAMP(ts, 'YYYY/MM/DD HH24:MI')::timestamp AS ts,
       from_bank || '-' || from_acct  AS sender,
       to_bank   || '-' || to_acct    AS receiver,
       amt_received::FLOAT8           AS amt_received, recv_ccy,
       amt_paid::FLOAT8               AS amt_paid,     pay_ccy,
       pay_format,
       is_laundering::SMALLINT        AS is_laundering
FROM stg_txn;

-- Data-quality check: the last days are a thin tail dominated by laundering rows
SELECT ts::date AS d, COUNT(*) AS txns, SUM(is_laundering) AS laundering
FROM txn GROUP BY 1 ORDER BY 1;

-- 3) FX to USD derived from the data itself: median rate of rows paid in X and received in USD
DROP TABLE IF EXISTS fx_rates;
CREATE TABLE fx_rates AS
SELECT pay_ccy AS ccy,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY amt_received / amt_paid) AS usd_per_unit
FROM txn
WHERE recv_ccy = 'US Dollar' AND pay_ccy <> 'US Dollar' AND amt_paid > 0
GROUP BY 1
UNION ALL SELECT 'US Dollar', 1.0;

-- 4) Analysis table: 1-10 Sep only, no self-transfers, amounts in USD
DROP TABLE IF EXISTS t CASCADE;
CREATE TABLE t AS
SELECT x.*, x.amt_paid * f.usd_per_unit AS amt_usd, x.ts::date AS d
FROM txn x JOIN fx_rates f ON f.ccy = x.pay_ccy
WHERE x.ts < '2022-09-11' AND x.sender <> x.receiver;

CREATE INDEX ON t (sender, d);
CREATE INDEX ON t (receiver, d);

-- Sanity check (expected: 5,078,345 / 5,177 raw; 4,486,418 / 4,514 after cleaning)
SELECT (SELECT COUNT(*) FROM txn) AS raw_rows, (SELECT SUM(is_laundering) FROM txn) AS raw_laundering,
       (SELECT COUNT(*) FROM t)   AS clean_rows, (SELECT SUM(is_laundering) FROM t) AS clean_laundering;
