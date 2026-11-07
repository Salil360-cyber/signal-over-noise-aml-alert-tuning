"""Draws the README charts from the CSVs that signal_over_noise_pipeline.py writes to outputs/.
Every number on a chart comes from those files; the asserts below stop the script if they drift
from the figures quoted in the README."""
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

OUT, IMG = Path("outputs"), Path("images")
IMG.mkdir(exist_ok=True)
BLUE, ORANGE, AQUA, GREY, INK = "#2a78d6", "#eb6834", "#1baf7a", "#9a9a95", "#222222"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titleweight": "bold", "axes.titlesize": 12, "figure.dpi": 110})

daily = pd.read_csv(OUT / "daily_volume.csv", parse_dates=["d"])
rules = pd.read_csv(OUT / "rule_scorecard.csv")
pkg = pd.read_csv(OUT / "package_before_after.csv")
cap = pd.read_csv(OUT / "capture_curve.csv")
typ = pd.read_csv(OUT / "typology_coverage.csv")

# ---- cross-checks against the README figures ----
assert daily.txns.sum() == 5_078_345 and daily.laundering.sum() == 5_177
assert rules.alerts.tolist() == [3235, 94576, 62120, 7657, 38917]
assert rules.true_pos.tolist() == [106, 585, 1190, 132, 94]
assert pkg.alerts.tolist() == [188_883, 158_918] and pkg.true_pos.tolist() == [1802, 1772]
BASE = 7130 / 2_315_960  # suspicious account-days / all account-days = 0.31%


def save(fig, name):
    fig.tight_layout()
    fig.savefig(IMG / name, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("saved", IMG / name)


# 1. Data-quality: the thin tail after 10 Sep
daily["share"] = daily.laundering / daily.txns
tail = daily.d >= "2022-09-11"
fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 5.6), sharex=True)
a1.bar(daily.d, daily.txns / 1000, color=[ORANGE if t else BLUE for t in tail])
a1.set_ylabel("Transactions (thousands)")
a1.set_title("Data check: after 10 Sep the data thins out and is mostly laundering")
a2.bar(daily.d, daily.share * 100, color=[ORANGE if t else BLUE for t in tail])
a2.set_ylabel("Laundering share (%)")
a2.set_yscale("log")
a2.set_yticks([0.01, 0.1, 1, 10, 100]); a2.set_yticklabels(["0.01", "0.1", "1", "10", "100"])
a2.set_xticks(daily.d); a2.set_xticklabels(daily.d.dt.strftime("%d Sep"), rotation=45, fontsize=8.5)
a1.legend(handles=[Patch(color=BLUE, label="1-10 Sep: kept"),
                   Patch(color=ORANGE, label=f"11-18 Sep: removed ({daily[tail].txns.sum():,} txns, "
                                             f"{int(daily[tail].laundering.sum())} laundering)")],
          frameon=False, loc="upper right")
save(fig, "01_data_quality_tail.png")

# 2. Rule precision vs base rate
r = rules.iloc[::-1]
fig, ax = plt.subplots(figsize=(9, 4))
cols = [ORANGE if p < BASE else BLUE for p in r.precision]
ax.barh(r.rule, r.precision * 100, color=cols)
ax.axvline(BASE * 100, color=INK, ls="--", lw=1)
ax.text(BASE * 100 + 0.05, 4.62, f"base rate {BASE:.2%} = picking at random", fontsize=9, va="center")
for y, (p, a, tp) in enumerate(zip(r.precision, r.alerts, r.true_pos)):
    ax.text(max(p, BASE) * 100 + 0.08, y, f"{p:.2%}  ({tp:,} TP / {a:,} alerts)", va="center", fontsize=9)
ax.set_ylim(-0.6, 4.85); ax.set_xlim(0, 4.6); ax.set_xlabel("Precision: share of alerts that were truly suspicious (%)")
ax.set_title("R5 is worse than picking account-days at random")
save(fig, "02_rule_precision.png")

