"""
Configuration and path management for LiDAR Snow Filtering project.

This module centralizes all path management, making the repo reproducible
without hardcoded paths.
"""

from pathlib import Path

# ============================================================================
# PROJECT ROOT
# ============================================================================
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ============================================================================
# DATA DIRECTORIES (for local testing; paths should be set relative to repo)
# ============================================================================
DATA_DIR = PROJECT_ROOT / "data"

SNOW_DATA_DIR = DATA_DIR / "snow_scans"
CLEAR_DATA_DIR = DATA_DIR / "clear_scans"
RESULTS_DIR = PROJECT_ROOT / "results"

# ============================================================================
# SENSOR DATA SAMPLES (example paths - users should provide their own)
# ============================================================================
EXAMPLE_SNOW_PCD = SNOW_DATA_DIR / "snow_cloud_sample.pcd"
EXAMPLE_CLEAR_PCD = CLEAR_DATA_DIR / "clear_cloud_sample.pcd"

# ============================================================================
# OUTPUT & RESULTS
# ============================================================================
BENCHMARK_RESULTS = RESULTS_DIR / "benchmark_results.csv"
EVALUATION_METRICS = RESULTS_DIR / "evaluation_metrics.json"
PLOTS_DIR = RESULTS_DIR / "plots"

# ============================================================================
# FILTER PARAMETERS (defaults used for synthetic/public examples)
# ============================================================================
SOR_NB_NEIGHBORS = 20
SOR_STD_RATIO = 2.0

ROR_NB_POINTS = 5
ROR_RADIUS = 0.05

DSOR_MIN_RATIO = 1.5
DSOR_SECTOR_COUNT = 8

DROR_SECTOR_COUNT = 12
DROR_SCALE_FACTOR = 1.5

# ============================================================================
# TIMING & BENCHMARKING
# ============================================================================
TIMEIT_REPEAT = 1000
TIMEIT_LOOPS = 3


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
def get_data_path(filename: str, data_type: str = "snow") -> Path:
    """Resolve a data filename to its full path."""
    if data_type == "snow":
        return SNOW_DATA_DIR / filename
    elif data_type == "clear":
        return CLEAR_DATA_DIR / filename
    else:
        raise ValueError(f"Invalid data_type: {data_type}. Use 'snow' or 'clear'.")


def ensure_project_dirs() -> None:
    """Create local data/result directories for scripts that write outputs."""
    for directory in [SNOW_DATA_DIR, CLEAR_DATA_DIR, RESULTS_DIR, PLOTS_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    ensure_project_dirs()
    print(f"Project Root: {PROJECT_ROOT}")
    print(f"Data Directory: {DATA_DIR}")
    print(f"Results Directory: {RESULTS_DIR}")
