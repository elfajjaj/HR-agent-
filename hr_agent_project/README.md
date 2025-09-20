
# HR Agent (Chat-Only)

A tiny command-line assistant for recruiters.

## How to Run

```bash
cd "/mnt/data/hr_agent_project"
python hr_agent.py
```

Type commands and press Enter. Type **Quit** to exit.

## Seed Prompts (copy/paste)

- Find top 5 React interns in Casablanca, 0–2 years, available this month
- Save #1 #3 as "FE-Intern-A"
- Draft an outreach email for "FE-Intern-A" using job "Frontend Intern" in friendly tone
- Change the subject to "Quick chat about a Frontend Intern role?" and re-preview
- Show analytics

## Data

Edit `data/candidates.json` and `data/jobs.json`. A `data/shortlists.json` is created on save.

## Screenshot (console preview)

```
Subject: Quick chat about a Frontend Intern opportunity?
----- HTML PREVIEW BEGIN -----
<html> ... (trimmed) ... </html>
----- HTML PREVIEW END -----
```

## Minimal Scoring

- +2 per required skill match
- +1 if location exact match
- +1 if experience within user range (±1 year ok)
- +1 if availabilityDate within next 45 days (or window from your query)
