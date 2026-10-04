#!/usr/bin/env bash
#SBATCH --job-name=pi-series
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=256M
#SBATCH --time=00:05:00
#SBATCH --output=logs/%j.out
#SBATCH --error=logs/%j.err
set -euo pipefail

# Submit from the project root. Slurm opens these root-level logs before this
# script starts; create logs/ BEFORE sbatch, never inside the job as a substitute.
cd "${SLURM_SUBMIT_DIR:?Submit this script from the project root}"
exec python3 experiment.py --slurm
