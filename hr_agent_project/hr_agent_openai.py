import json
import re
import os
import requests
from datetime import datetime
from pathlib import Path
from collections import Counter
from dotenv import load_dotenv

# ---------- Environment Setup ----------
load_dotenv()
API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")  
MODEL = os.getenv("MODEL")       

# ---------- File Paths ----------
DATA_DIR = Path("data")
CAND_FILE = DATA_DIR / "candidates.json"
jobs_FILE = DATA_DIR / "positions.json"
SHORT_FILE = DATA_DIR / "shortlists.json"

# ---------- Helpers ----------
def load_json(path):
    """Load JSON data from file, return [] if file does not exist."""
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    """Save data to a JSON file with pretty formatting."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def parse_date(s):
    """Convert string (YYYY-MM-DD) to datetime.date."""
    return datetime.strptime(s, "%Y-%m-%d").date()

# ---------- AI Command Understanding ----------
def ai_understand(cmd):
    """
    Send user input to GitHub AI model and extract intent + details.
    Fallback if API fails or input is invalid.
    """
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "X-Requested-With": "python",
        "Content-Type": "application/json",
    }

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful HR assistant that outputs only JSON."},
            {"role": "user", "content": f"""
                Extract intent and details from: {cmd}.
                JSON format:
                {{
                  "intent": "search|choose|show|email|analytics|exit|help",
                  "skills": ["React","Python"],
                  "location": "Casablanca",
                  "minExp": 0,
                  "maxExp": 2,
                  "topN": 5,
                  "shortlistName": "FE-Intern-A",
                  "indices": [1,3],
                  "jobTitle": "Frontend Intern"
                }}
                If you cannot understand the input, return:
                {{ "intent": "fallback", "message": "Sorry, I can't do this right now." }}
            """}
        ],
        "temperature": 0
    }

    try:
        response = requests.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]

        # Remove Markdown code block if present
        if content.startswith("```"):
            content = "\n".join(content.split("\n")[1:-1])

        result = json.loads(content)

        # Ensure fallback if intent is missing or invalid
        if "intent" not in result or not result["intent"]:
            return {"intent": "fallback", "message": "Sorry, I can't do this right now."}

        return result

    except (requests.exceptions.RequestException, json.JSONDecodeError):
        return {"intent": "fallback", "message": "Sorry, I can't do this right now."}

# ---------- Candidate Scoring ----------
def score_candidate(candidate, filters):
    score = 0
    reasons = []

    # Skill matching
    req_skills = filters.get("skills", [])
    skill_matches = 0
    for s in req_skills:
        if s.lower() in [cs.lower() for cs in candidate.get("skills", [])]:
            skill_matches += 1
    score += 2 * skill_matches
    if skill_matches:
        reasons.append(f"{'+'.join(req_skills)} match (+{2*skill_matches})")

    # Location match
    if filters.get("location") and candidate.get("location","").lower() == filters["location"].lower():
        score += 1
        reasons.append(f"{candidate['location']} (+1)")

    # Experience range match
    minExp = filters.get("minExp")
    maxExp = filters.get("maxExp")
    if minExp is not None and maxExp is not None:
        exp = candidate.get("experienceYears", 0)
        if minExp <= exp <= maxExp:
            score += 1
            reasons.append(f"{exp}y fits (+1)")

    return score, " , ".join(reasons)

# ---------- Candidate Search ----------
def search_candidates(filters, candidates):
    scored = []
    for idx, c in enumerate(candidates, start=1):
        sc, reason = score_candidate(c, filters)
        scored.append({"index": idx, "candidate": c, "score": sc, "reason": reason if reason else "no matches"})
    scored_sorted = sorted(scored, key=lambda x: x["score"], reverse=True)
    topN = filters.get("topN", 5)
    return scored_sorted[:topN]

# ---------- Shortlists ----------
def load_shortlists():
    return load_json(SHORT_FILE)

def save_shortlist(name, indices, candidates):
    shortlists = load_shortlists()
    sel = [candidates[i-1] for i in indices if 1 <= i <= len(candidates)]
    entry = {"name": name, "createdAt": datetime.now().isoformat(), "candidates": sel}
    shortlists.append(entry)
    save_json(SHORT_FILE, shortlists)
    return True

# ---------- Email Drafting ----------
def draft_email(recipient, job_title, closing="Best regards,\nRecruitment Team"):
    subject = f"{job_title} Interview Invitation"
    intro = f"Dear {recipient.get('firstName','')},"
    text = f"""{intro}

We are pleased to inform you that you have been shortlisted for an interview for the {job_title} position.

Please let us know your availability for a 30-minute interview this week.

{closing}
"""
    return {"subject": subject, "text": text, "to": recipient["email"]}

def html_template(email_obj):
    subject = email_obj["subject"]
    text = email_obj["text"].replace("\n", "<br>")
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>{subject}</title>
  </head>
  <body style="font-family: Arial, sans-serif; line-height:1.4;">
    <div style="max-width:600px; padding:16px; border:1px solid #ddd; border-radius:8px;">
      <h2 style="margin-top:0;">{subject}</h2>
      <div>{text}</div>
    </div>
  </body>
</html>"""

