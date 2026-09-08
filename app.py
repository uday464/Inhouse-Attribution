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
SESSION_DATA_FILE = Path(__file__).parent / "data" / "sessions_by_landing_page_type.csv"

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

    d["UTM Campaign"] = safe_col("UTM campaign name").fillna("Missing").astype(str).str.strip().replace("", "Missing")
    if "Order UTM campaign" in d.columns:
        fallback = d["Order UTM campaign"].fillna("Missing").astype(str).str.strip().replace("", "Missing")
        d["UTM Campaign"] = d["UTM Campaign"].where(d["UTM Campaign"] != "Missing", fallback)

    d["UTM Source"] = safe_col("UTM source").fillna("Missing").replace("", "Missing")
    d["UTM Medium"] = safe_col("UTM medium").fillna("Missing").replace("", "Missing")
    d["Notes"] = safe_col("Notes").fillna("").astype(str).str.strip()
    d["Found On"] = safe_col("Found on shopify or zoho").fillna("Missing").replace("", "Missing")

    return d


def normalize_campaign_name(value):
    """Standardize campaign names for display and grouping without discarding the raw value."""
    if pd.isna(value):
        return "Missing"
    raw = str(value).strip()
    if not raw:
        return "Missing"
    # Collapse common separators/case variants while preserving meaningful IDs and dates.
    cleaned = raw.replace("+", " ")
    cleaned = cleaned.replace("_", " ").replace("-", " ")
    cleaned = " ".join(cleaned.split())
    # Human-readable casing for word-like campaigns, but keep digit-heavy IDs intact.
    if any(ch.isdigit() for ch in cleaned):
        words = []
        for token in cleaned.split():
            if token.isupper() or any(ch.isdigit() for ch in token):
                words.append(token)
            else:
                words.append(token.capitalize())
        return " ".join(words)
    return cleaned.title()


def standardize_campaign_series(series):
    raw = series.fillna("Missing").astype(str).str.strip().replace("", "Missing")
    # Canonical key removes common separators and case, then the most frequent raw value
    # is rendered in a readable standardized form.
    key = (raw.str.lower().str.replace(r"[+_\-|]", "", regex=True).str.replace(r"\s+", "", regex=True))
    named = raw[raw != "Missing"]
    display_map = {}
    if len(named):
        frame = pd.DataFrame({"raw": named, "key": key.loc[named.index]})
        most_common = frame.groupby("key")["raw"].agg(lambda x: x.value_counts().idxmax())
        display_map = {k: normalize_campaign_name(v) for k, v in most_common.items()}
    return key.map(display_map).fillna("Missing")


@st.cache_data(ttl=600)
def load_session_data(source):
    s = pd.read_csv(source)
    s.columns = [str(c).strip() for c in s.columns]
    required = {
        "Landing page type", "Landing page path", "Sessions", "Pageviews",
        "Sessions that completed checkout", "Sessions that reached checkout",
        "Sessions with cart additions",
    }
    missing = sorted(required - set(s.columns))
    if missing:
        raise ValueError(f"Session CSV is missing required columns: {', '.join(missing)}")
    for c in [
        "Sessions", "Pageviews", "Sessions that completed checkout",
        "Sessions that reached checkout", "Sessions with cart additions",
    ]:
        s[c] = pd.to_numeric(s[c], errors="coerce").fillna(0)
    if "Conversion rate" in s.columns:
        s["Conversion rate"] = pd.to_numeric(s["Conversion rate"], errors="coerce").fillna(0)
    for c in ["UTM source", "UTM campaign", "Referrer source", "Landing page type", "Landing page path"]:
        if c in s.columns:
            s[c] = s[c].fillna("Missing").astype(str).str.strip().replace("", "Missing")
    if "UTM campaign" in s.columns:
        s["Campaign"] = standardize_campaign_series(s["UTM campaign"])
    else:
        s["Campaign"] = "Missing"
    return s


def infer_session_window(path):
    # The supplied export filename contains its reporting window. This is used only
    # for the light order/session comparison and never changes either source dataset.
    import re
    name = Path(str(path)).name
    m = re.search(r"(\d{4}-\d{2}-\d{2}).*?(\d{4}-\d{2}-\d{2})", name)
    if not m:
        return None, None
    try:
        return pd.Timestamp(m.group(1)), pd.Timestamp(m.group(2))
    except Exception:
        return None, None


def page_label(path):
    if path == "Missing" or pd.isna(path):
        return "Missing"
    raw = str(path).strip().strip("/")
    if "/products/" in raw:
        slug = raw.split("/products/", 1)[1]
    elif "/collections/" in raw:
        slug = raw.split("/collections/", 1)[1]
    else:
        slug = raw.split("/")[-1]
    slug = slug.split("?", 1)[0]
    return slug.replace("-", " ").replace("_", " ").title()


