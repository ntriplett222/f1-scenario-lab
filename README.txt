# F1 2026 Championship Scenario Lab — Live iPhone Build

This is the mobile-first version of the simulator with automatic post-race updates.

## What updates automatically

When the hosted app opens, it:

1. Loads `data/season-2026.json` from the same site if the GitHub Action has produced a newer snapshot.
2. Checks OpenF1 directly for the latest completed historical session and championship standings.
3. Locks newly completed Grands Prix/Sprints as actual results.
4. Clears only the simulation inputs for sessions that became actual.
5. Preserves all scenarios for future rounds.
6. Recalculates driver/constructor projections and title math.
7. Saves the newest successful live snapshot in browser storage for offline fallback.

The built-in offline fallback is seeded through the 2026 Spanish Grand Prix in Madrid on September 13, 2026.

## Recommended iPhone setup with GitHub Pages

Upload **the entire contents of this folder**, including `.github`, `data`, and `scripts`, to the root of your repository.

Then:

1. In GitHub, open **Settings → Pages**.
2. Under **Build and deployment**, choose **Deploy from a branch**.
3. Select `main` and `/ (root)`.
4. Open the GitHub Pages HTTPS address in Safari on your iPhone.
5. Tap **Share → Add to Home Screen**.

From then on, launch it from the Home Screen. It will check for new F1 data automatically.

## GitHub Action

`.github/workflows/update-f1-data.yml` runs:

- Every 2 hours on Thursday, Friday, Saturday and Sunday.
- Once each weekday morning.
- Any time you manually choose **Run workflow** in GitHub Actions.

It uses only Python's standard library and the free historical OpenF1 endpoints. If the standings have not changed, it does not create a commit.

## Live status colors

- **Green:** OpenF1 live/historical sync succeeded.
- **Amber:** using a cached or GitHub-generated snapshot.
- **Red:** live refresh failed and the built-in fallback is being used.
- **Blue:** refresh currently running.

## Files

- `index.html` — the dashboard.
- `data/season-2026.json` — cached canonical standings/result snapshot.
- `scripts/update_f1_data.py` — GitHub updater.
- `.github/workflows/update-f1-data.yml` — scheduled automation.

No backend server, npm install, API key, or build step is required.
