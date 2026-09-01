# Daily Orders Command Center

Run in VS Code:
```powershell
py -m pip install -r requirements.txt
py -m streamlit run app.py
```

Drop a fresh export into `data/orders.csv` (same column headers as before) any time you
want to refresh the numbers — the app re-reads it automatically.

## What's in it

**Overview** — total orders, total sales, AOV, attribution rate, a combined sales/orders
trend, top channels, top regions.

**Attribution** — first-click vs. last-click by sales and by orders, a Facebook/Instagram
drill-down inside Meta, and a sales-shift table comparing first- to last-click.

**Geography** — regional sales, top cities, regional AOV, regional sales share, and a
dedicated **paid-only** breakdown (region + city) limited to orders that carry a UTM
campaign tag.

**Insights** — auto-generated read of the current filter: top channel, channel
concentration (top-3 share), top geographic market by total revenue, top geographic
market by *paid* (UTM-tracked) revenue, best-tracked campaign, UTM coverage, peak sales
day, and a campaign opportunity table that flags paid-style channels (Google, Meta,
Bing) with high untracked revenue — i.e. where adding UTM tags would recover
attribution.

**Data Quality** — first-click, last-click, UTM, notes, region and city coverage.

**Order Explorer** — search every column, then download exactly what's on screen.

All source columns are preserved throughout — nothing is dropped, only enriched with
normalized Region/City/Channel/UTM fields for analysis.

## Connecting a live Google Sheet

Instead of dropping a fresh CSV into `data/orders.csv` every day, you can point the app
straight at a Google Sheet so it updates on its own:

1. In the Sheet: **File → Share → Publish to web**.
2. Under "Link", pick the specific tab that holds your order data (not "Entire
   document"). Under "Embed", choose **CSV**.
3. Click **Publish**, then copy the link — it ends in `...pub?output=csv`.
4. Open the app, expand **🔄 Live spreadsheet source** in the sidebar, and paste the
   link into "Google Sheet CSV link".
5. Set how often it should refresh with the slider (15s–5min). It'll then pull the
   latest data on its own — no restart needed. Use "Refresh now" to force an immediate
   pull.

To avoid pasting the link every time you restart the app, save it permanently instead:
create `.streamlit/secrets.toml` next to `app.py` with:
```toml
data_source_url = "https://docs.google.com/.../pub?output=csv"
```

**Note:** "Publish to web" makes that sheet viewable by anyone with the link (read-only,
not editable). Don't publish a sheet that has data you'd rather keep private — if that's
a concern, keep using the local CSV drop-in instead.

