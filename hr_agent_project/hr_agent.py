
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HR Agent — chat-only assistant for quick recruiting tasks.

Features:
- parse_query(text)
- search_candidates(filters)
- save_shortlist(name, candidate_indices)
- draft_email(recipients, job_title, tone='friendly')
- html_template(email)
- analytics_summary()

Data folder:
- data/candidates.json (>=12)
- data/jobs.json (2–3)
- data/shortlists.json (created on demand)

CLI examples:
> Find top 5 React interns in Casablanca, 0–2 years, available this month
> Save #1 #3 as "FE-Intern-A"
> Draft an outreach email for "FE-Intern-A" using job "Frontend Intern" in friendly tone
> Change the subject to "Quick chat about a Frontend Intern role?" and re-preview
> Show analytics
> Quit
"""
import json, os, re, datetime
from collections import Counter, defaultdict
from typing import List, Dict, Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CANDIDATES_FP = os.path.join(DATA_DIR, "candidates.json")
JOBS_FP = os.path.join(DATA_DIR, "jobs.json")
SHORTLISTS_FP = os.path.join(DATA_DIR, "shortlists.json")

def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return default

def _save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

# ---------- Required: parse_query ----------
def parse_query(text: str) -> Dict[str, Any]:
    """
    Extract rough filters from free text:
    {role?, skills[], location?, minExp?, maxExp?, availabilityWindowDays?}
    """
    t = text.lower().strip()

    filters = {
        "role": None,
        "skills": [],
        "location": None,
        "minExp": None,
        "maxExp": None,
        "availabilityWindowDays": None
    }

    # role (simple heuristics)
    role_match = re.search(r"(intern|junior|frontend|backend|full[- ]?stack|react\s*ui|trainee)", t)
    if role_match:
        filters["role"] = role_match.group(0)

    # location: detect "in <word>" or known city names
    loc_match = re.search(r"\bin\s+([a-zéèêîïâàç\-]+)", t)
    known_cities = ["casablanca", "rabat", "marrakesh", "marrakech", "tangier", "fes", "agadir"]
    if loc_match:
        filters["location"] = loc_match.group(1).strip().title()
    else:
        for city in known_cities:
            if city in t:
                filters["location"] = city.title()
                break

    # experience: "0-2 years", "0–2y", "2 years", "with 1 y"
    range_match = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*(?:years?|y)", t)
    if range_match:
        filters["minExp"] = int(range_match.group(1))
        filters["maxExp"] = int(range_match.group(2))
    else:
        # single value "2 years"
        single_match = re.search(r"(\d+)\s*(?:years?|y)", t)
        if single_match:
            v = int(single_match.group(1))
            filters["minExp"] = max(0, v-1)
            filters["maxExp"] = v

    # skills: pick words that look like tech terms
    skill_candidates = re.findall(r"\b(react|javascript|js|typescript|ts|html|css|git|python|flask|sql|django|redux|node|next\.?js|tailwind)\b", t)
    norm = {"javascript":"JS","ts":"TypeScript", "next.js":"Next.js", "nextjs":"Next.js"}
    for s in skill_candidates:
        s2 = s.lower()
        s2 = norm.get(s2, s2.capitalize() if len(s2)>2 else s2.upper())
        if s2 == "Js": s2 = "JS"
        if s2 not in filters["skills"]:
            filters["skills"].append(s2)

    # availability
    # "available this month" -> 30 days
    if "available this month" in t or "this month" in t:
        filters["availabilityWindowDays"] = 30
    else:
        # "available in X days"
        m = re.search(r"available\s*(?:in)?\s*(\d+)\s*days", t)
        if m:
            filters["availabilityWindowDays"] = int(m.group(1))
        # "available next month" -> 45 days
        if "available next month" in t:
            filters["availabilityWindowDays"] = 45

    return filters

# ---------- Scoring ----------
def _score_candidate(c: Dict[str, Any], required_skills: List[str], location: str, minExp, maxExp, availability_days: int) -> (int, List[str]):
    score = 0
    reasons = []

    # +2 per required skill
    if required_skills:
        matched = [s for s in required_skills if s in c.get("skills", [])]
        if matched:
            pts = 2 * len(matched)
            score += pts
            reasons.append(f"{'+'.join(matched)} match (+{pts})")

    # +1 location exact match
    if location and location.lower() == c.get("location","").lower():
        score += 1
        reasons.append(f"{location} (+1)")

    # +1 experience within range (±1 ok)
    if minExp is not None and maxExp is not None:
        exp = c.get("experienceYears", 0)
        if exp >= (minExp - 1) and exp <= (maxExp + 1):
            score += 1
            reasons.append(f"{exp}y fits (±1) (+1)")

    # +1 availability within next X days
    if availability_days:
        try:
            avail = datetime.date.fromisoformat(c.get("availabilityDate"))
            delta = (avail - datetime.date.today()).days
            if 0 <= delta <= availability_days:
                score += 1
                reasons.append(f"available in {delta}d (+1)")
        except Exception:
            pass

    return score, reasons

# ---------- Required: search_candidates ----------
def search_candidates(filters: Dict[str, Any], top_n: int = 5) -> List[Dict[str, Any]]:
    candidates = _load_json(CANDIDATES_FP, [])
    jobs = _load_json(JOBS_FP, [])
    # derive required skills from filters.role by using jobs if matches
    required_skills = list(filters.get("skills") or [])
    if not required_skills and filters.get("role"):
        # try match job by role keyword
        key = filters["role"].lower()
        for j in jobs:
            if key in j["title"].lower():
                required_skills = j["skillsRequired"]
                break

    results = []
    for idx, c in enumerate(candidates, start=1):
        score, reasons = _score_candidate(
            c,
            required_skills=required_skills,
            location=filters.get("location"),
            minExp=filters.get("minExp"),
            maxExp=filters.get("maxExp"),
            availability_days=filters.get("availabilityWindowDays")
        )
        if score > 0:
            results.append({
                "index": idx,
                "candidate": c,
                "score": score,
                "reason": f"{', '.join(reasons)} → score {score}" if reasons else f"score {score}"
            })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]

# ---------- Required: save_shortlist ----------
def save_shortlist(name: str, candidate_indices: List[int]) -> bool:
    lists = _load_json(SHORTLISTS_FP, {})
    lists[name] = candidate_indices
    _save_json(SHORTLISTS_FP, lists)
    return True

# ---------- Helper: resolve recipients ----------
def _recipients_from_name_or_indices(target: str) -> List[Dict[str,Any]]:
    """
    target can be:
    - shortlist name string (will load indices)
    - comma separated indices string like "1,3,5"
    """
    candidates = _load_json(CANDIDATES_FP, [])
    lists = _load_json(SHORTLISTS_FP, {})
    indices = []

    if target in lists:
        indices = lists[target]
    else:
        # parse numbers
        nums = re.findall(r"#?(\d+)", target)
        indices = [int(n) for n in nums]

    outs = []
    for i in indices:
        if 1 <= i <= len(candidates):
            outs.append(candidates[i-1])
    return outs

# ---------- Required: draft_email ----------
def draft_email(recipients: List[Dict[str,Any]], job_title: str, tone: str = "friendly") -> Dict[str,str]:
    if not recipients:
        return {"subject": "", "text": ""}

    jobs = _load_json(JOBS_FP, [])
    job = next((j for j in jobs if j["title"].lower() == job_title.lower()), None)
    jd = job["jdSnippet"] if job else ""
    skills = ", ".join(job["skillsRequired"]) if job else ""

    if len(recipients) == 1:
        r = recipients[0]
        subject = f"{r['firstName']}, quick chat about a {job_title} opportunity?"
        greeting = f"Hi {r['firstName']},"
    else:
        subject = f"Quick chat about a {job_title} opportunity?"
        greeting = "Hi there,"

    closings = {
        "friendly": "Cheers,\nSoukaina — Talent Team",
        "formal": "Kind regards,\nSoukaina\nTalent Acquisition",
        "concise": "Thanks,\nSoukaina"
    }
    closing = closings.get(tone, closings["friendly"])

    body_lines = [
        greeting,
        "",
        f"I'm reaching out about a {job_title} role in {job['location'] if job else 'our team'}.",
    ]
    if jd:
        body_lines.append(jd)
    if skills:
        body_lines.append(f"Nice-to-have: {skills}.")
    body_lines += [
        "",
        "Would you be open to a quick chat this week? I’d love to learn more about your interests.",
        "",
        closing
    ]
    text = "\n".join(body_lines)
    return {"subject": subject, "text": text}

# ---------- Required: html_template ----------
def html_template(email: Dict[str,str]) -> str:
    subject = email.get("subject","(no subject)")
    text = email.get("text","")
    # Convert plain text to simple paragraphs
    paras = "".join(f"<p>{line}</p>" if line.strip() else "<br/>" for line in text.split("\n"))
    html = f"""<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>{subject}</title>
    <style>
      body {{ font-family: Arial, sans-serif; line-height:1.5; padding:24px; background:#f9fafb; }}
      .card {{ max-width:640px; margin:auto; background:white; border:1px solid #e5e7eb; border-radius:12px; padding:24px; }}
      .subject {{ font-size:20px; font-weight:700; margin-bottom:12px; }}
      .meta {{ color:#6b7280; font-size:12px; margin-bottom:16px; }}
    </style>
  </head>
  <body>
    <div class="card">
      <div class="subject">{subject}</div>
      <div class="meta">Preview only</div>
      <div class="content">{paras}</div>
    </div>
  </body>
</html>"""
    return html

# ---------- Required: analytics_summary ----------
def analytics_summary() -> Dict[str, Any]:
    candidates = _load_json(CANDIDATES_FP, [])
    countByStage = defaultdict(int)
    skills_counter = Counter()
    for c in candidates:
        countByStage[c.get("stage","UNKNOWN")] += 1
        for s in c.get("skills", []):
            skills_counter[s] += 1
    topSkills = skills_counter.most_common(3)
    return {"countByStage": dict(countByStage), "topSkills": topSkills}

# ---------- Intent classification & router ----------
def classify_intent(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["find", "search", "look for"]):
        return "search"
    if t.startswith("save ") or " save " in t:
        return "save"
    if t.startswith("draft ") or "draft outreach email" in t or t.startswith("email "):
        return "email"
    if t.startswith("change the subject") or "edit subject" in t or "closing" in t:
        return "edit_email"
    if "analytics" in t or "show analytics" in t:
        return "analytics"
    if t in ("quit", "exit"):
        return "quit"
    return "unknown"

def repl():
    print("HR Agent — type 'Quit' to exit.")
    last_search = []
    last_email = None

    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not q:
            continue

        intent = classify_intent(q)

        if intent == "quit":
            print("Bye.")
            break

        elif intent == "search":
            filters = parse_query(q)
            results = search_candidates(filters, top_n=5)
            last_search = results
            if not results:
                print("No matches found.")
            else:
                for i, r in enumerate(results, start=1):
                    c = r["candidate"]
                    full = f"{c['firstName']} {c['lastName']} — {c['location']} — {c['experienceYears']}y — skills: {', '.join(c['skills'])}"
                    print(f"#{i} (idx {r['index']}): {full}")
                    print(f"   Why: {r['reason']}")
            print("Tip: Save #1 #3 as \"Name-Here\"")

        elif intent == "save":
            # pattern: Save #1 #3 as "FE-Intern-A"
            name_match = re.search(r'as\s+"([^"]+)"', q, re.IGNORECASE)
            nums = re.findall(r"#(\d+)", q)
            if not name_match or not nums:
                print('Usage: Save #1 #3 as "Shortlist-Name" (use # from last search)')
                continue
            name = name_match.group(1)
            # map #i (1..len(last_search)) to original candidate index
            mapped = []
            for n in nums:
                i = int(n)
                if 1 <= i <= len(last_search):
                    mapped.append(last_search[i-1]["index"])
            if not mapped:
                print("Nothing saved; numbers out of range.")
                continue
            save_shortlist(name, mapped)
            print(f'Shortlist "{name}" saved with indices: {mapped}')

        elif intent == "email":
            # pattern: Draft outreach email for "FE-Intern-A" using job "Frontend Intern" in friendly tone
            list_or_indices = None
            job_title = None
            tone = "friendly"

            m1 = re.search(r'for\s+"([^"]+)"', q, re.IGNORECASE)
            if m1:
                list_or_indices = m1.group(1)
            else:
                # allow direct numbers: Draft email for #1
                nums = re.findall(r"#(\d+)", q)
                if nums:
                    list_or_indices = ",".join(nums)

            m2 = re.search(r'job\s+"([^"]+)"', q, re.IGNORECASE)
            if m2:
                job_title = m2.group(1)

            m3 = re.search(r'in\s+(friendly|formal|concise)\s+tone', q, re.IGNORECASE)
            if m3:
                tone = m3.group(1).lower()

            recipients = _recipients_from_name_or_indices(list_or_indices or "")
            email = draft_email(recipients, job_title or "Opportunity", tone=tone)
            html = html_template(email)
            last_email = email
            print("Subject:", email["subject"])
            print("----- HTML PREVIEW BEGIN -----")
            print(html)
            print("----- HTML PREVIEW END -----")
            print('Edit subject or closing? Example: Change the subject to "New subject"')

        elif intent == "edit_email":
            # Change the subject to "..."
            if not last_email:
                print("No email in context. Draft one first.")
                continue
            msub = re.search(r'subject to\s+"([^"]+)"', q, re.IGNORECASE)
            mclose = re.search(r'closing to\s+"([^"]+)"', q, re.IGNORECASE)
            if msub:
                last_email["subject"] = msub.group(1)
            if mclose:
                # replace last line after a blank line; naive but OK
                parts = last_email["text"].split("\n")
                # Find closing start (after last blank line)
                try:
                    last_blank = len(parts) - 1 - parts[::-1].index('')
                except ValueError:
                    last_blank = len(parts)-1
                new_text = "\n".join(parts[:last_blank+1] + [mclose.group(1)])
                last_email["text"] = new_text
            html = html_template(last_email)
            print("Subject:", last_email["subject"])
            print("----- HTML PREVIEW BEGIN -----")
            print(html)
            print("----- HTML PREVIEW END -----")

        elif intent == "analytics":
            a = analytics_summary()
            print("Pipeline by stage:", ", ".join(f"{k}={v}" for k,v in a["countByStage"].items()))
            print("Top skills:", ", ".join(f"{k}({v})" for k,v in a["topSkills"]))

        else:
            print("I didn't understand. Try: Find React interns in Casablanca, 0–2 years, available this month")

if __name__ == "__main__":
    repl()
