-- Account x day behaviour features (the data covers only 10 days, so weekly windows would be too few)
DROP TABLE IF EXISTS acct_day;
CREATE TABLE acct_day AS
WITH outflow AS (
  SELECT sender AS acct, d,
         COUNT(*)                 AS out_cnt,
         SUM(amt_usd)             AS out_amt,
         COUNT(DISTINCT receiver) AS out_cpty,
         COUNT(*) FILTER (WHERE pay_format = 'Cash' AND amt_usd BETWEEN 9000 AND 9999.99) AS cash_near_10k,
         COUNT(*) FILTER (WHERE pay_format IN ('Bitcoin', 'Wire'))                       AS risky_rail_cnt,
         MAX(is_laundering)       AS out_flag
  FROM t GROUP BY 1, 2
),
inflow AS (
  SELECT receiver AS acct, d,
         COUNT(*)               AS in_cnt,
         SUM(amt_usd)           AS in_amt,
         COUNT(DISTINCT sender) AS in_cpty,
         MAX(is_laundering)     AS in_flag
  FROM t GROUP BY 1, 2
)
SELECT COALESCE(o.acct, i.acct) AS acct,
       COALESCE(o.d, i.d)       AS d,
       COALESCE(out_cnt, 0)  AS out_cnt,  COALESCE(out_amt, 0)  AS out_amt,  COALESCE(out_cpty, 0) AS out_cpty,
       COALESCE(cash_near_10k, 0) AS cash_near_10k, COALESCE(risky_rail_cnt, 0) AS risky_rail_cnt,
       COALESCE(in_cnt, 0)   AS in_cnt,   COALESCE(in_amt, 0)   AS in_amt,   COALESCE(in_cpty, 0)  AS in_cpty,
       -- pass-through: how much of what came in went out the same day
       COALESCE(CASE WHEN COALESCE(in_amt, 0) > 0 THEN COALESCE(out_amt, 0) / in_amt END, 0) AS out_in_ratio,
       GREATEST(COALESCE(out_flag, 0), COALESCE(in_flag, 0)) AS label
FROM outflow o
FULL OUTER JOIN inflow i ON o.acct = i.acct AND o.d = i.d;

-- Expected: 2,315,960 account-days, 7,130 suspicious (0.31%)
SELECT COUNT(*) AS account_days, SUM(label) AS suspicious,
       ROUND(100.0 * AVG(label), 2) AS suspicious_pct
FROM acct_day;

-- Feature distribution: used to choose the baseline thresholds
SELECT PERCENTILE_CONT(ARRAY[0.5, 0.9, 0.99, 0.999]) WITHIN GROUP (ORDER BY out_cpty) AS out_cpty_pct,
       PERCENTILE_CONT(ARRAY[0.5, 0.9, 0.99, 0.999]) WITHIN GROUP (ORDER BY in_cpty)  AS in_cpty_pct
FROM acct_day;
