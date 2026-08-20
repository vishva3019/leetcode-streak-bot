#!/usr/bin/env python3
"""
LeetCode Streak Bot — Keeps your contribution graph green.

Usage:
    python leetcode_bot.py submit          # Submit one random easy problem now
    python leetcode_bot.py daily           # Submit the daily challenge (if in bank)
    python leetcode_bot.py fetch-solved    # Fetch & store your solved problems
    python leetcode_bot.py status          # Show streak & submission stats
    python leetcode_bot.py scheduler       # Run as daemon, auto-submits daily at 00:30 IST
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

# ─── Config ───────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

LEETCODE_SESSION = os.getenv("LEETCODE_SESSION", "")
CSRF_TOKEN = os.getenv("CSRF_TOKEN", "")
CF_CLEARANCE = os.getenv("CF_CLEARANCE", "")
USERNAME = os.getenv("LEETCODE_USERNAME", "Vikash_SDE")

GRAPHQL_URL = "https://leetcode.com/graphql/"
SUBMIT_URL = "https://leetcode.com/problems/{slug}/submit/"
CHECK_URL = "https://leetcode.com/submissions/detail/{id}/check/"

SOLUTIONS_FILE = BASE_DIR / "solutions.json"
SOLVED_FILE = BASE_DIR / "solved_problems.json"
LOG_FILE = BASE_DIR / "submission_log.json"

IST = timezone(timedelta(hours=5, minutes=30))

# ─── Session Setup ────────────────────────────────────────────────────────────

def get_session() -> requests.Session:
    """Create a requests.Session with LeetCode auth cookies & headers."""
    if not LEETCODE_SESSION or LEETCODE_SESSION == "your_leetcode_session_cookie_here":
        print("ERROR: Set LEETCODE_SESSION in .env file.")
        print("  1. Open leetcode.com in Chrome, press F12 → Application → Cookies")
        print("  2. Copy the value of LEETCODE_SESSION cookie")
        print("  3. Paste it in .env")
        sys.exit(1)

    s = requests.Session()
    s.cookies.set("LEETCODE_SESSION", LEETCODE_SESSION, domain="leetcode.com")
    s.cookies.set("csrftoken", CSRF_TOKEN, domain="leetcode.com")
    if CF_CLEARANCE:
        s.cookies.set("cf_clearance", CF_CLEARANCE, domain=".leetcode.com")
    s.headers.update({
        "Content-Type": "application/json",
        "Origin": "https://leetcode.com",
        "Referer": "https://leetcode.com",
        "x-csrftoken": CSRF_TOKEN,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"
        ),
    })
    return s


# ─── GraphQL Helpers ──────────────────────────────────────────────────────────

def graphql_request(session: requests.Session, query: str, variables: dict, operation: str) -> dict:
    """Send a GraphQL request to LeetCode."""
    payload = {
        "query": query,
        "variables": variables,
        "operationName": operation,
    }
    resp = session.post(GRAPHQL_URL, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ─── Fetch Solved Problems ───────────────────────────────────────────────────

SOLVED_QUERY = """
query problemsetQuestionListV2(
    $filters: QuestionFilterInput, $limit: Int, $skip: Int,
    $sortBy: QuestionSortByInput, $categorySlug: String
) {
    problemsetQuestionListV2(
        filters: $filters, limit: $limit, skip: $skip,
        sortBy: $sortBy, categorySlug: $categorySlug
    ) {
        questions {
            id
            titleSlug
            title
            questionFrontendId
            difficulty
            status
            acRate
            paidOnly
        }
        totalLength
        hasMore
    }
}
"""

def fetch_solved_problems(session: requests.Session) -> list:
    """Fetch all problems the user has solved (AC status)."""
    all_solved = []
    skip = 0
    limit = 100

    while True:
        variables = {
            "skip": skip,
            "limit": limit,
            "categorySlug": "all-code-essentials",
            "filters": {
                "filterCombineType": "ALL",
                "statusFilter": {
                    "questionStatuses": ["AC"],
                    "operator": "IS",
                },
            },
            "sortBy": {"sortField": "CUSTOM", "sortOrder": "ASCENDING"},
        }
        data = graphql_request(session, SOLVED_QUERY, variables, "problemsetQuestionListV2")
        questions = data["data"]["problemsetQuestionListV2"]["questions"]
        has_more = data["data"]["problemsetQuestionListV2"]["hasMore"]

        for q in questions:
            all_solved.append({
                "question_id": q["id"],
                "frontend_id": q["questionFrontendId"],
                "title": q["title"],
                "title_slug": q["titleSlug"],
                "difficulty": q["difficulty"],
                "paid_only": q["paidOnly"],
            })

        print(f"  Fetched {len(all_solved)} solved problems so far...")

        if not has_more:
            break
        skip += limit
        time.sleep(1)  # be polite

    # Save to file
    with open(SOLVED_FILE, "w") as f:
        json.dump({"fetched_at": datetime.now(IST).isoformat(), "problems": all_solved}, f, indent=2)

    print(f"Saved {len(all_solved)} solved problems to {SOLVED_FILE.name}")
    return all_solved


# ─── Get Daily Challenge ─────────────────────────────────────────────────────

DAILY_QUERY = """
query questionOfToday {
    activeDailyCodingChallengeQuestion {
        date
        link
        question {
            questionId
            questionFrontendId
            title
            titleSlug
            difficulty
        }
    }
}
"""

def fetch_daily_challenge(session: requests.Session) -> dict:
    """Fetch today's daily coding challenge."""
    data = graphql_request(session, DAILY_QUERY, {}, "questionOfToday")
    q = data["data"]["activeDailyCodingChallengeQuestion"]["question"]
    return {
        "question_id": q["questionId"],
        "frontend_id": q["questionFrontendId"],
        "title": q["title"],
        "title_slug": q["titleSlug"],
        "difficulty": q["difficulty"],
    }


