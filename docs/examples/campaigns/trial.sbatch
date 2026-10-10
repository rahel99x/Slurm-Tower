#!/bin/bash
#SBATCH --cpus-per-task=1
#SBATCH --mem=128M
#SBATCH --time=00:05:00
python3 - <<'PY'
import json
import os
values = json.loads(os.environ["TOWER_TRIAL_PARAMETERS"])
print(json.dumps({"trial": os.environ["TOWER_TRIAL_ID"],
                  "status": "success", "metric": (values["x"] - 2) ** 2}))
PY
