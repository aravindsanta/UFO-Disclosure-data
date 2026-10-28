# UFO Disclosure — records index

Public index of officially released UAP (UFO) records used by the **UFO Disclosure** iOS app by Temagami Software Inc.

- **Index:** <https://aravindsanta.github.io/UFO-Disclosure-data/data/records.json>
- **Source:** the All-domain Anomaly Resolution Office (AARO) uploads on [DVIDS](https://www.dvidshub.net), covering the Department of War PURSUE releases. Each record links its original DVIDS page. Media files are U.S. Government works hosted by DVIDS; this repo stores metadata only.
- **Updates:** `.github/workflows/update-records.yml` rebuilds the index daily with `tools/build_records.py` and publishes it via GitHub Pages.

Not affiliated with or endorsed by the U.S. Department of War, AARO, or DVIDS.

## Run locally

```bash
DVIDS_API_KEY=... python3 tools/build_records.py   # writes data/records.json
```