# 3. One-step threshold raise
fig, ax = plt.subplots(figsize=(9, 4.2))
x = range(len(rules)); w = 0.38
ax.bar([i - w / 2 for i in x], rules.alert_cut * 100, w, color=BLUE, label="Alerts removed")
ax.bar([i + w / 2 for i in x], rules.tp_kept * 100, w, color=AQUA, label="True positives kept")
for i, (c, k) in enumerate(zip(rules.alert_cut, rules.tp_kept)):
    ax.text(i - w / 2, c * 100 + 1.5, f"{c:.0%}", ha="center", fontsize=9)
    ax.text(i + w / 2, k * 100 + 1.5, f"{k:.0%}", ha="center", fontsize=9)
labels = [f"{n}\n{t:g} -> {nt:g}" for n, t, nt in zip(rules.rule, rules.threshold, rules.next_threshold)]
ax.set_xticks(list(x)); ax.set_xticklabels(labels, fontsize=8.5)
ax.set_ylim(0, 112); ax.set_ylabel("%")
ax.set_title("Raising each threshold one step: what you save vs what you lose")
ax.legend(frameon=False, ncol=2, loc="upper right")
save(fig, "03_threshold_raise.png")

# 4. Recommended package
fig, axes = plt.subplots(1, 3, figsize=(10, 3.6))
names = ["Current\n(5 rules)", "Recommended\n(R5 off, R1 at 2)"]
for ax, col, title, fmt in [(axes[0], "alerts", "Alerts to review", "{:,.0f}"),
                            (axes[1], "true_pos", "Suspicious account-days caught", "{:,.0f}"),
                            (axes[2], "precision", "Precision", "{:.2%}")]:
    v = pkg[col]
    ax.bar(names, v, color=[GREY, BLUE])
    for i, val in enumerate(v):
        ax.text(i, val * 1.01, fmt.format(val), ha="center", va="bottom", fontsize=10)
    ax.set_title(title, fontsize=10.5); ax.set_yticks([]); ax.spines["left"].set_visible(False)
    ax.set_ylim(0, v.max() * 1.18)
cut = 1 - pkg.alerts[1] / pkg.alerts[0]; kept = pkg.true_pos[1] / pkg.true_pos[0]
fig.suptitle(f"Recommended package: {cut:.1%} fewer alerts, {kept:.1%} of true positives kept",
             fontweight="bold", fontsize=12)
save(fig, "04_package_before_after.png")

# 5. Capture curve
fig, ax = plt.subplots(figsize=(7.5, 5))
ax.plot(cap.pct_reviewed * 100, cap["Gradient boosting"] * 100, color=BLUE, lw=2.2, label="Gradient boosting")
ax.plot(cap.pct_reviewed * 100, cap["Logistic regression"] * 100, color=AQUA, lw=2, label="Logistic regression")
ax.plot([0, 100], [0, 100], color=GREY, ls="--", lw=1.2, label="Random order")
gb30 = cap.loc[cap.pct_reviewed.round(2) == 0.30, "Gradient boosting"].iloc[0]
ax.scatter([30], [gb30 * 100], color=ORANGE, zorder=5)
ax.annotate(f"Review top 30% of alerts\n-> find {gb30:.0%} of true positives", (30, gb30 * 100),
            xytext=(42, 52), fontsize=9.5, arrowprops=dict(arrowstyle="->", color=INK))
ax.set_xlabel("Alerts reviewed, highest score first (%)")
ax.set_ylabel("True positives found (%)")
ax.set_xlim(0, 100); ax.set_ylim(0, 102)
ax.set_title("Alert scoring on the test days (8-10 Sep)")
ax.legend(frameon=False, loc="lower right")
save(fig, "05_capture_curve.png")

# 6. Typology coverage
t = typ.sort_values("caught")
fig, ax = plt.subplots(figsize=(8.5, 4))
ax.barh(t.typology, t.caught * 100, color=BLUE)
for y, (c, n, a) in enumerate(zip(t.caught, t.account_days, t.alerted)):
    ax.text(c * 100 + 0.4, y, f"{c:.1%}  ({a} of {n})", va="center", fontsize=9)
ax.set_xlim(0, 40); ax.set_xlabel("Typology account-days caught by at least one rule (%)")
ax.set_title("Every laundering pattern is mostly missed: coverage 22-29%")
save(fig, "06_typology_coverage.png")
