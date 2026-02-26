# Screenshot Capture Guide

## How to capture screenshots

1. Start the app: `docker compose up -d`
2. Open Chrome DevTools (`F12`)
3. Set viewport to **1280 x 800** (Device toolbar → Responsive → 1280 x 800)
4. Navigate to the relevant page
5. Use `Cmd+Shift+P` → "Capture full size screenshot" or crop to the relevant area
6. Save as PNG in this directory

## Required screenshots

| File | Page | What to capture |
|------|------|-----------------|
| `dashboard.png` | `/` | Dashboard with metric cards, follow-up alerts, recent analyses |
| `analyze.png` | `/analyze` | Analysis form with CV status, job description textarea, model selector |
| `analysis_result.png` | `/analysis/{id}` | Score ring, strengths/gaps columns, recommendation badge |
| `history.png` | `/history` | History page with 4 status tabs and job cards |
| `interviews.png` | `/interviews` | Upcoming interviews with prep scripts, past collapsed |
| `settings.png` | `/settings` | CV management card, API credit tracking |
| `cover_letter.png` | `/analysis/{id}` | Generated cover letter section within analysis detail |
| `login.png` | `/login` | Standalone login page (dark theme) |

## Tips

- Use realistic data (not "test" placeholders)
- Ensure the Apple dark theme renders cleanly (#0D0D0F background)
- Sidebar should be visible on all pages except login
- Crop unnecessary browser chrome
- Aim for ~1280px width for consistency
- For mobile screenshots, set viewport to 375 x 812 to show bottom bar