# ─── Get Problem Detail (question_id from slug) ──────────────────────────────

DETAIL_QUERY = """
query questionData($titleSlug: String!) {
    question(titleSlug: $titleSlug) {
        questionId
        questionFrontendId
        title
        titleSlug
        difficulty
        codeSnippets {
            lang
            langSlug
            code
        }
    }
}
"""

def fetch_problem_detail(session: requests.Session, title_slug: str) -> dict:
    """Fetch problem detail by slug."""
    data = graphql_request(session, DETAIL_QUERY, {"titleSlug": title_slug}, "questionData")
    return data["data"]["question"]


# ─── Submit Solution ──────────────────────────────────────────────────────────

def submit_solution(session: requests.Session, title_slug: str, question_id: str, lang: str, code: str) -> dict:
    """Submit a solution and wait for the verdict."""
    url = SUBMIT_URL.format(slug=title_slug)
    session.headers["Referer"] = f"https://leetcode.com/problems/{title_slug}/"

    payload = {
        "lang": lang,
        "question_id": question_id,
        "typed_code": code,
    }

    print(f"  Submitting {title_slug} ({lang})...")
    resp = session.post(url, json=payload, timeout=30)

    if resp.status_code == 429:
        print("  Rate limited! Waiting 30s...")
        time.sleep(30)
        resp = session.post(url, json=payload, timeout=30)

    resp.raise_for_status()
    submission_id = resp.json().get("submission_id")

    if not submission_id:
        print(f"  ERROR: No submission_id returned. Response: {resp.text}")
        return {"status": "error", "message": resp.text}

    # Poll for result
    check_url = CHECK_URL.format(id=submission_id)
    for attempt in range(20):
        time.sleep(2 + attempt)  # progressive backoff
        check_resp = session.get(check_url, timeout=30)
        check_resp.raise_for_status()
        result = check_resp.json()

        state = result.get("state")
        if state == "SUCCESS":
            status_msg = result.get("status_msg", "Unknown")
            runtime = result.get("status_runtime", "N/A")
            memory = result.get("status_memory", "N/A")
            print(f"  Result: {status_msg} | Runtime: {runtime} | Memory: {memory}")
            return {
                "status": status_msg,
                "runtime": runtime,
                "memory": memory,
                "submission_id": submission_id,
            }
        elif state == "PENDING" or state == "STARTED":
            print(f"  Waiting for result... (attempt {attempt + 1})")
        else:
            print(f"  Unexpected state: {state} — {result}")
            return {"status": "error", "state": state, "raw": result}

    print("  Timed out waiting for result.")
    return {"status": "timeout", "submission_id": submission_id}


