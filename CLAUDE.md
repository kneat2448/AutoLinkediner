# CLAUDE.md — LinkedIn AI News Autoposter

## What this project is
A free, mostly-automated pipeline that publishes **one LinkedIn post per day** about AI news and research for a **general (non-technical) audience**. It:

1. Collects candidate stories from AI news feeds (AI-lab blogs and tech newsrooms), Hacker News, Reddit, Hugging Face daily papers, and a personal X/Twitter queue.
2. Picks the single best story for a general audience.
3. Writes a detailed, engaging post in a **sharp analyst** voice that leaves readers with something to talk about.
4. Renders a minimal, aesthetic image card (rotating between 3 templates).
5. Sends the draft and image to the owner on **Telegram for approval**.
6. On approval, sends the final copy; the owner posts it manually and replies `done`. Telegram reminders repeat until then. (Phase 3 auto-posting exists but is optional.)

**Golden rule:** nothing is ever posted to LinkedIn without explicit approval from the owner on Telegram.

---

## Tech stack (everything should run on free tiers)
- **Language:** Python 3.11+
- **Scheduler and runner:** GitHub Actions (cron). No servers.
- **State:** JSON files in `state/`, committed back to the repo by the workflow.
- **LLM:** a provider-agnostic wrapper in `src/llm.py`.
  - The default is the free tier of Google Gemini (`LLM_PROVIDER=gemini`).
  - Groq (`LLM_PROVIDER=groq`) is a free fallback.
  - Anthropic Claude (`LLM_PROVIDER=anthropic`) is the paid upgrade.
  - The model name always comes from the `LLM_MODEL` env var. Never hardcode it, and check each provider's docs for current model names and free-tier limits.
- **Images:** HTML/CSS templates rendered to PNG with Playwright (headless Chromium). Fonts are bundled locally in `assets/fonts/` and nothing is fetched at render time.
- **Approval:** Telegram Bot API, using polling (`getUpdates`) only. No webhooks.
- **Posting:** LinkedIn Posts API (Phase 3).

---

## Repo structure
```
.
├── CLAUDE.md
├── README.md                  # setup steps for the owner (keys, bot, secrets)
├── requirements.txt
├── .github/workflows/
│   ├── draft.yml              # daily: collect → pick → write → render → send to Telegram
│   └── poll.yml               # every 30 min: read Telegram replies → act
├── src/
│   ├── main_draft.py          # entrypoint for draft.yml
│   ├── main_poll.py           # entrypoint for poll.yml
│   ├── pipeline.py            # shared draft/approve steps used by both entrypoints
│   ├── sources/
│   │   ├── hackernews.py
│   │   ├── reddit.py
│   │   ├── huggingface.py
│   │   ├── news.py            # RSS: AI-lab blogs + tech newsrooms
│   │   └── x_queue.py         # tweets the owner forwarded via Telegram
│   ├── rank.py                # scoring + LLM final pick
│   ├── write.py               # post + headline generation, banned-phrase check
│   ├── render.py              # HTML → PNG via Playwright
│   ├── telegram.py
│   ├── linkedin.py            # Phase 3
│   ├── llm.py
│   └── config.py              # reads env vars, constants
├── prompts/
│   ├── pick.md
│   ├── write_post.md
│   └── headline.md
├── templates/
│   ├── clean_white.html
│   ├── dark_accent.html
│   └── warm_editorial.html
├── assets/fonts/
├── state/
│   ├── posted.json            # URLs/IDs already used (dedupe)
│   ├── pending.json           # current draft awaiting approval
│   ├── x_queue.json           # forwarded tweets waiting to be used
│   ├── telegram_offset.json   # last processed update_id
│   └── meta.json              # reminder bookkeeping
└── tests/
```

---

## Daily flow

