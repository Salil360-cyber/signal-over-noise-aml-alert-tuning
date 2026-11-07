-- Case pull for one alert. Usage:
--   psql -d aml -v acct='001047-801C31E90' -v d='2022-09-02' -f sql/04_case_pull.sql

-- 1) Transaction trail: 3 days either side of the alert day
SELECT ts, sender, receiver, ROUND(amt_usd::numeric, 2) AS amt_usd, pay_format, pay_ccy,
       CASE WHEN sender = :'acct' THEN 'OUT' ELSE 'IN' END AS direction
FROM t
WHERE (sender = :'acct' OR receiver = :'acct')
  AND d BETWEEN :'d'::date - 3 AND :'d'::date + 3
ORDER BY ts;

-- 2) Counterparty summary: who is this account really dealing with?
SELECT CASE WHEN sender = :'acct' THEN receiver ELSE sender END AS counterparty,
       COUNT(*) AS txns, ROUND(SUM(amt_usd)::numeric, 2) AS total_usd, MIN(ts) AS first_seen, MAX(ts) AS last_seen
FROM t
WHERE sender = :'acct' OR receiver = :'acct'
GROUP BY 1 ORDER BY total_usd DESC LIMIT 20;

-- 3) The alert day compared with the account's own average on earlier days
SELECT a.d, a.out_cnt, ROUND(a.out_amt::numeric, 2) AS out_amt, a.out_cpty, a.in_cpty,
       (SELECT ROUND(AVG(out_amt)::numeric, 2) FROM acct_day b WHERE b.acct = a.acct AND b.d < a.d) AS avg_daily_out_before,
       (SELECT ROUND(AVG(out_cpty)::numeric, 1) FROM acct_day b WHERE b.acct = a.acct AND b.d < a.d) AS avg_out_cpty_before
FROM acct_day a WHERE a.acct = :'acct' AND a.d = :'d'::date;