# ---------- Analytics ----------
def analytics_summary(candidates):
    countByStage = Counter([c.get("stage","UNKNOWN") for c in candidates])
    skills = Counter()
    for c in candidates:
        for s in c.get("skills", []):
            skills[s] += 1
    topSkills = skills.most_common(3)
    return {"countByStage": dict(countByStage), "topSkills": topSkills}

# ---------- CLI Display ----------
def print_candidate_short(cobj):
    c = cobj["candidate"]
    print(f"#{cobj['index']:02d} {c['firstName']} {c['lastName']} — {c['email']} — {c['location']} — {c['experienceYears']}y — score {cobj['score']} — {cobj['reason']}")

# ---------- Main Loop ----------
def main_loop():
    DATA_DIR.mkdir(exist_ok=True)
    candidates = load_json(CAND_FILE)
    positions = load_json(jobs_FILE)

    print("🤖 AI HR Agent: Hello! How can I help you?")
    last_search = []

    while True:
        cmd = input("\n> ").strip()
        if not cmd:
            continue

        ai_cmd = ai_understand(cmd)
        intent = ai_cmd.get("intent","fallback").lower()

        # Fallback
        if intent == "fallback":
            print(f"🤖 AI HR Agent: {ai_cmd.get('message','Sorry, I can\'t do this right now.')}")
            continue


        # Search
        if intent == "search":
            results = search_candidates(ai_cmd, candidates)
            last_search = results
            print(f"Found top {len(results)} results:")
            for r in results:
                print_candidate_short(r)

        # Choose
        elif intent == "choose":
            idxs = ai_cmd.get("indices", [])
            name = ai_cmd.get("shortlistName", "Unnamed")
            save_shortlist(name, idxs, [r["candidate"] for r in last_search])
            print(f"Shortlist '{name}' saved with {len(idxs)} candidates.")

        # Show
        elif intent == "show":
            name = ai_cmd.get("shortlistName", "")
            shortlists = load_shortlists()

            if name.lower() in ["", "all"]:
                if not shortlists:
                    print("No shortlists found.")
                    continue
                for s in shortlists:
                    print(f"\nShortlist: {s['name']} (created: {s['createdAt']})")
                    for idx, c in enumerate(s["candidates"], start=1):
                        print(f"  #{idx} {c['firstName']} {c['lastName']} — {c['email']} — {c['location']} — {c['experienceYears']}y")
                continue

            matches = [s for s in shortlists if s["name"].lower() == name.lower()]
            if not matches:
                print("Shortlist not found.")
                continue
            print(f"Candidates in '{name}':")
            for idx, c in enumerate(matches[0]["candidates"], start=1):
                print(f"#{idx} {c['firstName']} {c['lastName']} — {c['email']} — {c['location']} — {c['experienceYears']}y")

        # Email
        elif intent == "email":
            job_title = ai_cmd.get("jobTitle", "Job")
            sl_name = ai_cmd.get("shortlistName", None)
            shortlists = load_shortlists()
            if not shortlists:
                print("No shortlists found to send email.")
                continue
            if sl_name:
                matches = [s for s in shortlists if s["name"].lower() == sl_name.lower()]
                if not matches:
                    print(f"Shortlist '{sl_name}' not found.")
                    continue
                recipients = matches[0]["candidates"]
                sl_name = matches[0]["name"]
            else:
                recipients = shortlists[-1]["candidates"]
                sl_name = shortlists[-1]["name"]

            print(f"\nSending individual emails for shortlist '{sl_name}':")
            for person in recipients:
                email_obj = draft_email(person, job_title)
                print("\n--- SUBJECT ---")
                print(email_obj["subject"])
                print("\n--- TO ---")
                print(email_obj["to"])
                print("\n--- PLAINTEXT ---")
                print(email_obj["text"])
                print("\n--- HTML PREVIEW ---")
                print(html_template(email_obj))
                print("-"*40)

        # Analytics
        elif intent == "analytics":
            summary = analytics_summary(candidates)
            print("Pipeline by stage:")
            for k,v in summary["countByStage"].items():
                print(f"  {k} = {v}")
            print("Top skills:")
            for s,cnt in summary["topSkills"]:
                print(f"  {s} ({cnt})")

        # Exit
        elif intent in ["exit","quit"]:
            print("Bye!")
            break

        # Help
        elif intent == "help":
            print("""
Available commands (in natural language):
- "Find me React developers in Casablanca"
- "Choose 1 3 as FE-Intern-A"
- "Show shortlist FE-Intern-A" or "Show all"
- "Send email using Frontend Intern from FE-Intern-A"
- "Give me analytics"
- "Exit"
""")

        else:
            print("🤖 AI HR Agent: Sorry, I can't do this right now.")

if __name__ == "__main__":
    main_loop()