### `draft.yml` runs at 08:00 IST (cron `30 2 * * *` UTC)
1. **Process the X queue first.** Run the poll logic once so any tweets forwarded overnight get queued.
2. **Collect** candidates from every source from the last ~36 hours. Each candidate is normalized to:
   `{id, source, title, url, summary, score, created_at, raw_text}`
3. **Dedupe** against `state/posted.json`, matching on URL and on fuzzy title.
4. **Rank.** Items in the X queue get a priority boost because they reflect the owner's own taste. Take the top ~12 by a heuristic score (engagement normalized per source, or outlet weight for news; plus recency; plus a "buzz" boost when several outlets cover the same development, which is collapsed to one entry). The LLM then picks one using `prompts/pick.md`.
5. **Fetch more context** for the chosen item where possible (article text, the full paper body from arXiv HTML for Hugging Face papers, top HN comment) so the post can go into real detail.
   - **Research step (`src/research.py`)** runs for every owner-forwarded tweet, and for any story whose context is under ~2,500 characters. One LLM call (`prompts/research.md`) plans 2–3 news queries and 0–2 background terms. The step then gathers the pages linked in the tweet, up to 3 articles from different outlets (Bing News RSS), Wikipedia background, and a related HN thread. The Source line credits up to two of those outlets, and the Telegram draft lists every research link so the owner can verify.
6. **Write** the post (`prompts/write_post.md`) and a separate short headline for the image (`prompts/headline.md`). Validate the result (see Writing rules). If validation fails, regenerate, up to 3 tries.
7. **Render** the image using the template for the day (day-of-year mod 3).
8. **Send to Telegram:** the photo, the post text, the source link, and the instructions "Reply: ok / redo / skip / or send edited text".
9. Save the draft to `state/pending.json` with status `awaiting_approval`, then commit the state.

### `poll.yml` runs every 30 minutes
Read new Telegram updates since the stored offset. Only accept messages from `TELEGRAM_CHAT_ID` and ignore everyone else. Handle each message as follows:
- **`ok` / `approve` / 👍:**
  - Manual mode (default): send back a "final copy" message (text, image, link for the first comment) for manual posting and mark the item `approved`. The owner replies **`done` / `posted`** once it's live, which marks it `posted`.
  - Phase 3: post to LinkedIn, then reply with the post link.
- **`redo`:** regenerate the post and headline for the same story, re-render, and send again.
- **`next`:** skip this story, pick the next-best candidate, and send a new draft.
- **`skip`:** no post today. Mark the item as skipped.
- **Daily posting reminder:** at each hour in `REMINDER_HOURS` (IST, default `12,18`), if today's draft is still awaiting approval or approved-but-not-done, send one reminder (for approved drafts, resend the final copy).
- **Any other text longer than 40 characters:** treat it as the owner's edited post. Re-render the image if the headline changed, then confirm with a preview and ask for `ok`.
- **A message containing an x.com/twitter.com link:** add it to `state/x_queue.json` and reply "Queued ✓".
  - If the owner includes text with the link, use that text as `raw_text`.
  - Otherwise, try a best-effort fetch of the tweet text. Unofficial embed endpoints are fragile, so failure is fine; fall back to asking the owner to paste the text.

Save the new offset and commit the state. Note that GitHub cron can be delayed by 5–20 minutes, which is acceptable.

---

## Sources

**Hacker News:** use the Algolia API (free, no key).
- Endpoint: `https://hn.algolia.com/api/v1/search?tags=story&numericFilters=created_at_i>{ts},points>80`
- Run it with AI keywords (`AI, LLM, OpenAI, Anthropic, Gemini, model, neural, GPT, Claude, agent, robotics`), then filter the results.

**Reddit:** use PRAW with a free personal "script" app (`REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`).
- Subreddits: `MachineLearning`, `LocalLLaMA`, `artificial`, `singularity`, `OpenAI`.
- Take the top posts of the day with score above 100.

**Hugging Face:** `https://huggingface.co/api/daily_papers` (free). Rank by upvotes. The abstract, plus the paper body from `https://arxiv.org/html/{id}` when available, provides the grounding context.

