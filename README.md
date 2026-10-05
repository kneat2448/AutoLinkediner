# AutoLinkediner

Drafts one calm, plain-language LinkedIn post a day about AI news. Each draft comes with a 1080×1350 image card and is sent to you on Telegram. **Nothing is posted until you approve it.**

The pipeline collects stories from Hacker News, Reddit, Hugging Face daily papers, and tweets you forward. An LLM picks the best one, writes the post and a headline, and the card is rendered. Everything runs on free tiers (GitHub Actions, the Gemini free tier, and the Telegram Bot API).

See [CLAUDE.md](CLAUDE.md) for the full spec.

---

## Setup

### 1. Telegram bot (required)
1. In Telegram, message **@BotFather**, send `/newbot`, and follow the prompts. Copy the **bot token**.
2. Send any message (e.g. `hi`) to your new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and find `"chat":{"id":123456789,...}`. That number is your **chat ID**.

The bot only responds to that chat ID. Messages from anyone else are ignored.

### 2. LLM key (required)
- **Gemini (default, free):** create a key at <https://aistudio.google.com/apikey>. Choose a current model from <https://ai.google.dev/gemini-api/docs/models> (a "Flash" model is enough) and check its free-tier limits.
- **Groq (free fallback):** create a key at <https://console.groq.com/keys>, and pick a model from <https://console.groq.com/docs/models>.
- **Anthropic (paid):** get a key from <https://console.anthropic.com>, and pick a model from <https://docs.anthropic.com/en/docs/about-claude/models>.

A day typically uses 3 LLM calls (pick, post, headline), plus up to 4 more if validation fails.

### 3. Reddit (optional)
Reddit now asks developers to request API access before creating an app. If you have access, create a **script** app at <https://www.reddit.com/prefs/apps>. If you don't, leave these secrets unset: the Reddit source logs a warning and is skipped. (Reddit's public JSON endpoints block requests from servers, so they aren't used.)

### 4. GitHub secrets
In the repo, go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Example / notes |
|---|---|
| `LLM_PROVIDER` | `gemini` (or `groq` / `anthropic`) |
| `LLM_MODEL` | the exact model name from the provider's docs |
| `GEMINI_API_KEY` / `GROQ_API_KEY` / `ANTHROPIC_API_KEY` | only the one you use |
| `TELEGRAM_BOT_TOKEN` | from BotFather |
| `TELEGRAM_CHAT_ID` | from step 1 |
| `AUTHOR_NAME` | shown in the corner of the image |
| `POST_MODE` | `manual` (default) until Phase 3 is verified |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` | optional, e.g. `AutoLinkediner/1.0 by u/yourname` |
| `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_TOKEN_ISSUED` | Phase 3 only |

Optionally, add `LLM_FALLBACK_MODEL`: a second model from the same provider (e.g. a Flash-Lite model). It's tried when the main model keeps returning errors such as 503 "overloaded", which happens on free tiers at busy times.

**Tip:** GitHub hides every secret value wherever it appears in the logs, so a secret like `LLM_PROVIDER=gemini` shows up as `***`. The non-sensitive settings (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_FALLBACK_MODEL`, `AUTHOR_NAME`, `POST_MODE`, `LINKEDIN_TOKEN_ISSUED`, `LINKEDIN_VERSION`) can be created under the **Variables** tab instead. The workflows read variables first and fall back to secrets.

Next, check **Settings → Actions → General → Workflow permissions**. It should be set to *Read and write* (the workflows also request `contents: write`).

### 5. Try it
**Actions → Daily draft → Run workflow**, with *Dry run* ticked first, then unticked. The draft arrives on Telegram.

---

## Daily use (Telegram)

| You send | What happens |
|---|---|
| `ok` / `approve` / 👍 | Manual mode: you get the final copy (image + text + source link) to post. Auto mode: it's published to LinkedIn and you get the link. |
| `redo` | The post and headline are rewritten for the same story. |
| `next` | This story is dropped and the next-best one is drafted. |
| `skip` | No post today. |
| Any text over 40 characters | Used as your edited post. Start it with `headline: Your new headline` on the first line to re-render the image. Reply `ok` afterwards. |
| An x.com / twitter.com link | Queued for future drafts (with a priority boost). Add your own text in the same message to use it as the tweet text. If the text can't be fetched, the bot asks you to reply with it. |

Replies are checked every 30 minutes, and GitHub's cron can run 5–20 minutes late.

**Actions minutes:** most poll runs finish in under a minute, because Chromium is installed only when a reply needs a new image. Public repos get unlimited minutes. Private repos get 2,000 free minutes a month, and this setup uses roughly 1,500–1,700 of them.

---

## Local development

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
python -m playwright install chromium

python -m pytest                       # tests
python -m src.render --preview         # renders all 3 templates to out/
python -m src.main_draft --dry-run     # full draft printed locally; nothing sent or saved
python -m src.main_poll --dry-run      # reads Telegram replies; nothing sent or saved
```

Set the env vars from the table above in your shell first (or in a local `.env` you `source`; `.env` is gitignored).

---

## Phase 3: posting to LinkedIn automatically

1. Create an app at <https://www.linkedin.com/developers/apps>. LinkedIn requires the app to be associated with a Company Page.
2. Under **Products**, add **Sign In with LinkedIn using OpenID Connect** and **Share on LinkedIn**.
3. Under **Auth**, add `http://localhost:8765/callback` as a redirect URL.
4. Run the helper locally:
   ```bash
   LINKEDIN_CLIENT_ID=... LINKEDIN_CLIENT_SECRET=... python scripts/linkedin_auth.py
   ```
5. Save the printed `LINKEDIN_ACCESS_TOKEN` and `LINKEDIN_TOKEN_ISSUED` as secrets, then set `POST_MODE=auto`.

Tokens last about 60 days. From day 50 on, the daily run sends you a Telegram reminder to rerun the helper. The API version header defaults to `202609`; you can override it with a `LINKEDIN_VERSION` secret.

If publishing fails, nothing is posted. You get the error type and the manual copy, and you can reply `ok` to retry.
