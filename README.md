# Morning Brief (free Streamlit app)

A one-page Streamlit news app with a cleaner news-style layout and fuller story summaries.

## What it includes
- Top stories
- Politics
- Finance
- Tech
- Cybersecurity / data breaches
- Health & fitness
- Science
- Movies & TV
- Anime & manga
- Local weather
- Daily fact
- Logo placeholder that uses `assets/logo.png`

## Why this version is better
- Free to run
- No paid API needed for the main news feed
- Shows more detail than just headlines
- Keeps a simple one-page scroll layout
- Works well on mobile
- Easy to deploy on Streamlit Community Cloud

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Add your logo
Put your image file here:

```text
assets/logo.png
```

Then refresh the app.

## Notes
- Some stories use the RSS summary only.
- When the RSS snippet is too short, the app tries to pull a cleaner description from the article page.
- The anime calendar uses the Jikan API.