**AI news (RSS, free, no keys):** `src/sources/news.py` lists the feeds with a weight each. Official lab blogs (OpenAI, Google DeepMind, Google AI) weigh most, then newsrooms (MIT Technology Review, The Verge, TechCrunch, Ars Technica, Wired, The Decoder), then smaller blogs (NVIDIA, Simon Willison). Anthropic has no RSS feed. Keep only items from the lookback window.

**X/Twitter:** only via the owner forwarding tweets to the Telegram bot. Do **not** scrape X or use paid X API tiers.

Each source module must fail gracefully: log the error, return `[]`, and let the pipeline continue.

---

## Writing rules (voice spec)

**Audience:** smart professionals who don't follow AI closely. They should finish the post understanding what specifically happened, how it works, and why it matters to them, and leave with something to bring up at work.

**Voice:** a sharp, engaging analyst with a point of view.
- Confident, curious, energetic, but grounded. Energy comes from specifics and a clear angle, never hype or exclamation marks.
- Plain words, short punchy sentences, varied rhythm.
- One clear angle per post (e.g. "how X is actually used for Y", a surprising consequence, who wins/loses, a counterintuitive tension).
- Takes a clear stance while staying honest about uncertainty.
- Goes into the details: who, what exactly, how it works, the key numbers, what's new, specific limitations.

**Structure (about 200–320 words):**
1. **Hook (line 1, under 15 words):** punchy and specific, true to the source. No clickbait.
2. **What happened and how it works:** 3–5 short paragraphs built around the angle. Explain jargon in passing.
3. **Why it matters:** the concrete real-world implication for work, money, everyday life, or society.
4. **The take:** a clear stance, one memorable/quotable line, and the specific caveats.
5. **A closing question** that people will want to argue about: a concrete choice or dilemma (not "Thoughts?").
6. **Credit:** a line such as `Source: {publication/author}`. The link itself goes in the first comment in Phase 3; in Phase 1–2, include it in the Telegram message only.

**Formatting:**
- Short paragraphs of 1–3 lines with blank lines between them.
- At most 1 emoji, and usually none. No exclamation marks.
- 0–3 hashtags at the end.
- No bold Unicode text and no bullet-point walls.

**Banned phrases** (validated in code; regenerate if any appear):
game-changer, revolutionary, groundbreaking, "excited to share", "let's dive in", "in today's fast-paced world", "the future is here", buckle up, "mind-blowing", unleash, delve, landscape, "it's not just X, it's Y", "here's the thing", "the best part?", "Thoughts?"

Avoid em-dash overuse: at most one per post.

**Accuracy rules (critical):**
- Use only facts present in the fetched source material. Never invent numbers, quotes, names, or dates.
- If the source is thin, say less rather than embellish.
- Never claim the owner did, tested, or built something.
- Paraphrase fully, and do not copy sentences from the source.

**Headline for the image:** 4–9 words, punchy and built on the angle (e.g. "How AI is quietly running high-frequency trading"). Not the hook verbatim. Fully supported by the post. No ending punctuation except "?".

**Example of the target voice** (structure only; see `prompts/write_post.md` for the fuller, current example):
> Small AI models are quietly catching up with the giants.
>
> A new open model released this week performs close to systems many times its size on common reasoning tests.
>
> That matters because smaller models are cheaper to run and can work on a laptop or phone, not just in a data center.
>
> The caveat: benchmark scores and real-world usefulness aren't the same thing. The interesting test is what people build with it over the next few months.
>
> If capable AI could run privately on your own device, what's the first thing you'd use it for?
>
> Source: Hugging Face

---

