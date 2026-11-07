"""Builds docs/index.html (the interactive explorer) from the CSVs in outputs/.
Needs outputs/threshold_grid.csv and outputs/rule_combos.csv from sql/05_explorer_data.sql."""
import json, sys
from pathlib import Path
import pandas as pd

OUT = Path("outputs")
data = {
    "scorecard": pd.read_csv(OUT / "rule_scorecard.csv")[["rule", "threshold", "alerts", "true_pos", "precision"]].to_dict("records"),
    "grid": pd.read_csv(OUT / "threshold_grid.csv").to_dict("records"),
    "combos": pd.read_csv(OUT / "rule_combos.csv").to_dict("records"),
    "capture": pd.read_csv(OUT / "capture_curve.csv").round(4).to_dict("records"),
    "typology": pd.read_csv(OUT / "typology_coverage.csv").round(4).to_dict("records"),
}
# the explorer must reproduce the headline numbers
c = pd.DataFrame(data["combos"])
assert c.alerts.sum() == 188_883 and c.true_pos.sum() == 1802
rec = c[(c.r1_2 == 1) | (c.r2 == 1) | (c.r3 == 1) | (c.r4 == 1)]
assert rec.alerts.sum() == 158_918 and rec.true_pos.sum() == 1772

body = Path("docs/template.html").read_text().replace("__DATA__", json.dumps(data, separators=(",", ":")))
Path("docs/index.html").write_text(
    '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    "<style>body{margin:0}[hidden]{display:none!important}</style>\n</head>\n<body>\n" + body + "\n</body>\n</html>\n")
if len(sys.argv) > 1:  # optional: also write the fragment version used for the hosted preview
    Path(sys.argv[1]).write_text(body)
print("wrote docs/index.html")
