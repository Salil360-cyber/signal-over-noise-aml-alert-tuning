-- Exports the small tables behind the interactive explorer (docs/index.html).
-- Run after 01-03:  psql -d aml -f sql/05_explorer_data.sql

-- 1) Each rule on its own across a range of thresholds
DROP TABLE IF EXISTS threshold_grid;
CREATE TABLE threshold_grid AS
WITH g AS (
  SELECT 'R1 Structuring' AS rule, n::float8 AS thr FROM generate_series(1, 5) n
  UNION ALL SELECT 'R2 Fan-out', n FROM generate_series(2, 15) n
  UNION ALL SELECT 'R3 Fan-in',  n FROM generate_series(2, 15) n
  UNION ALL SELECT 'R4 Pass-through', n * 5000 FROM generate_series(1, 20) n
  UNION ALL SELECT 'R5 High-risk rails', n FROM generate_series(1, 6) n
)
SELECT g.rule, g.thr,
       COUNT(a.*)              AS alerts,
       COALESCE(SUM(a.label),0) AS true_pos
FROM g LEFT JOIN acct_day a ON CASE g.rule
     WHEN 'R1 Structuring'     THEN a.cash_near_10k >= g.thr
     WHEN 'R2 Fan-out'         THEN a.out_cpty >= g.thr
     WHEN 'R3 Fan-in'          THEN a.in_cpty >= g.thr
     WHEN 'R4 Pass-through'    THEN a.in_amt >= g.thr AND a.out_in_ratio BETWEEN 0.8 AND 1.2
     WHEN 'R5 High-risk rails' THEN a.risky_rail_cnt >= g.thr END
GROUP BY 1, 2 ORDER BY 1, 2;
\copy threshold_grid TO 'outputs/threshold_grid.csv' CSV HEADER

-- 2) Which combination of rules fired on each alerted account-day.
--    Any package (rules on/off, R1 at 1 or 2) can be scored exactly from this table.
DROP TABLE IF EXISTS rule_combos;
CREATE TABLE rule_combos AS
SELECT r1_structuring::int AS r1, r1_next::int AS r1_2, r2_fan_out::int AS r2, r3_fan_in::int AS r3,
       r4_pass_through::int AS r4, r5_risky_rails::int AS r5,
       COUNT(*) AS alerts, SUM(label) AS true_pos
FROM alerts GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY alerts DESC;
\copy rule_combos TO 'outputs/rule_combos.csv' CSV HEADER