## Image cards
- **Size:** 1080×1350 (4:5 portrait, which takes the most room in the LinkedIn feed).
- **Content:** headline (large), a small source tag (e.g. "via Hugging Face"), the owner's name or handle (`AUTHOR_NAME` env var) in a corner, and generous whitespace. Nothing else.
- **Templates:** rotate by `day_of_year % 3`.
  1. `clean_white.html`: white background, near-black bold sans-serif headline (Inter or similar), thin accent rule.
  2. `dark_accent.html`: deep charcoal background, off-white headline, one soft accent color for the source tag.
  3. `warm_editorial.html`: warm beige background, editorial serif headline (Fraunces or Playfair), muted brown details.
- **Fonts:** download the TTF/WOFF2 files into `assets/fonts/` (all must be open-licensed) and load them via `@font-face`.
- **Long headlines:** auto-shrink the font size so the headline always fits within the safe margins (at least 96px padding).
- Save the output to `out/{date}.png` (gitignored). Send it to Telegram; never commit images.

---

## LinkedIn posting (Phase 3)
- The owner creates a LinkedIn developer app, adds the products **Sign In with LinkedIn using OpenID Connect** and **Share on LinkedIn**, and authorizes the scopes `openid profile w_member_social`. LinkedIn requires the app to be associated with a Company Page.
- Provide `scripts/linkedin_auth.py`, a one-time local OAuth helper that prints the access token. The owner stores it as a GitHub secret.
- Get the person URN from `/v2/userinfo` (`sub`), formatted as `urn:li:person:{sub}`.
- **Image upload:** call the Images API `initializeUpload`, PUT the PNG to the returned URL, then create the post via `/rest/posts` with the image URN. Send `LinkedIn-Version` (YYYYMM, configurable) and `X-Restli-Protocol-Version: 2.0.0` headers. Check the current LinkedIn docs for exact payloads.
- After posting, add the source link as the first comment if the API permits it; otherwise skip that step.
- **Token expiry:** tokens last about 60 days. Store the issue date in an env var or secret and send a Telegram reminder from day 50 onward.
- **Fallback:** `POST_MODE=manual` (the default until Phase 3 is verified) sends the final copy to Telegram instead of posting.

---

## Secrets / env vars (GitHub Actions secrets)
```
LLM_PROVIDER, LLM_MODEL
GEMINI_API_KEY | GROQ_API_KEY | ANTHROPIC_API_KEY
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
AUTHOR_NAME
POST_MODE                      # manual | auto
LINKEDIN_ACCESS_TOKEN, LINKEDIN_TOKEN_ISSUED   # Phase 3
```
Never log or print secret values. Workflows need `permissions: contents: write` to commit state.

---

## Build phases and acceptance criteria

### Phase 1: drafts to Telegram
- All 3 automated sources plus the X queue work, and each fails gracefully.
- Ranking, picking, and writing work, and the banned-phrase validator passes.
- The Telegram bot sends drafts and handles `ok`, `redo`, `next`, `skip`, edits, and tweet links.
- `python -m src.main_draft --dry-run` prints the draft locally without sending anything.
- **Done when:** the owner receives a good draft every morning for 5 days straight.

### Phase 2: image cards
- All 3 templates render cleanly. Headlines auto-fit, fonts load, and the output is 1080×1350.
- `python -m src.render --preview` renders all 3 templates with a sample headline for review.

### Phase 3: auto-post to LinkedIn
- The OAuth helper works, image and text posts succeed, and the token-expiry reminder fires.
- **Done when:** one approved post publishes successfully with `POST_MODE=auto`.

---

## Coding conventions
- Small, readable modules with type hints and docstrings on the public functions.
- Every external call has a timeout and retries with backoff.
- Use `logging`, not `print`, in pipeline code.
- Every entrypoint supports `--dry-run`, which sends nothing, posts nothing, and commits nothing.
- Tests in `tests/` cover:
  - source normalization, using fixture JSON files
  - dedupe
  - the banned-phrase validator
  - Telegram command parsing
  - template selection
- Keep LLM calls to about 5 per day so they stay well within free-tier limits.
- When unsure about a current API detail (LinkedIn, Telegram, LLM providers), check the official docs rather than guessing.
