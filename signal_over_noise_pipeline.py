"""
Signal Over Noise: AML alert tuning & prioritisation (full pipeline, one file)
-----------------------------------------------------------------------------
Input : HI-Small_Trans.csv     (IBM AMLworld, HI-Small; see README for download)
        HI-Small_Patterns.txt  (optional: typology check)
        put both in the same folder as this script
Run   : pip install -r requirements.txt
        python signal_over_noise_pipeline.py
Time  : a few minutes on a normal laptop (DuckDB does the heavy lifting)
Output: outputs/results.txt and the CSV tables behind every chart and number in the README
"""
from pathlib import Path
import csv
import duckdb, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import average_precision_score

OUT = Path("outputs"); OUT.mkdir(exist_ok=True)
out = []
def say(s=""):
    print(s); out.append(s)

con = duckdb.connect()
# ---------------- 1. LOAD ----------------
con.execute("""CREATE TABLE raw AS SELECT * FROM read_csv('HI-Small_Trans.csv', header=true, all_varchar=true)""")
con.execute("""CREATE TABLE txn AS SELECT
  strptime(Timestamp,'%Y/%m/%d %H:%M') AS ts,
  "From Bank"||'-'||Account AS sender, "To Bank"||'-'||Account_1 AS receiver,
  CAST("Amount Received" AS DOUBLE) amt_received, "Receiving Currency" recv_ccy,
  CAST("Amount Paid" AS DOUBLE) amt_paid, "Payment Currency" pay_ccy,
  "Payment Format" pay_format, CAST("Is Laundering" AS INT) is_laundering FROM raw""")
n, l = con.execute("select count(*), sum(is_laundering) from txn").fetchone()
say("=== 1. DATA ===")
say(f"Transactions: {n:,} | laundering: {l:,} ({l/n:.2%})")
tn, tl = con.execute("select count(*), sum(is_laundering) from txn where ts >= '2022-09-11'").fetchone()
say(f"Data-quality finding: after 10 Sep only {tn:,} transactions remain, {tl:,} of them laundering -> window 1-10 Sep")
con.execute("""SELECT CAST(ts AS DATE) d, count(*) txns, sum(is_laundering) laundering FROM txn GROUP BY 1 ORDER BY 1""") \
   .df().to_csv(OUT / "daily_volume.csv", index=False)

# ---------------- 2. FX (derived from the data itself) ----------------
con.execute("""CREATE TABLE fx AS SELECT pay_ccy AS ccy, median(amt_received/amt_paid) usd_per_unit
  FROM txn WHERE recv_ccy='US Dollar' AND pay_ccy<>'US Dollar' AND amt_paid>0 GROUP BY 1
  UNION ALL SELECT 'US Dollar', 1.0""")
con.execute("SELECT * FROM fx ORDER BY ccy").df().to_csv(OUT / "fx_rates_from_data.csv", index=False)
con.execute("""CREATE TABLE t AS SELECT x.*, x.amt_paid*f.usd_per_unit AS amt_usd, CAST(ts AS DATE) AS d
  FROM txn x JOIN fx f ON f.ccy=x.pay_ccy WHERE ts < '2022-09-11' AND sender<>receiver""")
n2, l2 = con.execute("select count(*), sum(is_laundering) from t").fetchone()
say(f"After removing self-transfers and the tail: {n2:,} transactions, {l2:,} laundering")

