"""Peek at Betfair's free ANZ thoroughbred files (format check; saves nothing)."""
import io, sys, urllib.request, zipfile
import pandas as pd
BASE = "https://betfair-datascientists.github.io/data/assets/"
url = BASE + (sys.argv[1] if len(sys.argv) > 1 else "ANZ_Thoroughbreds_2026_10.csv")
raw = urllib.request.urlopen(url, timeout=120).read()
print("bytes:", len(raw))
if url.endswith(".zip"):
    z = zipfile.ZipFile(io.BytesIO(raw)); print("zip members:", [(i.filename, i.file_size) for i in z.infolist()][:20])
    raw = z.read(z.infolist()[0].filename)
df = pd.read_csv(io.BytesIO(raw), low_memory=False)
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 80); pd.set_option("display.max_colwidth", 40)
print("rows:", len(df)); print("columns:", list(df.columns)); print(df.dtypes.to_string())
print(df.head(4).T.to_string())
for c in df.columns:
    if df[c].dtype == object and df[c].nunique() < 40: print(c, "->", df[c].dropna().unique()[:40].tolist())
print("null share:", df.isna().mean().round(3).to_dict())