def session_rollup(data, group_col):
    x = data.groupby(group_col).agg(
        Sessions=("Sessions", "sum"),
        Pageviews=("Pageviews", "sum"),
        Cart_Additions=("Sessions with cart additions", "sum"),
        Checkout_Reached=("Sessions that reached checkout", "sum"),
        Completed=("Sessions that completed checkout", "sum"),
    ).reset_index()
    x["Cart Rate"] = x["Cart_Additions"] / x["Sessions"].replace(0, np.nan) * 100
    x["Checkout Rate"] = x["Checkout_Reached"] / x["Cart_Additions"].replace(0, np.nan) * 100
    x["Completion Rate"] = x["Completed"] / x["Checkout_Reached"].replace(0, np.nan) * 100
    x["Session CVR"] = x["Completed"] / x["Sessions"].replace(0, np.nan) * 100
    x = x.fillna(0)
    return x


PERCENT_METRICS = {"Session CVR", "Cart Rate", "Checkout Rate", "Completion Rate"}


def ranked_chart(data, metric, title):
    # Bug fix 1: this previously plotted the raw float straight from the dataframe
    # as the bar label (e.g. "0.285442435775452" for a 0.29% conversion rate),
    # with no % sign and no rounding — technically the right number, but
    # unreadable and easy to mistake for a wrong one. Now formatted per metric
    # type, and the x-axis is pinned to start at 0 so Plotly doesn't auto-pad
    # a symmetric range (e.g. -1..1) around a cluster of near-zero values.
    # Bug fix 2: rows with a metric of exactly 0 (e.g. a "worst performers"
    # list where nothing converted) produce a zero-length bar. Plotly's default
    # text placement tries to fit the label *inside* the bar, and a zero-length
    # bar has no inside to put it in, so the label silently disappears. Forcing
    # textposition="outside" prints the label just past the bar's end instead,
    # so "0.00%" rows are still labeled.
    chart = data.copy()
    chart["Name"] = chart["Name"].astype(str).str.slice(0, 42)
    chart = chart.sort_values(metric)
    is_pct = metric in PERCENT_METRICS
    figp = px.bar(
        chart, x=metric, y="Name", orientation="h",
        title=title, text=metric,
    )
    if is_pct:
        figp.update_traces(texttemplate="%{x:.2f}%")
        figp.update_xaxes(ticksuffix="%")
    else:
        figp.update_traces(texttemplate="%{x:,.0f}")
    figp.update_traces(textposition="outside", cliponaxis=False)
    figp.update_layout(template=TEMPLATE, margin=dict(t=55, l=10, r=60, b=10), showlegend=False)
    max_val = chart[metric].max() if len(chart) else 0
    # Even an all-zero chart needs a non-zero range, or the outside label for
    # every 0-length bar has nowhere to sit and gets clipped at the axis edge.
    figp.update_xaxes(range=[0, max_val * 1.15 if max_val > 0 else 1])
    return figp


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

with st.sidebar.expander("📊 Web-session funnel source", expanded=False):
    st.caption("Separate from the order dataset. Expected columns: landing page, UTM campaign, sessions, carts, checkout reached, completed checkout.")
    session_upload = st.file_uploader("Session CSV", type=["csv"], key="session_csv_upload")
    st.caption("The bundled session export is loaded by default; uploading here replaces only this separate analysis.")

