# Open Knowledge Pipeline

A distributed content collection pipeline for open knowledge aggregation.

## How It Works

This project runs scheduled workflows that collect and process publicly available
knowledge from various open sources. Content is rewritten and submitted to a
configured training pipeline.

## Sources

- Wikipedia (CC-BY-SA 4.0)
- Wikisource (CC-BY-SA / Public Domain)
- UN FAO (Free to use)
- Project Gutenberg (Public Domain)
- Stack Exchange (CC-BY-SA 4.0)
- MDN Web Docs (CC-BY-SA 4.0)
- GitHub Public Repositories

## Setup

Add the following secrets to GitHub Actions:
- `TRAINING_FORM_URL` — Target endpoint
- `SCRAPER_API_KEY` — Authentication key
- `GROQ_API_KEY` — AI generation API key
- `MISTRAL_API_KEY` — AI generation API key (fallback)
- `GH_TOKEN` — GitHub API token

## License

MIT