# ---------------- 3. ACCOUNT x DAY FEATURES ----------------
con.execute("""CREATE TABLE ad AS
WITH o AS (SELECT sender acct, d, count(*) out_cnt, sum(amt_usd) out_amt, count(distinct receiver) out_cpty,
   count(*) FILTER (WHERE pay_format='Cash' AND amt_usd BETWEEN 9000 AND 9999.99) cash_near_10k,
   count(*) FILTER (WHERE pay_format IN ('Bitcoin','Wire')) risky_rail_cnt, max(is_laundering) out_flag FROM t GROUP BY 1,2),
 i AS (SELECT receiver acct, d, count(*) in_cnt, sum(amt_usd) in_amt, count(distinct sender) in_cpty, max(is_laundering) in_flag FROM t GROUP BY 1,2)
SELECT coalesce(o.acct,i.acct) AS acct, coalesce(o.d,i.d) AS d,
  coalesce(out_cnt,0) AS out_cnt, coalesce(out_amt,0) AS out_amt, coalesce(out_cpty,0) AS out_cpty,
  coalesce(cash_near_10k,0) AS cash_near_10k, coalesce(risky_rail_cnt,0) AS risky_rail_cnt,
  coalesce(in_cnt,0) AS in_cnt, coalesce(in_amt,0) AS in_amt, coalesce(in_cpty,0) AS in_cpty,
  CASE WHEN coalesce(in_amt,0)>0 THEN coalesce(out_amt,0)/in_amt END AS out_in_ratio,
  greatest(coalesce(out_flag,0),coalesce(in_flag,0)) AS lbl
FROM o FULL OUTER JOIN i ON o.acct=i.acct AND o.d=i.d""")
aw = con.execute("select * from ad order by acct, d").df()   # fixed order = same result every run
aw["out_in_ratio"] = aw.out_in_ratio.fillna(0); aw["d"] = pd.to_datetime(aw.d)
y = aw.lbl == 1; P = int(y.sum())
say(f"Account-days: {len(aw):,} | suspicious: {P:,} ({P/len(aw):.2%})")

# ---------------- 4. RULES + ATL TESTING ----------------
R = {"R1 Structuring":     (lambda d,t: d.cash_near_10k >= t, 1, 2),
     "R2 Fan-out":         (lambda d,t: d.out_cpty >= t, 4, 5),
     "R3 Fan-in":          (lambda d,t: d.in_cpty >= t, 3, 4),
     "R4 Pass-through":    (lambda d,t: (d.in_amt >= t) & d.out_in_ratio.between(0.8,1.2), 10000, 20000),
     "R5 High-risk rails": (lambda d,t: d.risky_rail_cnt >= t, 2, 3)}
say(""); say("=== 2. RULES (baseline) AND ONE-STEP THRESHOLD RAISE ===")
m, rows = {}, []
for k, (fn, b, nx) in R.items():
    mb, mn = fn(aw, b), fn(aw, nx); m[k] = mb
    bt, nt = int((mb & y).sum()), int((mn & y).sum())
    rows.append(dict(rule=k, threshold=b, alerts=int(mb.sum()), true_pos=bt, precision=bt/mb.sum(),
                     next_threshold=nx, next_alerts=int(mn.sum()), next_true_pos=nt,
                     alert_cut=1-mn.sum()/mb.sum(), tp_kept=nt/bt))
    say(f"{k}: {int(mb.sum()):,} alerts, {bt:,} TP, precision {bt/mb.sum():.2%} | raise {b}->{nx}: "
        f"alerts -{1-mn.sum()/mb.sum():.1%}, TP kept {nt/bt:.1%}")
pd.DataFrame(rows).to_csv(OUT / "rule_scorecard.csv", index=False)
base = np.logical_or.reduce(list(m.values())); bt = int((base & y).sum())
say(f"All rules: {int(base.sum()):,} alerts, {bt:,} TP, precision {bt/base.sum():.2%}, "
    f"coverage {bt/P:.1%} of suspicious account-days")

# ---------------- 5. RECOMMENDED PACKAGE ----------------
pkg = R["R1 Structuring"][0](aw, 2) | m["R2 Fan-out"] | m["R3 Fan-in"] | m["R4 Pass-through"]
pt = int((pkg & y).sum())
r1_2 = R["R1 Structuring"][0](aw, 2)
say(""); say("=== 3. RECOMMENDED PACKAGE: retire R5, raise R1 to 2 ===")
say(f"R1 at 2: {int(r1_2.sum()):,} alerts, {int((r1_2 & y).sum()):,} TP")
say(f"Alerts {int(base.sum()):,} -> {int(pkg.sum()):,} ({1-pkg.sum()/base.sum():.1%} fewer) | TP {bt:,} -> {pt:,} "
    f"({pt/bt:.1%} kept) | precision {bt/base.sum():.2%} -> {pt/pkg.sum():.2%}")