data_source = sheet_url.strip() if sheet_url.strip() else DATA_FILE
refresh_bucket = int(time.time() // refresh_secs)
df = load_data(data_source, refresh_bucket)
if session_upload is not None:
    try:
        session_df = load_session_data(session_upload)
        session_source_label = session_upload.name
        session_source_path = session_upload.name
    except Exception as e:
        session_df = None
        session_source_label = "Invalid uploaded session CSV"
        session_source_path = ""
        st.sidebar.error(str(e))
else:
    session_df = load_session_data(SESSION_DATA_FILE)
    session_source_label = SESSION_DATA_FILE.name
    session_source_path = str(SESSION_DATA_FILE)
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

# Campaign name normalization: the sheet has case-only duplicates
# ("LightingShopping_..." vs "lightingshopping_...") that silently fragment
# a single campaign's performance into two rows. Group by a lowercased key
# and display the most common original casing, so campaign-level reporting
# (below, and the funnel view) isn't split across case variants.
df["Campaign"] = standardize_campaign_series(df["UTM Campaign"])

# Optional override: if the sheet already has a real funnel-stage column
# (from your ad platforms), use it directly per campaign instead of guessing.
_funnel_col = next((c for c in df.columns if "funnel" in str(c).lower() and c != "Campaign"), None)

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


TIER_ORDER = ["Top Funnel", "Middle Funnel", "Bottom Funnel"]
TIER_COLORS = {"Top Funnel": "#3D6EB0", "Middle Funnel": "#E0A72E", "Bottom Funnel": "#0F6B4C"}


def classify_funnel(data, metric="Orders", high_is_bottom=True, funnel_col=None):
    """Campaign-level funnel tiering.

    We don't have ad-platform funnel-stage or impression/click data — only
    converted orders — so this is a heuristic, not a measured funnel:
      1. Any campaign already flagged as "Funnel Stage" (etc.) in the sheet
         is trusted as-is.
      2. Any remaining campaign with "demand gen" in its name is forced to
         Top Funnel — Google Demand Gen is an awareness/discovery ad format
         by design, regardless of its order volume.
      3. Everything else is ranked by the chosen volume metric and split
         into three equal-sized groups. High-volume, repeatable campaigns
         are assumed to be lower-funnel (branded search / retargeting keep
         converting the same warm demand); low-volume ones are assumed
         upper-funnel (broad/prospecting, still earning trust). Flip the
         toggle in the UI if that assumption doesn't match your account.
    """
    camp = data[data["Campaign"] != "Missing"]
    if not len(camp):
        return pd.DataFrame(columns=["Campaign", "Orders", "Sales", "AOV", "Tier", "Tier Source"])

    g = camp.groupby("Campaign").agg(Orders=("Sales", "size"), Sales=("Sales", "sum")).reset_index()
    g["AOV"] = g["Sales"] / g["Orders"].replace(0, np.nan)
    g["Tier"] = pd.NA
    g["Tier Source"] = "Heuristic (volume)"

    if funnel_col:
        real = camp[camp[funnel_col].notna() & (camp[funnel_col].astype(str).str.strip() != "")]
        if len(real):
            real_tier = real.groupby("Campaign")[funnel_col].agg(lambda s: s.value_counts().idxmax())
            g.loc[g["Campaign"].isin(real_tier.index), "Tier"] = g["Campaign"].map(real_tier)
            g.loc[g["Campaign"].isin(real_tier.index), "Tier Source"] = "From sheet"

    is_demand_gen = g["Campaign"].str.lower().str.contains("demand gen|demandgen", regex=True) & g["Tier"].isna()
    g.loc[is_demand_gen, "Tier"] = "Top Funnel"
    g.loc[is_demand_gen, "Tier Source"] = "Forced (Demand Gen)"

    rest_mask = g["Tier"].isna()
    rest = g[rest_mask].sort_values(metric, ascending=False)
    if len(rest):
        buckets = np.array_split(rest.index, 3)  # high -> low volume, 3 equal-ish groups
        high_label, low_label = ("Bottom Funnel", "Top Funnel") if high_is_bottom else ("Top Funnel", "Bottom Funnel")
        for idx in buckets[0]:
            g.loc[idx, "Tier"] = high_label
        for idx in buckets[1]:
            g.loc[idx, "Tier"] = "Middle Funnel"
        for idx in buckets[2]:
            g.loc[idx, "Tier"] = low_label

    g["Sales Share"] = g["Sales"] / g["Sales"].sum() * 100 if g["Sales"].sum() else 0
    return g.sort_values("Sales", ascending=False)


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

tabs = st.tabs(["Overview", "Attribution", "Geography", "Campaigns", "Insights", "Data Quality", "Order Explorer", "Session Funnel"])

# ================= OVERVIEW =================
with tabs[0]:
    if f["Day"].notna().any():
        max_day = f["Day"].max()
        this_week = f[f["Day"] > max_day - pd.Timedelta(days=7)]
        last_week = f[(f["Day"] <= max_day - pd.Timedelta(days=7)) & (f["Day"] > max_day - pd.Timedelta(days=14))]
        if len(last_week):
            st.caption(f"Last 7 days (through {max_day.strftime('%d %b')}) vs. the 7 days before that")
            w1, w2, w3 = st.columns(3)
            tw_orders, lw_orders = len(this_week), len(last_week)
            tw_sales, lw_sales = this_week["Sales"].sum(), last_week["Sales"].sum()
            tw_aov = tw_sales / tw_orders if tw_orders else 0
            lw_aov = lw_sales / lw_orders if lw_orders else 0
            w1.metric("Orders (7d)", f"{tw_orders:,}", f"{tw_orders - lw_orders:+,} vs prior 7d")
            w2.metric("Sales (7d)", money_compact(tw_sales), f"{pct(tw_sales - lw_sales, lw_sales):+.1f}% vs prior 7d" if lw_sales else None)
            w3.metric("AOV (7d)", money_compact(tw_aov), f"{pct(tw_aov - lw_aov, lw_aov):+.1f}% vs prior 7d" if lw_aov else None)
            st.divider()

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

# ================= CAMPAIGNS =================
with tabs[3]:
    st.subheader("Campaign funnel")
    st.caption(
        "Orders don't carry ad-platform funnel-stage data (impressions, clicks, or a declared "
        "objective), so tiers below are inferred, not measured. Demand Gen campaigns are always "
        "treated as Top Funnel by ad-format definition; everything else is ranked by volume."
    )

    cc1, cc2 = st.columns(2)
    with cc1:
        rank_metric = st.radio("Rank remaining campaigns by", ["Orders", "Sales"], horizontal=True)
    with cc2:
        volume_assumption = st.selectbox(
            "Assume high-volume campaigns are",
            ["Bottom Funnel (branded search / retargeting — repeatedly closes warm demand)",
             "Top Funnel (broad prospecting / awareness at scale)"],
        )
    high_is_bottom = volume_assumption.startswith("Bottom")

    camp_stats = classify_funnel(f, metric=rank_metric, high_is_bottom=high_is_bottom, funnel_col=_funnel_col)

    if _funnel_col:
        st.success(f"Found a '{_funnel_col}' column in your sheet — using it wherever a campaign has a value, and only falling back to the heuristic where it's blank.")

    if len(camp_stats):
        tier_summary = camp_stats.groupby("Tier").agg(
            Campaigns=("Campaign", "nunique"), Orders=("Orders", "sum"), Sales=("Sales", "sum")
        ).reindex(TIER_ORDER).fillna(0)

        k1, k2, k3 = st.columns(3)
        for col, tier in zip([k1, k2, k3], TIER_ORDER):
            row = tier_summary.loc[tier]
            col.metric(tier, money_compact(row["Sales"]), f"{int(row['Campaigns'])} campaigns · {int(row['Orders']):,} orders")

        # Plotly's funnel shape only reads cleanly when values shrink from top
        # to bottom. Our tiers aren't sequential stages of one journey, so we
        # order the visual by sales size (largest first) rather than by
        # TIER_ORDER — otherwise a small Top-Funnel value above a huge
        # Bottom-Funnel one draws an inverted, broken-looking shape.
        funnel_order = tier_summary.sort_values("Sales", ascending=False).index.tolist()
        funnel_sales = [tier_summary.loc[t, "Sales"] for t in funnel_order]
        st.caption("Ordered by sales size (largest tier first) so the shape reads as a proper funnel — not by Top→Bottom label order.")
        fig = go.Figure(go.Funnel(
            y=funnel_order,
            x=funnel_sales,
            textposition="inside",
            textinfo="text",
            text=[f"<b>{money_compact(v)}</b><br>{v/funnel_sales[0]*100:.0f}% of largest tier" for v in funnel_sales],
            textfont=dict(color="white", size=16, family="Manrope"),
            marker=dict(color=[TIER_COLORS[t] for t in funnel_order], line=dict(width=1, color="white")),
            connector=dict(line=dict(color="#C9D4CE", width=1)),
        ))
        fig.update_layout(
            template=TEMPLATE, title="Sales by funnel tier", showlegend=False,
            margin=dict(t=50, l=10, r=10, b=10), font=dict(family="Manrope"),
        )
        st.plotly_chart(fig, use_container_width=True)

        if f["Day"].notna().any():
            trend_src = f[f["Campaign"] != "Missing"].dropna(subset=["Day"]).merge(
                camp_stats[["Campaign", "Tier"]], on="Campaign", how="left"
            )
            if len(trend_src):
                weekly = (
                    trend_src.assign(Week=trend_src["Day"].dt.to_period("W").apply(lambda p: p.start_time))
                    .groupby(["Week", "Tier"]).agg(Sales=("Sales", "sum")).reset_index()
                )
                fig2 = px.area(
                    weekly, x="Week", y="Sales", color="Tier", category_orders={"Tier": TIER_ORDER},
                    color_discrete_map=TIER_COLORS, title="Weekly sales by funnel tier",
                )
                fig2.update_layout(template=TEMPLATE, margin=dict(t=50, l=10, r=10, b=10))
                st.plotly_chart(fig2, use_container_width=True)

        st.subheader("Campaign-level detail")

        def tier_badge(t):
            cls = {"Top Funnel": "opp-mid", "Middle Funnel": "opp-mid", "Bottom Funnel": "opp-low"}.get(t, "")
            return f'<span class="{cls}">{t}</span>'

        disp = camp_stats.copy()
        disp["Tier"] = disp["Tier"].apply(tier_badge)
        for c in ["Sales", "AOV"]:
            disp[c] = disp[c].apply(money)
        disp["Sales Share"] = disp["Sales Share"].map("{:.1f}%".format)
        st.write(
            disp[["Campaign", "Tier", "Tier Source", "Orders", "Sales", "AOV", "Sales Share"]].to_html(escape=False, index=False),
            unsafe_allow_html=True,
        )
    else:
        st.info("No UTM-tagged campaigns in the current filter.")

# ================= INSIGHTS =================
with tabs[4]:
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

    if f["Day"].notna().any():
        st.subheader("Day-of-week pattern")
        st.caption("Average sales and orders per weekday across the whole date range — useful for staffing, ad-scheduling, and spotting slow days.")
        dow = f.dropna(subset=["Day"]).copy()
        dow["Weekday"] = dow["Day"].dt.day_name()
        weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        n_weeks = max((dow["Day"].max() - dow["Day"].min()).days / 7, 1)
        dsum = dow.groupby("Weekday").agg(Orders=("Sales", "size"), Sales=("Sales", "sum")).reindex(weekday_order).fillna(0)
        dsum["Avg Orders/Day"] = dsum["Orders"] / n_weeks
        dsum["Avg Sales/Day"] = dsum["Sales"] / n_weeks
        fig_dow = px.bar(dsum.reset_index(), x="Weekday", y="Avg Sales/Day", title="Average sales by day of week")
        fig_dow.update_layout(template=TEMPLATE, margin=dict(t=50, l=10, r=10, b=10))
        st.plotly_chart(fig_dow, use_container_width=True)

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
with tabs[5]:
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
with tabs[6]:
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

# ================= SESSION FUNNEL =================
with tabs[7]:
    st.subheader("Web-session funnel")
    st.caption(
        "A separate view for the landing-page session export. It is intentionally not merged into the order-level "
        "dataset above: sessions describe visits, while the order sheet describes completed orders and sales."
    )
    session_source_rows = len(session_df) if session_df is not None else 0
    st.caption(f"Session source: {session_source_label} · {session_source_rows:,} source rows")

    if session_df is None or session_df.empty:
        st.info("Upload a valid session CSV in the sidebar to use this section.")
    else:
        total_sessions = session_df["Sessions"].sum()
        total_carts = session_df["Sessions with cart additions"].sum()
        total_checkout = session_df["Sessions that reached checkout"].sum()
        total_completed = session_df["Sessions that completed checkout"].sum()

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Sessions", f"{total_sessions:,.0f}")
        k2.metric("Cart additions", f"{total_carts:,.0f}", f"{pct(total_carts, total_sessions):.2f}% of sessions")
        k3.metric("Checkout reached", f"{total_checkout:,.0f}", f"{pct(total_checkout, total_carts):.1f}% of carts")
        k4.metric("Completed checkout", f"{total_completed:,.0f}", f"{pct(total_completed, total_checkout):.1f}% of checkout")

        # Real four-stage funnel from the provided session export.
        stage_names = ["Sessions", "Cart additions", "Checkout reached", "Completed checkout"]
        stage_values = [total_sessions, total_carts, total_checkout, total_completed]
        fig = go.Figure(go.Funnel(
            y=stage_names, x=stage_values, textposition="inside", textinfo="text",
            text=[f"<b>{v:,.0f}</b><br>{pct(v, stage_values[0]):.1f}% of sessions" for v in stage_values],
            textfont=dict(color="white", size=15, family="Manrope"),
            marker=dict(color=["#3D6EB0", "#5B8FC1", "#E0A72E", "#0F6B4C"], line=dict(width=1, color="white")),
            connector=dict(line=dict(color="#C9D4CE", width=1)),
        ))
        fig.update_layout(template=TEMPLATE, title="Session → cart → checkout → completed checkout",
                          showlegend=False, margin=dict(t=55, l=10, r=10, b=10), font=dict(family="Manrope"))
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Funnel stage leaders by campaign")
        campaign_roll = session_rollup(session_df[session_df["Campaign"] != "Missing"], "Campaign")
        if len(campaign_roll):
            c1, c2, c3 = st.columns(3)
            for col, title, metric, fmt in [
                (c1, "Top funnel — session volume", "Sessions", "{:,.0f}"),
                (c2, "Middle funnel — cart additions", "Cart_Additions", "{:,.0f}"),
                (c3, "Bottom funnel — completed checkout", "Completed", "{:,.0f}"),
            ]:
                top = campaign_roll.sort_values(metric, ascending=False).head(8).copy()
                top["Campaign"] = top["Campaign"].str.slice(0, 34)
                figc = px.bar(top.sort_values(metric), x=metric, y="Campaign", orientation="h", title=title, text=metric)
                figc.update_traces(texttemplate="%{x:,.0f}")
                figc.update_layout(template=TEMPLATE, margin=dict(t=55, l=10, r=10, b=10), showlegend=False)
                col.plotly_chart(figc, use_container_width=True)

            st.caption("These are stage leaders, not funnel-stage labels assigned to campaigns. A campaign can be strong at more than one stage.")

            compare_campaigns = st.multiselect(
                "Compare campaigns in one funnel",
                options=campaign_roll.sort_values("Sessions", ascending=False)["Campaign"].head(12).tolist(),
                default=campaign_roll.sort_values("Sessions", ascending=False)["Campaign"].head(3).tolist(),
            )
            if compare_campaigns:
                cmap = {
                    c: campaign_roll.loc[campaign_roll["Campaign"] == c].iloc[0] for c in compare_campaigns
                }
                fig_multi = go.Figure()
                for c in compare_campaigns:
                    row = cmap[c]
                    vals = [row["Sessions"], row["Cart_Additions"], row["Checkout_Reached"], row["Completed"]]
                    fig_multi.add_trace(go.Funnel(
                        name=c, y=stage_names, x=vals, textinfo="value+percent initial",
                        opacity=0.55, connector=dict(line=dict(color="#C9D4CE", width=1)),
                    ))
                fig_multi.update_layout(template=TEMPLATE, title="Campaign funnel comparison",
                                        margin=dict(t=55, l=10, r=10, b=10), font=dict(family="Manrope"))
                st.plotly_chart(fig_multi, use_container_width=True)

        st.divider()
        st.subheader("Top 10 & bottom 10 — collections")
        st.caption("Separate session-performance ranking for collection landing pages. Rankings use the session funnel only and do not alter the order dataset.")

        rank_metric = st.selectbox(
            "Rank collections by",
            ["Session CVR", "Completed", "Cart Rate", "Checkout Rate", "Sessions"],
            index=0,
            key="collection_rank_metric",
        )
        min_sessions = st.slider("Minimum sessions per collection", 0, 1000, 100, step=25, key="collection_min_sessions")
        cc1, cc2, cc3 = st.columns(3)
        with cc1:
            coll_min_cart = st.number_input("Minimum cart additions", min_value=0, value=0, step=1, key="collection_min_cart")
        with cc2:
            coll_min_checkout = st.number_input("Minimum checkout reached", min_value=0, value=0, step=1, key="collection_min_checkout")
        with cc3:
            coll_min_cvr = st.slider("Minimum conversion rate", 0.0, 100.0, 0.0, step=0.5, key="collection_min_cvr", format="%.1f%%")

        def rank_pages(page_type, metric, min_s, min_cart, min_checkout, min_cvr, key_prefix):
            subset = session_df[session_df["Landing page type"].str.lower().eq(page_type)]
            r = session_rollup(subset, "Landing page path")
            r = r[r["Sessions"] >= min_s]
            r = r[r["Cart_Additions"] >= min_cart]
            r = r[r["Checkout_Reached"] >= min_checkout]
            r = r[r["Session CVR"] >= min_cvr].copy()
            if r.empty:
                return r, r, r
            r["Name"] = r["Landing page path"].map(page_label)
            best = r.sort_values(metric, ascending=False).head(10).copy()
            worst = r.sort_values(metric, ascending=True).head(10).copy()
            return r, best, worst

        collections_all, collections_best, collections_worst = rank_pages(
            "collection", rank_metric, min_sessions, coll_min_cart, coll_min_checkout, coll_min_cvr, "collection"
        )
        if collections_all.empty:
            st.info("No collections meet the current minimum-session filter.")
        else:
            if len(collections_all) <= 10:
                st.caption(
                    f"Only {len(collections_all)} collections meet the {min_sessions}-session minimum, "
                    "so Top 10 and Bottom 10 show the same set (just ranked in opposite order). "
                    "Lower the minimum-sessions slider to widen the pool, or raise it to narrow to real standouts."
                )
            c1, c2 = st.columns(2)
            c1.plotly_chart(ranked_chart(collections_best, rank_metric, "Top 10 collections"), use_container_width=True)
            c2.plotly_chart(ranked_chart(collections_worst, rank_metric, "Bottom 10 collections"), use_container_width=True)

            view_cols = ["Name", "Sessions", "Cart_Additions", "Checkout_Reached", "Completed", "Cart Rate", "Checkout Rate", "Completion Rate", "Session CVR"]
            st.dataframe(
                collections_all.sort_values(rank_metric, ascending=False)[view_cols].style.format({
                    "Sessions": "{:,.0f}", "Cart_Additions": "{:,.0f}", "Checkout_Reached": "{:,.0f}", "Completed": "{:,.0f}",
                    "Cart Rate": "{:.2f}%", "Checkout Rate": "{:.1f}%", "Completion Rate": "{:.1f}%", "Session CVR": "{:.2f}%",
                }),
                use_container_width=True, hide_index=True,
            )

        st.divider()
        st.subheader("Top 10 & bottom 10 — products")
        st.caption("Separate product landing-page ranking from the same session export.")
        product_rank_metric = st.selectbox(
            "Rank products by",
            ["Session CVR", "Completed", "Cart Rate", "Checkout Rate", "Sessions"],
            index=0,
            key="product_rank_metric",
        )
        product_min_sessions = st.slider("Minimum sessions per product", 0, 1000, 100, step=25, key="product_min_sessions")
        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            prod_min_cart = st.number_input("Minimum cart additions", min_value=0, value=0, step=1, key="product_min_cart")
        with pc2:
            prod_min_checkout = st.number_input("Minimum checkout reached", min_value=0, value=0, step=1, key="product_min_checkout")
        with pc3:
            prod_min_cvr = st.slider("Minimum conversion rate", 0.0, 100.0, 0.0, step=0.5, key="product_min_cvr", format="%.1f%%")
        products_all, products_best, products_worst = rank_pages(
            "product", product_rank_metric, product_min_sessions, prod_min_cart, prod_min_checkout, prod_min_cvr, "product"
        )
        if products_all.empty:
            st.info("No products meet the current minimum-session filter.")
        else:
            if len(products_all) <= 10:
                st.caption(
                    f"Only {len(products_all)} products meet the {product_min_sessions}-session minimum, "
                    "so Top 10 and Bottom 10 show the same set (just ranked in opposite order)."
                )
            p1, p2 = st.columns(2)
            p1.plotly_chart(ranked_chart(products_best, product_rank_metric, "Top 10 products"), use_container_width=True)
            p2.plotly_chart(ranked_chart(products_worst, product_rank_metric, "Bottom 10 products"), use_container_width=True)
            pcols = ["Name", "Sessions", "Cart_Additions", "Checkout_Reached", "Completed", "Cart Rate", "Checkout Rate", "Completion Rate", "Session CVR"]
            st.dataframe(
                products_all.sort_values(product_rank_metric, ascending=False)[pcols].style.format({
                    "Sessions": "{:,.0f}", "Cart_Additions": "{:,.0f}", "Checkout_Reached": "{:,.0f}", "Completed": "{:,.0f}",
                    "Cart Rate": "{:.2f}%", "Checkout Rate": "{:.1f}%", "Completion Rate": "{:.1f}%", "Session CVR": "{:.2f}%",
                }),
                use_container_width=True, hide_index=True,
            )

        st.divider()
        st.subheader("Campaign performance — standardized names")
        st.caption("Campaign naming is normalized for display and grouping. The raw UTM campaign field remains available in the uploaded source and is not modified.")
        camp_filter = st.multiselect(
            "Campaigns to inspect",
            options=sorted([x for x in session_df["Campaign"].unique() if x != "Missing"]),
            key="session_campaign_filter",
        )
        camp_view = session_df.copy()
        if camp_filter:
            camp_view = camp_view[camp_view["Campaign"].isin(camp_filter)]
        campaign_filtered_roll = session_rollup(camp_view[camp_view["Campaign"] != "Missing"], "Campaign")
        if len(campaign_filtered_roll):
            st.dataframe(
                campaign_filtered_roll.sort_values("Sessions", ascending=False).style.format({
                    "Sessions": "{:,.0f}", "Pageviews": "{:,.0f}", "Cart_Additions": "{:,.0f}",
                    "Checkout_Reached": "{:,.0f}", "Completed": "{:,.0f}", "Cart Rate": "{:.2f}%",
                    "Checkout Rate": "{:.1f}%", "Completion Rate": "{:.1f}%", "Session CVR": "{:.2f}%",
                }), use_container_width=True, hide_index=True,
            )

        st.divider()
        st.subheader("Collection & product explorer")
        st.caption("A dedicated explorer for all landing-page collections and products. These filters affect only this session-data section.")
        e1, e2, e3, e4 = st.columns(4)
        with e1:
            explorer_type = st.multiselect(
                "Landing page type", ["Collection", "Product"], default=["Collection", "Product"], key="explorer_type"
            )
        with e2:
            explorer_campaign = st.multiselect(
                "Campaign", sorted([x for x in session_df["Campaign"].unique() if x != "Missing"]), key="explorer_campaign"
            )
        with e3:
            explorer_source = st.multiselect(
                "UTM source", sorted([x for x in session_df["UTM source"].unique() if x != "Missing"]), key="explorer_source"
            )
        with e4:
            explorer_referrer = st.multiselect(
                "Referrer source", sorted([x for x in session_df["Referrer source"].unique() if x != "Missing"]), key="explorer_referrer"
            )
        q1, q2 = st.columns(2)
        with q1:
            explorer_search = st.text_input("Search collection or product name", key="explorer_search", placeholder="e.g. lighting, vase, chandelier")
        with q2:
            explorer_min_sessions = st.number_input("Minimum sessions", min_value=0, value=0, step=25, key="explorer_min_sessions")

        st.caption("Performance filters — applied after the above, per landing page (product or collection).")
        r1, r2, r3 = st.columns(3)
        with r1:
            explorer_min_cart = st.number_input("Minimum cart additions", min_value=0, value=0, step=1, key="explorer_min_cart")
        with r2:
            explorer_min_checkout = st.number_input("Minimum checkout reached", min_value=0, value=0, step=1, key="explorer_min_checkout")
        with r3:
            explorer_min_cvr = st.slider("Minimum conversion rate (Session CVR)", 0.0, 100.0, 0.0, step=0.5, key="explorer_min_cvr", format="%.1f%%")
        st.caption(
            "Conversion rate on a low-session page can swing wildly (1 session that converts reads as 100%). "
            "Pair the conversion-rate filter with a minimum-sessions floor above for a meaningful cut."
        )

        ex = session_df.copy()
        if explorer_type:
            ex = ex[ex["Landing page type"].isin(explorer_type)]
        if explorer_campaign:
            ex = ex[ex["Campaign"].isin(explorer_campaign)]
        if explorer_source:
            ex = ex[ex["UTM source"].isin(explorer_source)]
        if explorer_referrer:
            ex = ex[ex["Referrer source"].isin(explorer_referrer)]
        ex_roll = session_rollup(ex, "Landing page path")
        if len(ex_roll):
            ex_roll["Type"] = ex_roll["Landing page path"].map(lambda p: "Product" if "/products/" in str(p) else "Collection" if "/collections/" in str(p) else "Other")
            ex_roll["Name"] = ex_roll["Landing page path"].map(page_label)
            ex_roll = ex_roll[ex_roll["Sessions"] >= explorer_min_sessions]
            ex_roll = ex_roll[ex_roll["Cart_Additions"] >= explorer_min_cart]
            ex_roll = ex_roll[ex_roll["Checkout_Reached"] >= explorer_min_checkout]
            ex_roll = ex_roll[ex_roll["Session CVR"] >= explorer_min_cvr]
            if explorer_search.strip():
                ex_roll = ex_roll[ex_roll["Name"].str.contains(explorer_search.strip(), case=False, na=False)]
            ex_roll = ex_roll.sort_values("Sessions", ascending=False)
        if len(ex_roll):
            st.caption(f"{len(ex_roll):,} landing pages match the explorer filters.")
            st.dataframe(
                ex_roll[["Type", "Name", "Sessions", "Pageviews", "Cart_Additions", "Checkout_Reached", "Completed", "Cart Rate", "Checkout Rate", "Completion Rate", "Session CVR"]].style.format({
                    "Sessions": "{:,.0f}", "Pageviews": "{:,.0f}", "Cart_Additions": "{:,.0f}", "Checkout_Reached": "{:,.0f}", "Completed": "{:,.0f}",
                    "Cart Rate": "{:.2f}%", "Checkout Rate": "{:.1f}%", "Completion Rate": "{:.1f}%", "Session CVR": "{:.2f}%",
                }), use_container_width=True, hide_index=True,
            )
            st.download_button("Download session landing-page view", ex_roll.to_csv(index=False).encode("utf-8"), "session_landing_pages_filtered.csv", "text/csv")
        else:
            st.info("No collection/product landing pages match the current explorer filters.")

        st.divider()
        st.subheader("Light comparison with the order dataset")
        start, end = infer_session_window(session_source_path)
        if start is not None and end is not None and "Day" in df.columns:
            o = df.copy()
            o = o[(o["Day"] >= start) & (o["Day"] <= end)]
            o = o[o["Campaign"] != "Missing"]
            order_roll = o.groupby("Campaign").agg(Orders=("Sales", "size"), Sales=("Sales", "sum")).reset_index()
            shared = campaign_roll.merge(order_roll, on="Campaign", how="inner")
            if len(shared):
                st.caption(f"Shared-campaign view for the session report window ({start.strftime('%d %b %Y')}–{end.strftime('%d %b %Y')}). This is directional only: session metrics are visit-level, while orders/sales are order-level and are not expected to reconcile 1:1.")
                shared["Session CVR"] = shared["Session CVR"] / 100
                st.dataframe(
                    shared.sort_values("Sales", ascending=False)[["Campaign", "Sessions", "Completed", "Session CVR", "Orders", "Sales"]].style.format({
                        "Sessions": "{:,.0f}", "Completed": "{:,.0f}", "Session CVR": "{:.2%}", "Orders": "{:,.0f}", "Sales": "₹{:,.0f}",
                    }), use_container_width=True, hide_index=True
                )
            else:
                st.info("No campaign names overlap cleanly between the session export and order dataset in the same reporting window, so the light comparison is omitted.")
        else:
            st.info("The session export has no embedded date column, so this comparison needs a reporting-window date in the filename (or a future dated session export). The two datasets remain separate regardless.")