# ─── Solution Bank ────────────────────────────────────────────────────────────

def load_solutions() -> list:
    """Load the pre-built solution bank."""
    with open(SOLUTIONS_FILE) as f:
        return json.load(f)


def load_submission_log() -> list:
    """Load submission history."""
    if LOG_FILE.exists():
        with open(LOG_FILE) as f:
            return json.load(f)
    return []


def save_submission_log(log: list):
    """Save submission history."""
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


def get_today_str() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def already_submitted_today(log: list) -> bool:
    today = get_today_str()
    return any(entry.get("date") == today and entry.get("status") == "Accepted" for entry in log)


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_submit(args):
    """Submit one random easy problem from the solution bank."""
    session = get_session()
    log = load_submission_log()

    if already_submitted_today(log) and not args.force:
        print(f"Already submitted today ({get_today_str()}). Use --force to submit again.")
        return

    solutions = load_solutions()

    # Prefer problems not submitted recently
    recent_slugs = {e["title_slug"] for e in log[-10:]} if log else set()
    candidates = [s for s in solutions if s["title_slug"] not in recent_slugs]
    if not candidates:
        candidates = solutions

    pick = random.choice(candidates)
    print(f"Picked: #{pick['question_id']} {pick['title']} ({pick['difficulty']})")

    result = submit_solution(session, pick["title_slug"], pick["question_id"], pick["lang"], pick["typed_code"])

    log.append({
        "date": get_today_str(),
        "timestamp": datetime.now(IST).isoformat(),
        "question_id": pick["question_id"],
        "title": pick["title"],
        "title_slug": pick["title_slug"],
        "difficulty": pick["difficulty"],
        "lang": pick["lang"],
        "status": result.get("status", "unknown"),
        "runtime": result.get("runtime"),
        "memory": result.get("memory"),
    })
    save_submission_log(log)
    print("Done!")


def cmd_daily(args):
    """Submit the daily challenge if we have a solution for it."""
    session = get_session()
    log = load_submission_log()

    if already_submitted_today(log) and not args.force:
        print(f"Already submitted today ({get_today_str()}). Use --force to submit again.")
        return

    daily = fetch_daily_challenge(session)
    print(f"Daily Challenge: #{daily['frontend_id']} {daily['title']} ({daily['difficulty']})")

    solutions = load_solutions()
    match = next((s for s in solutions if s["title_slug"] == daily["title_slug"]), None)

    if match:
        print("  Found solution in bank!")
        result = submit_solution(session, match["title_slug"], match["question_id"], match["lang"], match["typed_code"])
    else:
        print("  No solution in bank for daily challenge. Falling back to random easy problem...")
        pick = random.choice(solutions)
        print(f"  Fallback: #{pick['question_id']} {pick['title']} ({pick['difficulty']})")
        result = submit_solution(session, pick["title_slug"], pick["question_id"], pick["lang"], pick["typed_code"])
        daily = pick  # use fallback info for logging

    log.append({
        "date": get_today_str(),
        "timestamp": datetime.now(IST).isoformat(),
        "question_id": daily.get("question_id", daily.get("frontend_id")),
        "title": daily["title"],
        "title_slug": daily["title_slug"],
        "difficulty": daily["difficulty"],
        "lang": match["lang"] if match else "python3",
        "status": result.get("status", "unknown"),
        "runtime": result.get("runtime"),
        "memory": result.get("memory"),
    })
    save_submission_log(log)
    print("Done!")


