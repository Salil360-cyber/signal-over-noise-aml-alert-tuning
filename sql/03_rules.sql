-- Five transaction-monitoring scenarios at their baseline thresholds
DROP TABLE IF EXISTS alerts;
CREATE TABLE alerts AS
SELECT acct, d, label,
       (cash_near_10k  >= 1)                                          AS r1_structuring,
       (out_cpty       >= 4)                                          AS r2_fan_out,
       (in_cpty        >= 3)                                          AS r3_fan_in,
       (in_amt >= 10000 AND out_in_ratio BETWEEN 0.8 AND 1.2)         AS r4_pass_through,
       (risky_rail_cnt >= 2)                                          AS r5_risky_rails,
       -- next threshold up, for ATL testing
       (cash_near_10k  >= 2)                                          AS r1_next,
       (out_cpty       >= 5)                                          AS r2_next,
       (in_cpty        >= 4)                                          AS r3_next,
       (in_amt >= 20000 AND out_in_ratio BETWEEN 0.8 AND 1.2)         AS r4_next,
       (risky_rail_cnt >= 3)                                          AS r5_next
FROM acct_day
WHERE cash_near_10k >= 1 OR out_cpty >= 4 OR in_cpty >= 3 OR risky_rail_cnt >= 2
   OR (in_amt >= 10000 AND out_in_ratio BETWEEN 0.8 AND 1.2);

-- Rule scorecard + ATL test: what happens if each threshold goes up one step?
WITH r AS (
  SELECT 'R1 Structuring' AS rule, r1_structuring AS hit, r1_next AS hit_next, label FROM alerts
  UNION ALL SELECT 'R2 Fan-out',         r2_fan_out,      r2_next, label FROM alerts
  UNION ALL SELECT 'R3 Fan-in',          r3_fan_in,       r3_next, label FROM alerts
  UNION ALL SELECT 'R4 Pass-through',    r4_pass_through, r4_next, label FROM alerts
  UNION ALL SELECT 'R5 High-risk rails', r5_risky_rails,  r5_next, label FROM alerts
)
SELECT rule,
       COUNT(*) FILTER (WHERE hit)                                         AS alerts,
       SUM(label) FILTER (WHERE hit)                                       AS true_pos,
       ROUND(100.0 * SUM(label) FILTER (WHERE hit) / COUNT(*) FILTER (WHERE hit), 2) AS precision_pct,
       ROUND(100.0 * (1 - COUNT(*) FILTER (WHERE hit_next)::numeric / COUNT(*) FILTER (WHERE hit)), 1) AS alert_cut_pct_if_raised,
       ROUND(100.0 * SUM(label) FILTER (WHERE hit_next) / SUM(label) FILTER (WHERE hit), 1)            AS tp_kept_pct_if_raised
FROM r GROUP BY rule ORDER BY rule;

-- Overall (expected: 188,883 alerts, 1,802 TP, 0.95% precision, 25.3% coverage)
SELECT COUNT(*) AS alerts, SUM(label) AS true_pos,
       ROUND(100.0 * SUM(label) / COUNT(*), 2) AS precision_pct,
       ROUND(100.0 * SUM(label) / (SELECT SUM(label) FROM acct_day), 1) AS coverage_pct
FROM alerts;

-- Recommended package: retire R5 (precision below the 0.31% base rate) and raise R1 to 2
-- (expected: 158,918 alerts, 1,772 TP -> 15.9% fewer alerts, 98.3% of TP kept)
SELECT COUNT(*) AS alerts, SUM(label) AS true_pos,
       ROUND(100.0 * (1 - COUNT(*)::numeric / (SELECT COUNT(*) FROM alerts)), 1)   AS alert_cut_pct,
       ROUND(100.0 * SUM(label) / (SELECT SUM(label) FROM alerts), 1)              AS tp_kept_pct,
       ROUND(100.0 * SUM(label) / COUNT(*), 2)                                     AS precision_pct
FROM alerts
WHERE r1_next OR r2_fan_out OR r3_fan_in OR r4_pass_through;
