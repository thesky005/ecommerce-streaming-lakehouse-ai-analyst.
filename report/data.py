"""Reads Gold Delta tables with delta-rs (no Spark or JVM needed by the report)."""
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from deltalake import DeltaTable
from deltalake.exceptions import TableNotFoundError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAKE_ROOT = Path(os.getenv("LAKE_ROOT", PROJECT_ROOT / "lake"))


@st.cache_data(ttl=60, show_spinner=False)
def load(name: str, layer: str = "gold") -> pd.DataFrame:
    try:
        df = DeltaTable(str(LAKE_ROOT / layer / name)).to_pandas()
    except (TableNotFoundError, FileNotFoundError, OSError):
        return pd.DataFrame()
    for column in df.columns:
        if column == "date" or column.endswith("_date") or column in ("cohort_week", "hour"):
            df[column] = pd.to_datetime(df[column])
    return df


def lake_ready() -> bool:
    return not load("fact_orders").empty