def cmd_fetch_solved(args):
    """Fetch all solved problems from LeetCode."""
    session = get_session()
    print("Fetching solved problems...")
    fetch_solved_problems(session)


def cmd_status(args):
    """Show streak info and recent submissions."""
    session = get_session()
    log = load_submission_log()

    # User profile query for streak info
    STREAK_QUERY = """
    query userProfileCalendar($username: String!, $year: Int) {
        matchedUser(username: $username) {
            userCalendar(year: $year) {
                activeYears
                streak
                totalActiveDays
                submissionCalendar
            }
        }
    }
    """
    year = datetime.now(IST).year
    data = graphql_request(session, STREAK_QUERY, {"username": USERNAME, "year": year}, "userProfileCalendar")
    cal = data["data"]["matchedUser"]["userCalendar"]

    print(f"\n{'='*50}")
    print(f"  LeetCode Streak Bot — @{USERNAME}")
    print(f"{'='*50}")
    print(f"  Current Streak:    {cal['streak']} days")
    print(f"  Total Active Days: {cal['totalActiveDays']} ({year})")
    print(f"  Submitted Today:   {'Yes' if already_submitted_today(log) else 'No'}")
    print(f"  Solutions in Bank: {len(load_solutions())}")
    print(f"  Total Bot Submits: {len(log)}")

    if log:
        print(f"\n  Last 5 submissions:")
        for entry in log[-5:]:
            icon = "✓" if entry.get("status") == "Accepted" else "✗"
            print(f"    {icon} {entry['date']} — {entry['title']} [{entry.get('status', '?')}]")

    print(f"{'='*50}\n")


def cmd_scheduler(args):
    """Run as a persistent daemon that submits once per day."""
    try:
        import schedule
    except ImportError:
        print("Install schedule: pip install schedule")
        sys.exit(1)

    print(f"Scheduler started. Will submit daily at 00:30 IST for @{USERNAME}")
    print("Press Ctrl+C to stop.\n")

    class FakeArgs:
        force = False

    def daily_job():
        print(f"\n[{datetime.now(IST).isoformat()}] Running daily submission...")
        try:
            cmd_submit(FakeArgs())
        except Exception as e:
            print(f"  ERROR: {e}")

    # Schedule at 00:30 IST (= 19:00 UTC previous day)
    schedule.every().day.at("00:30").do(daily_job)  # 19:00 UTC = 00:30 IST

    # Also run immediately if not submitted today
    log = load_submission_log()
    if not already_submitted_today(log):
        print("No submission today yet — submitting now...")
        daily_job()

    while True:
        schedule.run_pending()
        time.sleep(60)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="LeetCode Streak Bot — Keep your contribution graph green",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    p_submit = sub.add_parser("submit", help="Submit one random easy problem")
    p_submit.add_argument("--force", action="store_true", help="Submit even if already done today")
    p_submit.set_defaults(func=cmd_submit)

    p_daily = sub.add_parser("daily", help="Submit the daily challenge or fallback")
    p_daily.add_argument("--force", action="store_true", help="Submit even if already done today")
    p_daily.set_defaults(func=cmd_daily)

    p_fetch = sub.add_parser("fetch-solved", help="Fetch & store all solved problems")
    p_fetch.set_defaults(func=cmd_fetch_solved)

    p_status = sub.add_parser("status", help="Show streak & submission stats")
    p_status.set_defaults(func=cmd_status)

    p_sched = sub.add_parser("scheduler", help="Run daemon, auto-submits daily at 00:30 IST")
    p_sched.set_defaults(func=cmd_scheduler)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
