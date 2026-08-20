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

SUBMISSIONS_URL = "https://leetcode.com/api/submissions/"

def fetch_solved_problems(session: requests.Session) -> list:
    """Fetch solved problems from the user's LeetCode submission history."""
    print("Fetching your LeetCode submissions...")

    all_solved = []
    seen_slugs = set()
    offset = 0
    limit = 20

    while True:
        url = f"{SUBMISSIONS_URL}?offset={offset}&limit={limit}"

        resp = session.get(url, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        submissions = data.get("submissions_dump", [])

        if not submissions:
            break

        accepted_count = 0

        for sub in submissions:
            if sub.get("status_display") != "Accepted":
                continue

            slug = sub.get("title_slug")
            if not slug or slug in seen_slugs:
                continue

            seen_slugs.add(slug)
            accepted_count += 1

            all_solved.append({
                "question_id": sub.get("question_id"),
                "frontend_id": sub.get("frontend_id"),
                "title": sub.get("title"),
                "title_slug": slug,
                "difficulty": None,
                "paid_only": False,
            })

        print(
            f"  Offset {offset}: {len(submissions)} submissions, "
            f"{accepted_count} Accepted, "
            f"{len(all_solved)} unique solved problems"
        )

        if not data.get("has_next"):
            break

        next_offset = offset + len(submissions)

        if next_offset <= offset:
            print("  Pagination did not advance; stopping safely.")
            break

        offset = next_offset
        time.sleep(0.5)

    with open(SOLVED_FILE, "w") as f:
        json.dump(
            {
                "fetched_at": datetime.now(IST).isoformat(),
                "problems": all_solved,
            },
            f,
            indent=2,
        )

    print(
        f"Saved {len(all_solved)} unique solved problems "
        f"to {SOLVED_FILE.name}"
    )

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

def submit_solution(
    session: requests.Session,
    title_slug: str,
    question_id: str,
    lang: str,
    code: str
) -> dict:
    """Submit a solution and wait for the verdict."""

    url = SUBMIT_URL.format(slug=title_slug)

    # LeetCode requires the CSRF token for authenticated POST requests.
    csrf_token = os.getenv("CSRF_TOKEN", "").strip()

    if not csrf_token:
        print("ERROR: CSRF_TOKEN is missing.")
        return {
            "status": "error",
            "message": "CSRF_TOKEN is missing"
        }

    # Make the request look like a normal browser request.
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://leetcode.com",
        "Referer": f"https://leetcode.com/problems/{title_slug}/",
        "X-CSRFToken": csrf_token,
        "x-csrftoken": csrf_token,
        "X-Requested-With": "XMLHttpRequest",
    })

    # Make sure the CSRF cookie is also present.
    session.cookies.set(
        "csrftoken",
        csrf_token,
        domain="leetcode.com",
        path="/"
    )

    payload = {
        "lang": lang,
        "question_id": str(question_id),
        "typed_code": code,
    }

    print(f"  Submitting {title_slug} ({lang})...")

    resp = session.post(
        url,
        json=payload,
        timeout=30
    )

    if resp.status_code == 403:
        print("  ERROR: LeetCode returned HTTP 403 Forbidden.")
        print("  Submission was NOT accepted.")
        print(f"  Response: {resp.text[:500]}")
        return {
            "status": "error",
            "message": "HTTP 403 Forbidden",
            "http_status": 403
        }

    if resp.status_code == 429:
        print("  Rate limited! Waiting 30 seconds...")
        time.sleep(30)

        resp = session.post(
            url,
            json=payload,
            timeout=30
        )

    resp.raise_for_status()

    try:
        response_data = resp.json()
    except ValueError:
        print(f"  ERROR: Invalid JSON response: {resp.text[:500]}")
        return {
            "status": "error",
            "message": resp.text
        }

    submission_id = response_data.get("submission_id")

    if not submission_id:
        print(
            "  ERROR: No submission_id returned. "
            f"Response: {resp.text[:500]}"
        )
        return {
            "status": "error",
            "message": resp.text
        }

    print(f"  Submission ID: {submission_id}")

    # Poll for the final result.
    check_url = CHECK_URL.format(id=submission_id)

    for attempt in range(20):
        time.sleep(2 + attempt)

        check_resp = session.get(
            check_url,
            timeout=30
        )

        if check_resp.status_code == 403:
            print("  ERROR: HTTP 403 while checking submission.")
            return {
                "status": "error",
                "message": "HTTP 403 while checking submission",
                "http_status": 403
            }

        check_resp.raise_for_status()

        result = check_resp.json()
        state = result.get("state")

        if state == "SUCCESS":
            status_msg = result.get("status_msg", "Unknown")
            runtime = result.get("status_runtime", "N/A")
            memory = result.get("status_memory", "N/A")

            print(
                f"  Result: {status_msg} | "
                f"Runtime: {runtime} | "
                f"Memory: {memory}"
            )

            return {
                "status": status_msg,
                "runtime": runtime,
                "memory": memory,
            }

        print(
            f"  Waiting for result... "
            f"attempt {attempt + 1}/20"
        )

    return {
        "status": "timeout",
        "message": "Submission result polling timed out"
    }

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
    """Submit one random unsolved problem from the solution bank."""

    session = get_session()
    log = load_submission_log()

    # Safety: require explicit confirmation for a real submission.
    if not args.confirm:
        print("Submission NOT sent.")
        print("Run with --confirm when you are ready to submit.")
        return

    if already_submitted_today(log) and not args.force:
        print(
            f"Already submitted today ({get_today_str()}). "
            "Use --force to submit again."
        )
        return

    solutions = load_solutions()

    # Load problems already solved on LeetCode.
    solved = []
    if SOLVED_FILE.exists():
        try:
            with open(SOLVED_FILE) as f:
                solved_data = json.load(f)
            solved = solved_data.get("problems", [])
        except (json.JSONDecodeError, OSError):
            print("Warning: Could not read solved_problems.json.")

    solved_ids = {
        str(p.get("question_id"))
        for p in solved
        if p.get("question_id") is not None
    }

    solved_slugs = {
        p.get("title_slug")
        for p in solved
        if p.get("title_slug")
    }

    recent_slugs = {
        e.get("title_slug")
        for e in log[-10:]
        if e.get("title_slug")
    }

    candidates = [
        s for s in solutions
        if str(s.get("question_id")) not in solved_ids
        and s.get("title_slug") not in solved_slugs
        and s.get("title_slug") not in recent_slugs
    ]

    if not candidates:
        print("No eligible unsolved problems remain.")
        return

    pick = random.choice(candidates)

    print(f"Solutions in bank: {len(solutions)}")
    print(f"Already solved: {len(solved)}")
    print(f"Recently submitted by bot: {len(recent_slugs)}")
    print(f"Eligible candidates: {len(candidates)}")
    print()
    print("Selected problem:")
    print(f"  #{pick['question_id']} {pick['title']} ({pick['difficulty']})")
    print(f"  Slug: {pick['title_slug']}")
    print("  This problem is not in solved_problems.json.")
    print()
    print(f"Submitting {pick['title_slug']} ({pick['lang']})...")

    result = submit_solution(
        session,
        pick["title_slug"],
        pick["question_id"],
        pick["lang"],
        pick["typed_code"],
    )

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

    print(
        f"Result: {result.get('status', 'unknown')} | "
        f"Runtime: {result.get('runtime')} | "
        f"Memory: {result.get('memory')}"
    )
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
    p_submit.add_argument(
        "--confirm",
        action="store_true",
        help="Actually submit the selected problem",
    )
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
