import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import time
from pathlib import Path

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False

st.set_page_config(page_title="Daily Orders Command Center", page_icon="◈", layout="wide")

# ---------- Theme ----------
# Keep the whole app on one light surface (main area + sidebar) so widget
# internals (dropdown menus, chips, calendar popovers) never fight a dark
# background with their own default dark text.
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Sora:wght@600;700&display=swap');
html, body, [class*="css"] { font-family: 'Manrope', sans-serif; }
.stApp { background: #F4F6F5; color: #1B2321; }

[data-testid="stSidebar"] { background: #EAF0EC; border-right: 1px solid #D3DED8; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color: #16241F; }
[data-testid="stSidebar"] label, [data-testid="stSidebar"] p, [data-testid="stSidebar"] span { color: #1B2321; }
[data-testid="stSidebar"] [data-baseweb="tag"] { background: #0F6B4C !important; }
[data-testid="stSidebar"] [data-baseweb="tag"] span { color: #FFFFFF !important; }

.block-container { max-width: 1520px; padding-top: 1.2rem; padding-bottom: 2.5rem; }
h1, h2, h3 { font-family: 'Sora', sans-serif; color: #16241F; }
h1 { letter-spacing: -0.01em; }

.card {
    background: white; border: 1px solid #E1E8E4; border-radius: 12px;
    padding: 18px 20px; box-shadow: 0 1px 3px rgba(22,36,31,.06);
    margin-bottom: 10px; color: #1B2321;
}
.card b { color: #0F6B4C; }
[data-testid="stMetric"] {
    background: white; border: 1px solid #E1E8E4; border-left: 4px solid #0F6B4C; border-radius: 10px;
    padding: 14px 16px; box-shadow: 0 1px 3px rgba(22,36,31,.06);
}
[data-testid="stMetricValue"] {
    color: #16241F;
    font-size: 1.65rem;
    white-space: normal;
    overflow: visible;
    text-overflow: clip;
    line-height: 1.25;
}
[data-testid="stMetricLabel"] { color: #5B6B64; font-weight: 600; }
[data-testid="stTabs"] button { font-weight: 700; font-family: 'Sora', sans-serif; }
.small { color:#5B6B64; font-size:.85rem; }
.opp-high { color: #B3391F; font-weight: 700; }
.opp-mid { color: #946200; font-weight: 700; }
.opp-low { color: #0F6B4C; font-weight: 700; }
hr { border-color: #E1E8E4; }

/* Plain HTML tables rendered via .to_html() (Campaign opportunity table) */
table { color: #1B2321; }
th { color: #16241F; }
</style>
""", unsafe_allow_html=True)

CHART_COLORS = ["#0F6B4C", "#E0A72E", "#3D6EB0", "#B3391F", "#7A5EA8", "#3E8E8B", "#C6702F", "#5B6B64"]
px.defaults.color_discrete_sequence = CHART_COLORS
TEMPLATE = "plotly_white"

DATA_FILE = Path(__file__).parent / "data" / "orders.csv"

# Channels that are essentially always paid-acquisition when they appear as the
# referring channel alongside a UTM campaign (used for the "paid revenue" cuts).
PAID_CHANNEL_HINTS = ["google", "facebook", "instagram", "meta", "fb", "ig", "bing"]


def _default_sheet_url():
    # Optional: put data_source_url = "https://docs.google.com/.../pub?output=csv"
    # in .streamlit/secrets.toml to set a permanent default instead of pasting
    # it into the sidebar every time.
    try:
        return st.secrets.get("data_source_url", "")
    except Exception:
        return ""


@st.cache_data(ttl=600)
def load_data(source, _refresh_bucket):
    d = pd.read_csv(source)
    d.columns = [str(c).strip() for c in d.columns]

    if "Day" in d:
        # The sheet mixes two date-separator styles ("30/07/2026" and
        # "29-07-2026"). pandas' bulk parser infers ONE format for the whole
        # column, so whichever style loses gets silently dropped to NaT.
        # Normalize separators to "/" first so every value shares one style
        # before parsing (still day-first, e.g. 29-07-2026 -> 29/07/2026).
        raw_day = d["Day"].astype(str).str.strip()
        normalized_day = raw_day.str.replace("-", "/", regex=False)
        d["Day"] = pd.to_datetime(normalized_day, dayfirst=True, errors="coerce")

    if "Total sales (last click)" in d:
        d["Sales"] = pd.to_numeric(
            d["Total sales (last click)"].astype(str).str.replace(r"[₹$,\s]", "", regex=True),
            errors="coerce",
        ).fillna(0)
    else:
        d["Sales"] = 0.0

    d["Region"] = d.get("Shipping region", pd.Series(index=d.index)).fillna("Missing").replace("", "Missing")
    d["City"] = d.get("Shipping city", pd.Series(index=d.index)).fillna("Missing").replace("", "Missing")

    def safe_col(name):
        return d[name] if name in d.columns else pd.Series("Missing", index=d.index)

    d["First Channel Raw"] = safe_col("First order referring channel").fillna("Missing").replace("", "Missing")
    d["Last Channel Raw"] = safe_col("Referring channel").fillna("Missing").replace("", "Missing")

    d["UTM Campaign"] = safe_col("UTM campaign name").fillna("Missing").replace("", "Missing")
    if "Order UTM campaign" in d.columns:
        d["UTM Campaign"] = d["UTM Campaign"].where(
            d["UTM Campaign"] != "Missing", d["Order UTM campaign"].fillna("Missing").replace("", "Missing")
        )

    d["UTM Source"] = safe_col("UTM source").fillna("Missing").replace("", "Missing")
    d["UTM Medium"] = safe_col("UTM medium").fillna("Missing").replace("", "Missing")
    d["Notes"] = safe_col("Notes").fillna("").astype(str).str.strip()
    d["Found On"] = safe_col("Found on shopify or zoho").fillna("Missing").replace("", "Missing")

    return d


def meta_group(x):
    if pd.isna(x):
        return "Missing"
    s = str(x).strip()
    if not s:
        return "Missing"
    low = s.lower()
    if any(k in low for k in ["facebook", "instagram", "insta", "fb", "meta"]):
        return "Meta"
    return s.capitalize() if s.islower() else s


def meta_detail(x):
    if pd.isna(x):
        return "Missing"
    s = str(x).strip()
    if not s:
        return "Missing"
    low = s.lower()
    if "instagram" in low or "insta" in low or low == "ig":
        return "Instagram"
    if "facebook" in low or low == "fb":
        return "Facebook"
    if "meta" in low:
        return "Meta"
    return s


# ---------- Sidebar: data source ----------
st.sidebar.markdown("## ◈ Daily Orders")

with st.sidebar.expander("🔄 Live spreadsheet source", expanded=False):
    st.caption(
        "In Google Sheets: File → Share → Publish to web → select the sheet tab → "
        "format **CSV** → Publish. Paste the link below."
    )
    sheet_url = st.text_input("Google Sheet CSV link", value=_default_sheet_url(), placeholder="https://docs.google.com/.../pub?output=csv")
    refresh_secs = st.slider("Auto-refresh every (seconds)", 15, 300, 60, step=15)
    if not HAS_AUTOREFRESH:
        st.caption("Add `streamlit-autorefresh` to requirements.txt for hands-free live refresh; otherwise use the button below.")
    if st.button("Refresh now"):
        st.cache_data.clear()
        st.rerun()

if sheet_url.strip() and HAS_AUTOREFRESH:
    st_autorefresh(interval=refresh_secs * 1000, key="live_data_autorefresh")

data_source = sheet_url.strip() if sheet_url.strip() else DATA_FILE
refresh_bucket = int(time.time() // refresh_secs)
df = load_data(data_source, refresh_bucket)
if isinstance(data_source, str):
    st.sidebar.caption(f"Live source connected · refreshing every {refresh_secs}s")
else:
    st.sidebar.caption("Using local data/orders.csv")

df["First Channel"] = df["First Channel Raw"].map(meta_group)
df["Last Channel"] = df["Last Channel Raw"].map(meta_group)
df["First Channel Detail"] = df["First Channel Raw"].map(meta_detail)
df["Last Channel Detail"] = df["Last Channel Raw"].map(meta_detail)
df["Is Paid"] = df["UTM Campaign"] != "Missing"
df["Has Notes"] = df["Notes"] != ""

st.sidebar.divider()
st.sidebar.caption("Filter the complete order dataset")

f = df.copy()

if f["Day"].notna().any():
    lo, hi = f["Day"].min().date(), f["Day"].max().date()
    dr = st.sidebar.date_input("Date range", (lo, hi), min_value=lo, max_value=hi)
    if isinstance(dr, tuple) and len(dr) == 2:
        f = f[(f["Day"].dt.date >= dr[0]) & (f["Day"].dt.date <= dr[1])]


def filter_col(label, col):
    global f
    vals = sorted(f[col].fillna("Missing").astype(str).unique().tolist())
    selected = st.sidebar.multiselect(label, vals)
    if selected:
        f = f[f[col].fillna("Missing").astype(str).isin(selected)]


filter_col("Channel — combined", "Last Channel")
filter_col("Channel — individual", "Last Channel Detail")
filter_col("First-click channel", "First Channel")
filter_col("Region", "Region")
filter_col("City", "City")
filter_col("UTM campaign", "UTM Campaign")
filter_col("UTM source", "UTM Source")
filter_col("UTM medium", "UTM Medium")

st.sidebar.divider()
st.sidebar.caption(f"{len(f):,} orders shown from {len(df):,}")

# ---------- Helpers ----------
def money(v):
    return f"₹{v:,.0f}"


def money_compact(v):
    """Indian-numbering compact form (₹1.24 Cr / ₹8.6 L / ₹42.3 K) for KPI cards,
    so large totals never overflow the metric widget."""
    v = float(v)
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1_00_00_000:
        return f"{sign}₹{v/1_00_00_000:.2f} Cr"
    if v >= 1_00_000:
        return f"{sign}₹{v/1_00_000:.2f} L"
    if v >= 1_000:
        return f"{sign}₹{v/1_000:.1f} K"
    return f"{sign}₹{v:,.0f}"


def pct(n, d):
    return n / d * 100 if d else 0


def group(data, col):
    x = data.groupby(col).agg(Orders=("Sales", "size"), Sales=("Sales", "sum")).reset_index()
    x["AOV"] = x["Sales"] / x["Orders"].replace(0, np.nan)
    x["Sales Share"] = x["Sales"] / x["Sales"].sum() * 100 if x["Sales"].sum() else 0
    return x.sort_values("Sales", ascending=False)


def hbar(data, x_col, y_col, title):
    fig = px.bar(data, x=x_col, y=y_col, orientation="h", title=title)
    fig.update_layout(template=TEMPLATE, yaxis={"categoryorder": "total ascending"}, margin=dict(t=50, l=10, r=10, b=10))
    return fig


# ---------- Header ----------
st.title("Daily Orders Command Center")
st.caption("Order intelligence • attribution • geography • data quality — built on the full source dataset")

orders = len(f)
sales = f["Sales"].sum()
aov = sales / orders if orders else 0
attributed = (f["Last Channel"] != "Missing").sum()

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Orders", f"{orders:,}")
k2.metric("Total Sales", money_compact(sales), help=money(sales))
k3.metric("Average Order Value", money_compact(aov), help=money(aov))
k4.metric("Attribution Rate", f"{pct(attributed, orders):.1f}%", f"{attributed:,} attributed")

tabs = st.tabs(["Overview", "Attribution", "Geography", "Insights", "Data Quality", "Order Explorer"])

# ================= OVERVIEW =================
with tabs[0]:
    if f["Day"].notna().any():
        daily = f.dropna(subset=["Day"]).groupby("Day").agg(Orders=("Sales", "size"), Sales=("Sales", "sum")).reset_index()
        fig = go.Figure()
        fig.add_bar(x=daily["Day"], y=daily["Orders"], name="Orders", marker_color="#CFE3D8", yaxis="y2", opacity=0.7)
        fig.add_trace(go.Scatter(x=daily["Day"], y=daily["Sales"], name="Sales", mode="lines+markers",
                                  line=dict(color="#0F6B4C", width=3)))
        fig.update_layout(
            template=TEMPLATE, title="Sales trend (with daily order volume)", hovermode="x unified",
            yaxis=dict(title="Sales (₹)"), yaxis2=dict(title="Orders", overlaying="y", side="right", showgrid=False),
            legend=dict(orientation="h", y=1.12), margin=dict(t=60, l=10, r=10, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    a, b = st.columns(2)
    with a:
        x = group(f, "Last Channel").head(10)
        st.plotly_chart(hbar(x, "Sales", "Last Channel", "Top channels by sales"), use_container_width=True)
    with b:
        x = group(f, "Region").head(10)
        st.plotly_chart(hbar(x, "Sales", "Region", "Top regions by sales"), use_container_width=True)

# ================= ATTRIBUTION =================
with tabs[1]:
    st.subheader("First-click vs. last-click")
    a, b = st.columns(2)
    with a:
        x = group(f, "First Channel").head(15)
        st.plotly_chart(hbar(x, "Sales", "First Channel", "First-click — sales by channel"), use_container_width=True)
    with b:
        x = group(f, "Last Channel").head(15)
        st.plotly_chart(hbar(x, "Sales", "Last Channel", "Last-click — sales by channel"), use_container_width=True)

    a, b = st.columns(2)
    with a:
        x = group(f, "First Channel").head(15)
        st.plotly_chart(hbar(x, "Orders", "First Channel", "First-click — orders by channel"), use_container_width=True)
    with b:
        x = group(f, "Last Channel").head(15)
        st.plotly_chart(hbar(x, "Orders", "Last Channel", "Last-click — orders by channel"), use_container_width=True)

    st.subheader("Meta drill-down (Facebook vs. Instagram)")
    meta = f[f["Last Channel"] == "Meta"]
    if not meta.empty:
        x = group(meta, "Last Channel Detail")
        st.plotly_chart(hbar(x, "Sales", "Last Channel Detail", "Meta: Facebook vs Instagram vs other Meta"), use_container_width=True)
    else:
        st.info("No Meta-attributed orders in the current filter.")

    first = group(f, "First Channel").rename(columns={"First Channel": "Channel", "Orders": "First Orders", "Sales": "First Sales"})
    last = group(f, "Last Channel").rename(columns={"Last Channel": "Channel", "Orders": "Last Orders", "Sales": "Last Sales"})
    comp = first[["Channel", "First Orders", "First Sales"]].merge(
        last[["Channel", "Last Orders", "Last Sales"]], on="Channel", how="outer"
    ).fillna(0)
    comp["Sales Shift"] = comp["Last Sales"] - comp["First Sales"]
    st.subheader("Sales shift between first and last click")
    st.dataframe(
        comp.sort_values("Last Sales", ascending=False).style.format({
            "First Sales": "₹{:,.0f}", "Last Sales": "₹{:,.0f}", "Sales Shift": "₹{:,.0f}",
            "First Orders": "{:,.0f}", "Last Orders": "{:,.0f}",
        }),
        use_container_width=True, hide_index=True,
    )

# ================= GEOGRAPHY =================
with tabs[2]:
    a, b = st.columns(2)
    with a:
        x = group(f, "Region").head(20)
        st.plotly_chart(hbar(x, "Sales", "Region", "Regional sales"), use_container_width=True)
    with b:
        x = group(f, "City").head(20)
        st.plotly_chart(hbar(x, "Sales", "City", "Top cities by sales"), use_container_width=True)

    a, b = st.columns(2)
    with a:
        x = group(f, "Region").sort_values("AOV", ascending=False).head(15)
        st.plotly_chart(hbar(x, "AOV", "Region", "Regional AOV"), use_container_width=True)
    with b:
        x = group(f, "Region").head(8)
        fig = px.pie(x, names="Region", values="Sales", hole=0.55, title="Regional sales share (top 8)")
        fig.update_layout(template=TEMPLATE, margin=dict(t=50, l=10, r=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Regional detail")
    st.dataframe(
        group(f, "Region").style.format({"Sales": "₹{:,.0f}", "AOV": "₹{:,.0f}", "Sales Share": "{:.1f}%"}),
        use_container_width=True, hide_index=True,
    )

    st.divider()
    st.subheader("Paid-only revenue by region & city")
    st.caption("Only orders carrying a UTM campaign tag (i.e. traceable to a paid campaign) — everything else is excluded here.")
    paid_geo = f[f["Is Paid"]]
    if len(paid_geo):
        pa, pb = st.columns(2)
        with pa:
            x = group(paid_geo, "Region").head(15)
            st.plotly_chart(hbar(x, "Sales", "Region", "Paid sales by region"), use_container_width=True)
        with pb:
            x = group(paid_geo, "City").head(15)
            st.plotly_chart(hbar(x, "Sales", "City", "Paid sales by city"), use_container_width=True)
        st.dataframe(
            group(paid_geo, "Region").style.format({"Sales": "₹{:,.0f}", "AOV": "₹{:,.0f}", "Sales Share": "{:.1f}%"}),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No UTM-tagged (paid) orders in the current filter.")

# ================= INSIGHTS =================
with tabs[3]:
    st.subheader("Automated insights")
    insights = []
    ch = group(f, "Last Channel")
    if len(ch):
        top = ch.iloc[0]
        insights.append(f"**Top channel:** {top['Last Channel']} generated {int(top['Orders']):,} orders and {money(top['Sales'])} ({top['Sales Share']:.1f}% of sales).")
        top3_share = ch.head(3)["Sales Share"].sum()
        insights.append(f"**Channel concentration:** the top 3 channels ({', '.join(ch.head(3)['Last Channel'])}) account for {top3_share:.1f}% of total sales.")

    meta = f[f["Last Channel"] == "Meta"]
    if len(meta):
        md = group(meta, "Last Channel Detail")
        if len(md):
            insights.append(f"**Meta split:** {md.iloc[0]['Last Channel Detail']} leads Meta with {money(md.iloc[0]['Sales'])} in sales.")

    reg = group(f, "Region")
    if len(reg):
        r = reg.iloc[0]
        insights.append(f"**Top geographic market (total revenue):** {r['Region']} contributes {r['Sales Share']:.1f}% of sales with {money(r['AOV'])} AOV.")

    paid = f[f["Is Paid"]]
    if len(paid):
        preg = group(paid, "Region")
        if len(preg):
            pr = preg.iloc[0]
            insights.append(f"**Top geographic market (paid revenue):** {pr['Region']} leads on UTM-tracked paid campaign revenue with {money(pr['Sales'])} from {int(pr['Orders']):,} orders.")

    camp = group(f, "UTM Campaign")
    camp = camp[camp["UTM Campaign"] != "Missing"]
    if len(camp):
        c = camp.iloc[0]
        insights.append(f"**Best tracked campaign:** {c['UTM Campaign']} generated {money(c['Sales'])} from {int(c['Orders']):,} orders.")

    utm_cov = pct((f["UTM Campaign"] != "Missing").sum(), orders)
    insights.append(f"**UTM coverage:** {utm_cov:.1f}% of orders carry a UTM campaign tag; the rest rely on channel-level attribution only.")

    if f["Day"].notna().any():
        daily = f.dropna(subset=["Day"]).groupby("Day").agg(Orders=("Sales", "size"), Sales=("Sales", "sum")).reset_index()
        if len(daily):
            p = daily.loc[daily["Sales"].idxmax()]
            insights.append(f"**Peak sales day:** {p['Day'].strftime('%d %b %Y')} with {money(p['Sales'])} across {int(p['Orders']):,} orders.")

    for i in insights:
        st.markdown(f'<div class="card">{i}</div>', unsafe_allow_html=True)

    st.subheader("Campaign opportunity table")
    st.caption("Channels driving real revenue without a UTM campaign tag — the untracked share is revenue you can't yet attribute to a specific campaign.")
    paid_like = f[f["Last Channel Raw"].str.lower().apply(lambda s: any(h in s for h in PAID_CHANNEL_HINTS))]
    if len(paid_like):
        opp = paid_like.groupby("Last Channel").agg(
            Orders=("Sales", "size"), Sales=("Sales", "sum"),
        ).reset_index()
        untracked = paid_like[paid_like["UTM Campaign"] == "Missing"].groupby("Last Channel").agg(
            **{"Untracked Orders": ("Sales", "size"), "Untracked Sales": ("Sales", "sum")}
        ).reset_index()
        opp = opp.merge(untracked, on="Last Channel", how="left").fillna(0)
        opp["Untracked %"] = opp["Untracked Sales"] / opp["Sales"] * 100
        opp = opp.sort_values("Untracked Sales", ascending=False)

        def flag(p):
            cls = "opp-high" if p >= 60 else "opp-mid" if p >= 25 else "opp-low"
            return f'<span class="{cls}">{p:.0f}%</span>'

        opp_display = opp.copy()
        opp_display["Untracked %"] = opp_display["Untracked %"].apply(flag)
        for c in ["Sales", "Untracked Sales"]:
            opp_display[c] = opp_display[c].apply(money)
        st.write(opp_display.to_html(escape=False, index=False), unsafe_allow_html=True)
    else:
        st.info("No paid-style channels (Google, Meta, Bing) found in the current filter.")

# ================= DATA QUALITY =================
with tabs[4]:
    st.subheader("Attribution & tracking quality")
    a, b, c, d = st.columns(4)
    a.metric("First-click coverage", f"{pct((f['First Channel'] != 'Missing').sum(), orders):.1f}%")
    b.metric("Last-click coverage", f"{pct((f['Last Channel'] != 'Missing').sum(), orders):.1f}%")
    c.metric("UTM campaign coverage", f"{pct((f['UTM Campaign'] != 'Missing').sum(), orders):.1f}%")
    d.metric("Orders with notes", f"{pct(f['Has Notes'].sum(), orders):.1f}%")

    e, g = st.columns(2)
    e.metric("Region coverage", f"{pct((f['Region'] != 'Missing').sum(), orders):.1f}%")
    g.metric("City coverage", f"{pct((f['City'] != 'Missing').sum(), orders):.1f}%")

    st.info("Meta grouping: Facebook, FB, Instagram, IG, Insta and Meta variants are grouped into Meta for combined reporting, while the individual channel view lets you inspect Facebook and Instagram separately.")

# ================= ORDER EXPLORER =================
with tabs[5]:
    st.subheader("Order explorer")
    st.caption("Search the full order-level dataset and download exactly what you're looking at.")
    search = st.text_input("Search across all fields")
    view = f.copy()
    if search:
        mask = view.astype(str).apply(lambda s: s.str.contains(search, case=False, na=False)).any(axis=1)
        view = view[mask]
    st.caption(f"{len(view):,} orders match the current filters and search.")
    st.dataframe(view, use_container_width=True, hide_index=True)
    st.download_button("Download filtered CSV", view.to_csv(index=False).encode("utf-8"), "orders_filtered.csv", "text/csv")
