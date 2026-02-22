# Screenshot Capture Guide

## How to capture screenshots

1. Start the app: `docker compose up -d`
2. Open Chrome DevTools (`F12`)
3. Set viewport to **1280 x 800** (Device toolbar → Responsive → 1280 x 800)
4. Navigate to the relevant page
5. Use `Cmd+Shift+P` → "Capture full size screenshot" or crop to the relevant area
6. Save as PNG in this directory

## Required screenshots

| File | What to capture |
|------|-----------------|
| `dashboard.png` | Main dashboard with spending bar, CV loaded, analysis history |
| `analysis_result.png` | A completed analysis showing score, strengths, gaps |
| `cover_letter.png` | A generated cover letter with subject lines |

## Tips

- Use realistic data (not "test" placeholders)
- Ensure the dark theme renders cleanly
- Crop unnecessary browser chrome
- Aim for ~1280px width for consistency
