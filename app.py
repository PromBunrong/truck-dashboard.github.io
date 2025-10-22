# streamlit run app.py
import streamlit as st
import pandas as pd
import numpy as np
from datetime import date
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Truck Loading Dashboard", page_icon="🚚", layout="wide")

# ====== 0) CONFIG: your Google Sheet (Action/Status tab) ======
SPREADSHEET_ID = "1UOCX8RFmvzYgvyUV2e2rYme_mp5E_h5yzJROKtewFHo"
GID_ACTION      = "0"  # tab with Action/Status
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={GID_ACTION}"

# ====== 1) REFRESH CONTROLS ======
# Auto-refresh every 60s (adjust as you like)
# --- Auto-refresh every 60 seconds ---


auto = st.sidebar.checkbox("Auto-refresh (60 s)", value=False)
if auto:
    count = st_autorefresh(interval=60_000, key="datarefresh")  # refresh every 60 s


# Manual refresh button
if st.sidebar.button("🔄 Refresh now"):
    st.cache_data.clear()

# ====== 2) LOAD DATA ======
@st.cache_data(ttl=60)  # refetch at most once per minute
def load_action():
    df = pd.read_csv(CSV_URL)
    # rename if needed
    rename_map = {"Plate Number":"Plate","Product Group":"Product","Action":"Status","Time":"Timestamp"}
    for k,v in rename_map.items():
        if k in df.columns and v not in df.columns:
            df = df.rename(columns={k:v})
    # required columns
    req = ["Timestamp","Product","Plate","Status"]
    missing = [c for c in req if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")
    # parse time & date
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df["Date"] = df["Timestamp"].dt.date
    # normalize status
    status_map = {
        "waiting":"Waiting","wait":"Waiting",
        "start":"Start Loading","start loading":"Start Loading","loading start":"Start Loading",
        "complete":"Complete Loading","completed":"Complete Loading","complete loading":"Complete Loading",
    }
    df["Status"] = (
        df["Status"].astype(str).str.strip().str.lower().map(status_map).fillna(df["Status"])
    )
    return df.dropna(subset=["Timestamp"])

action = load_action()

# ====== 3) PIVOT → one row per (Date, Product, Plate) ======
first_stage = (
    action.sort_values(["Date","Product","Plate","Status","Timestamp"])
          .groupby(["Date","Product","Plate","Status"], as_index=False)["Timestamp"]
          .first()
)
wide = (
    first_stage.pivot_table(
        index=["Date","Product","Plate"], columns="Status", values="Timestamp", aggfunc="first"
    ).reset_index()
)
for col in ["Waiting","Start Loading","Complete Loading"]:
    if col not in wide.columns:
        wide[col] = pd.NaT
wide = wide[["Date","Product","Plate","Waiting","Start Loading","Complete Loading"]]

# ====== 4) DURATIONS (min) ======
wide["Waiting_Time_min"] = (wide["Start Loading"] - wide["Waiting"]).dt.total_seconds() / 60
wide["Loading_Time_min"] = (wide["Complete Loading"] - wide["Start Loading"]).dt.total_seconds() / 60
wide["Total_Time_min"]   = (wide["Complete Loading"] - wide["Waiting"]).dt.total_seconds() / 60
for c in ["Waiting_Time_min","Loading_Time_min","Total_Time_min"]:
    wide.loc[wide[c] < 0, c] = np.nan

# ====== 5) FILTERS ======
dates = sorted(wide["Date"].dropna().unique().tolist())
default_date = date.today() if date.today() in dates else (dates[-1] if dates else None)
col1, col2 = st.columns([1,2])
with col1:
    sel_date = st.selectbox("Date", options=dates, index=(dates.index(default_date) if default_date in dates else 0))
with col2:
    products = sorted(wide["Product"].dropna().unique().tolist())
    sel_products = st.multiselect("Product group(s)", products, default=products)

df_day = wide[(wide["Date"]==sel_date) & (wide["Product"].isin(sel_products))]

# ====== 6) LIVE STATUS COUNTS (latest status per plate today) ======
latest = (
    action[action["Date"]==sel_date]
    .sort_values(["Plate","Timestamp"])
    .groupby("Plate").tail(1)  # latest row per plate
)
status_counts = latest["Status"].value_counts().reindex(
    ["Waiting","Start Loading","Complete Loading"], fill_value=0
)

k1,k2,k3 = st.columns(3)
k1.metric("🟡 Waiting", int(status_counts.get("Waiting",0)))
k2.metric("🟠 Start Loading", int(status_counts.get("Start Loading",0)))
k3.metric("🟢 Completed", int(status_counts.get("Complete Loading",0)))

# ====== 7) DAILY / PRODUCT SUMMARY ======
summary = (
    df_day.groupby(["Date","Product"], as_index=False)
          .agg(
              Avg_Waiting_min=("Waiting_Time_min","mean"),
              Avg_Loading_min=("Loading_Time_min","mean"),
              Avg_Total_min=("Total_Time_min","mean"),
              Truck_Count=("Plate","count"),
          )
          .round(1)
)

st.subheader("Daily Product Performance")
st.dataframe(summary, use_container_width=True)

# ====== 8) PER-TRUCK TABLE ======
st.subheader("Per Truck — Durations")
st.dataframe(
    df_day[["Product","Plate","Waiting","Start Loading","Complete Loading",
            "Waiting_Time_min","Loading_Time_min","Total_Time_min"]]
    .sort_values(["Product","Plate"])
    .round(1),
    use_container_width=True
)

# ====== 9) SIMPLE TREND CHART (Avg Total by product over time) ======
import matplotlib.pyplot as plt
trend = (
    wide.groupby(["Date","Product"], as_index=False)
        .agg(Avg_Total_min=("Total_Time_min","mean"))
        .dropna(subset=["Avg_Total_min"])
)
st.subheader("Trend — Avg Total Time by Product")
fig = plt.figure()
for p, g in trend.groupby("Product"):
    plt.plot(g["Date"], g["Avg_Total_min"], marker="o", label=p)
plt.xlabel("Date"); plt.ylabel("Avg Total (min)"); plt.title("Average Total Time by Product"); plt.legend(); plt.grid(True)
st.pyplot(fig)