pd.DataFrame([dict(scenario="Current (5 rules)", alerts=int(base.sum()), true_pos=bt, precision=bt/base.sum()),
              dict(scenario="Recommended (retire R5, R1 at 2)", alerts=int(pkg.sum()), true_pos=pt, precision=pt/pkg.sum())]
             ).to_csv(OUT / "package_before_after.csv", index=False)

# ---------------- 6. ALERT RISK SCORING (time split) ----------------
al = aw[base].copy()
for k, (fn, b, _) in R.items(): al[k[:2]] = fn(al, b).astype(int)
al["rules_hit"] = al[[k[:2] for k in R]].sum(axis=1)
for c in ["out_amt", "in_amt"]: al[c] = np.log1p(al[c])
F = ["out_cnt","out_amt","out_cpty","in_cnt","in_amt","in_cpty","out_in_ratio","cash_near_10k","risky_rail_cnt","rules_hit"] + [k[:2] for k in R]
tr, te = al[al.d <= "2022-09-07"], al[al.d > "2022-09-07"]
say(""); say("=== 4. ALERT RISK SCORING (train 1-7 Sep, test 8-10 Sep) ===")
say(f"Train {len(tr):,} alerts ({tr.lbl.mean():.2%} TP) | Test {len(te):,} alerts ({te.lbl.mean():.2%} TP)")
def cap(yy, s, top): o = np.argsort(-s, kind="stable"); return yy.values[o][:int(len(yy)*top)].sum() / yy.sum()
curve = {"pct_reviewed": np.round(np.arange(0, 101) / 100, 2)}
for name, mdl in {"Logistic regression": make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=3000)),
                  "Gradient boosting": HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=42)}.items():
    mdl.fit(tr[F], tr.lbl); p = mdl.predict_proba(te[F])[:, 1]
    curve[name] = [cap(te.lbl, p, q) if q > 0 else 0.0 for q in curve["pct_reviewed"]]
    o = np.argsort(-p, kind="stable"); found = np.cumsum(te.lbl.values[o]) / te.lbl.sum()
    need80 = (np.argmax(found >= 0.8) + 1) / len(te)
    say(f"{name}: PR-AUC {average_precision_score(te.lbl, p):.3f} (random = {te.lbl.mean():.3f}) | "
        f"TP in top 10%: {cap(te.lbl, p, .10):.1%} | top 30%: {cap(te.lbl, p, .30):.1%} | "
        f"review {need80:.1%} of alerts to find 80% of TP")
pd.DataFrame(curve).to_csv(OUT / "capture_curve.csv", index=False)

# ---------------- 7. TYPOLOGY CHECK (which laundering patterns do the rules catch?) ----------------
if Path("HI-Small_Patterns.txt").exists():
    rows, cur = [], None
    with open("HI-Small_Patterns.txt") as f:
        for line in f:
            line = line.strip()
            if line.startswith("BEGIN LAUNDERING ATTEMPT"):
                cur = line.split("-", 1)[1].split(":")[0].strip()      # e.g. FAN-OUT
            elif line.startswith("END LAUNDERING ATTEMPT"):
                cur = None
            elif cur and line:
                p = next(csv.reader([line]))
                d = pd.Timestamp(p[0][:10].replace("/", "-"))
                rows += [(cur, f"{p[1]}-{p[2]}", d), (cur, f"{p[3]}-{p[4]}", d)]
    pat = pd.DataFrame(rows, columns=["typology", "acct", "d"]).drop_duplicates()
    sus = aw.loc[y, ["acct", "d"]].assign(alerted=base[y.values])
    j = pat.merge(sus, on=["acct", "d"])                                 # suspicious account-days in each typology
    typ = (j.groupby("typology").agg(account_days=("alerted", "size"), alerted=("alerted", "sum"))
             .assign(caught=lambda x: x.alerted / x.account_days).sort_values("caught"))
    typ.to_csv(OUT / "typology_coverage.csv")
    say(""); say("=== 5. TYPOLOGY CHECK (pattern file, suspicious account-days in each typology) ===")
    for t_, r_ in typ.iterrows():
        say(f"{t_}: {int(r_.account_days):,} account-days, {r_.caught:.1%} caught by at least one rule")

open(OUT / "results.txt", "w", encoding="utf-8").write("\n".join(out) + "\n")
print("\nSaved outputs/")
