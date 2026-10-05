Write one LinkedIn post about the AI story below.

## Audience
Smart professionals who don't follow AI closely: managers, founders, engineers, designers, lawyers. When they finish reading, they should understand **what specifically happened, how it works, and why it matters to them**, and they should have **something to bring up at work**.

## Voice
A sharp, engaging analyst with a point of view. Confident, curious, and energetic, but grounded. The energy comes from interesting specifics and a clear angle, never from hype words, exclamation marks, or exaggeration. Plain words, short punchy sentences, varied rhythm. It should read like a smart friend who just dug into the story and can't wait to tell you the interesting part.

## Step 1: find the angle
Before writing, decide the single most interesting angle and build the whole post around it. Good angles:
- **How it actually works or how it's actually used:** "How X is used for Y" (e.g. how trading firms use AI to make split-second decisions).
- **The surprising consequence:** what this quietly changes for a job, an industry, or a habit.
- **Who wins and who loses.**
- **The counterintuitive tension:** it's better *and* worse, cheaper *but* riskier, etc.
- **The hidden mechanism:** the clever trick behind the headline.

## Step 2: go into the details
Use the source material to give the substance, not just the headline:
- **Who** did it (the company, lab, or university, if named) and **what exactly** they built, found, or announced.
- **How it works**, in plain language. One vivid, accurate analogy or concrete example is welcome.
- **The key specifics:** the 1–3 most meaningful numbers, results, or design choices, each with a few words on what it means.
- **What's new** compared with before.
- **The specific limitations** (small test, early preprint, only one model, cost, unproven in the real world), not a generic "time will tell".

Skip details a non-expert wouldn't care about (dataset names, acronyms, model sizes) unless you explain why they matter.

## Step 3: give them something to talk about
- Include one **memorable, quotable line**: a crisp reframing, implication, or prediction the reader could repeat to a colleague. If it's your own view, make that clear ("My read:", "The way I see it:").
- In the take, **commit to a clear stance**. Don't hedge everything. Be honest about uncertainty, but say what you think it means.
- End with a **specific question people will want to argue about**. Offer a concrete choice or dilemma, e.g. "Would you let an AI negotiate your contract, or is that a line you'd keep for humans?". Not a generic "What do you think?".

## Structure (about 200–320 words total)
1. **Hook:** the first line, under 15 words. Punchy and specific: a surprising fact from the source, a sharp "how" or "why" framing, or a bold claim the post backs up. It must be true to the source. No clickbait, no questions that the post doesn't answer.
2. **What happened and how it works:** 3–5 short paragraphs built around your angle.
3. **Why it matters:** the concrete, real-world implication for work, money, everyday life, or society.
4. **The take:** your stance, the quotable line, and the specific caveats.
5. **The closing question.** It must be the last line of the body and end with "?".
6. Optionally, a final line with 0–3 relevant hashtags (e.g. #AI). Nothing else after that.

Do NOT write a "Source:" line. It is added automatically. Do NOT include links.

## Formatting
- Short paragraphs of 1–3 lines, separated by blank lines. Mix one-line punches with slightly longer explanations.
- At most one emoji, and usually none. No exclamation marks.
- No bold text, no markdown, no bullet points, no headings.
- At most one em dash (—) in the whole post.

## Never use these words or phrases
game-changer, revolutionary, groundbreaking, "excited to share", "let's dive in", "in today's fast-paced world", "the future is here", buckle up, mind-blowing, unleash, delve, landscape, "it's not just X, it's Y", "here's the thing", "the best part?", "Thoughts?"

## Accuracy (critical)
- Use ONLY facts present in the source material below. Never invent numbers, quotes, names, dates, or results.
- Copy numbers exactly as the source gives them. Don't calculate new ones.
- Punchy is not the same as exaggerated: never overstate what the source says. If results are early or modest, say so; that tension can *be* the angle.
- If the source material is thin, say less rather than embellish.
- Reader comments are opinions, not facts. Research results are the authors' claims, so attribute them ("the researchers report...").
- Never claim the author tested, used, or built anything.
- Paraphrase fully. Do not copy sentences from the source.

## Example of the target voice and depth (structure only, never reuse its content)
A model small enough for your laptop just matched the giants on reasoning.

Researchers at a university lab released an open model this week. On a set of common reasoning tests, they report it scores close to systems many times larger.

The trick isn't more data. It's better data.

Instead of feeding it huge piles of web text, they trained it on a smaller set of carefully checked, step-by-step solutions. Think of it as learning from a great textbook instead of the entire internet. They also taught it to double-check its own answers before committing, which they say drove most of the gains on math-style questions.

Why should you care? Small models are cheap to run and can live on a company's own servers, or even a phone. That means sensitive data never has to leave the building.

My read: the race is quietly shifting from "who has the biggest model" to "who has the best teaching material". That's a game far more companies can play.

The caveat is real, though. These are the authors' own results on standard tests, and benchmarks aren't the messy reality of daily work.

If a capable AI could run privately on your laptop, would you trust it with your company's data, or still keep it at arm's length?

## The story
Headline: {{TITLE}}
Credited source: {{SOURCE}}

Source material:
"""
{{CONTEXT}}
"""

Output only the post text, nothing before or after it.
