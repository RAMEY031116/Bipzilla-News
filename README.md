# Daily News Brief

A one-page Streamlit news app with a simple news-site layout.

## What it does
- Shows short but more useful story summaries, not just bare headlines
- Keeps Health & Fitness shorter so it is quicker to scan
- Includes Top Stories, Politics, Finance, Tech, Cybersecurity, Science, Arts, Movies & TV, and Anime & Manga
- Includes London weather
- Includes an anime calendar block
- Has a dark and light theme toggle
- Uses a fixed logo file path so you can swap the logo easily

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Logo
A sample logo file is included already.

Use either of these:

```text
assets/logo.png
assets/sample_logo.png
```

To use your own logo later, replace `assets/logo.png` with your image file and refresh the app.

## Notes
- This version is built to stay mostly free using RSS feeds and public endpoints
- Some richer summaries are pulled from article pages, so the first load can be a bit slower
- The theme dropdown lets you switch between Dark and Light mode
