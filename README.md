# LeetCode Streak Bot

Automates daily LeetCode submissions to keep your contribution graph green.

## How It Works

1. **Solution Bank** — 40 pre-verified easy problem solutions stored in `solutions.json`
2. **Daily Submit** — Picks a random problem from the bank and submits it
3. **Streak Tracking** — Logs every submission to `submission_log.json`
4. **Scheduler** — Optional daemon mode that auto-submits at 00:30 IST daily

## Setup

```bash
cd leetcode_bot
pip install -r requirements.txt
```

### Get Your Cookies

1. Open [leetcode.com](https://leetcode.com) in Chrome
2. Press **F12** → **Application** → **Cookies** → `https://leetcode.com`
3. Copy these two values:
   - `LEETCODE_SESSION`
   - `csrftoken`
4. Paste them in `.env`:

```env
LEETCODE_SESSION=eyJhbGciOi...
CSRF_TOKEN=ILGyXsB4gO...
LEETCODE_USERNAME=Vikash_SDE
```

> ⚠️ Session cookies expire every ~14 days. You'll need to refresh them.

## Usage

```bash
# Submit one random easy problem right now
python leetcode_bot.py submit

# Submit even if already done today
python leetcode_bot.py submit --force

# Try submitting the daily challenge (falls back to random if not in bank)
python leetcode_bot.py daily

# Fetch & save all your solved problems
python leetcode_bot.py fetch-solved

# Check your streak status
python leetcode_bot.py status

# Run as daemon (auto-submits daily at 00:30 IST)
python leetcode_bot.py scheduler
```

## Automate with Cron (Recommended)

Add to your crontab (`crontab -e`):

```cron
# Submit daily at 12:05 AM IST (6:35 PM UTC previous day)
35 18 * * * cd /path/to/leetcode_bot && /usr/bin/python3 leetcode_bot.py submit >> cron.log 2>&1
```

## Adding More Solutions

Edit `solutions.json` to add more problems:

```json
{
  "question_id": "392",
  "title": "Is Subsequence",
  "title_slug": "is-subsequence",
  "difficulty": "Easy",
  "lang": "python3",
  "typed_code": "class Solution:\n    def isSubsequence(self, s: str, t: str) -> bool:\n        i = 0\n        for c in t:\n            if i < len(s) and c == s[i]:\n                i += 1\n        return i == len(s)"
}
```

## Files

| File | Purpose |
|---|---|
| `leetcode_bot.py` | Main bot script |
| `solutions.json` | Pre-verified solution bank (40 easy problems) |
| `.env` | Your LeetCode credentials (gitignored) |
| `solved_problems.json` | Auto-generated list of your solved problems |
| `submission_log.json` | History of all bot submissions |
