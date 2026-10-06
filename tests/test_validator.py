import pytest

from src import write

GOOD = """Small AI models are quietly catching up with the giants.

A new open model released this week performs close to systems many times its size on common reasoning tests. It was trained with a cleaner, more carefully chosen set of examples rather than simply more data.

The researchers say the gain came mostly from training on fewer but carefully checked examples, with each answer verified before it was used. They also report that the model learned to double-check its own work before giving a final answer, which helped most on math-style questions.

That matters because smaller models are cheaper to run and can work on a laptop or phone, not just in a data center. For a small business or a school, that changes what is affordable and what can stay private.

The caveat: benchmark scores and real-world usefulness aren't the same thing. Tests reward specific skills, and everyday work is messier than any test. The interesting signal will be what people actually build with it over the next few months, and whether it holds up outside the lab.

If capable AI could run privately on your own device, what's the first thing you'd use it for?"""


def test_good_post_passes():
    assert write.validate_post(GOOD, ["#AI"]) == []


@pytest.mark.parametrize("phrase", [
    "This is a game-changer.", "a game changer", "Revolutionary stuff.", "groundbreaking work",
    "I'm excited to share", "Let's dive in.", "Let’s dive in.", "In today's fast-paced world,",
    "The future is here.", "Buckle up.", "Mind-blowing.", "It will unleash creativity.",
    "We delve into it.", "the AI landscape", "It's not just a tool, it's a teammate.",
    "Here's the thing:", "The best part? It's free.", "Thoughts?",
])
def test_banned_phrases_detected(phrase):
    assert write.find_banned(phrase), phrase


def test_banned_does_not_false_positive():
    assert write.find_banned("The landing page shows thoughtful design. Not just yet.") == []


def test_post_problems():
    assert any("banned" in p for p in write.validate_post(GOOD.replace("quietly", "a game-changer,")))
    assert any("words" in p for p in write.validate_post("Too short?"))
    assert any("em dash" in p for p in write.validate_post(GOOD.replace("The caveat:", "The caveat — a — big one:")))
    assert any("hook" in p for p in write.validate_post(
        "This is a very long first line that goes on and on well past fifteen words for sure\n\n" + GOOD))
    # A dry landing line is a valid ending now (no question required)
    assert write.validate_post(GOOD.rsplit("\n", 1)[0] + "\n\nThe queue got smarter. Nobody lost a job.") == []
    assert any("hashtags" in p for p in write.validate_post(GOOD, ["#a", "#b", "#c", "#d"]))
    assert any("emoji" in p for p in write.validate_post(GOOD.replace("giants.", "giants 🚀🔥.")))
    assert any("Unicode" in p for p in write.validate_post(GOOD.replace("Small", "𝗦𝗺𝗮𝗹𝗹")))


def test_split_post_strips_source_and_hashtags():
    body, tags = write.split_post(GOOD + "\n\nSource: Hugging Face\n\n#AI #OpenSource")
    assert tags == ["#AI", "#OpenSource"]
    assert "Source:" not in body
    assert body.endswith("?")


def test_draft_text_order():
    d = write.Draft("Body?", ["#AI"], "Hugging Face Daily Papers")
    assert d.text == "Body?\n\nSource: Hugging Face Daily Papers\n\n#AI"


def test_headline_validation_and_cleaning():
    assert write.validate_headline("Small models are catching up fast") == []
    assert write.validate_headline("Can small models replace the giants?") == []
    assert write.validate_headline("Too short") != []
    assert write.validate_headline("Small models are catching up fast.") != []
    assert write.clean_headline('Headline: "Small models are catching up fast."') == "Small models are catching up fast"


@pytest.mark.parametrize("phrase", [
    "It's not a chatbot. It's a trader.", "This isn't hype, it's math.", "It is not just a model, but a platform.",
    "A seamless rollout.", "Firms can leverage it.", "This will unlock value.", "Powered by GPUs.",
    "At the end of the day, speed wins.", "Whether you're a founder or an engineer, listen.",
    "Why does this matter?", "So what does this mean?", "An insane result.", "A massive model.", "Agree?",
])
def test_firewall_tells_detected(phrase):
    assert write.find_banned(phrase), phrase


@pytest.mark.parametrize("opener", ["Most people think AI is slow.", "Here's what happened.", "Imagine a model that trades."])
def test_generic_openers_rejected(opener):
    assert any("generic" in p for p in write.validate_post(opener + "\n\n" + GOOD))


def test_echo_lines_detected():
    body = "More leads.\nMore calls.\nMore revenue.\n\n" + GOOD
    assert write.echo_lines(body) == ["more"]
    assert any("same word" in p for p in write.validate_post(body))


def test_one_short_list_allowed():
    listed = GOOD.replace("That matters because", "The results:\n• 3B parameters\n• 10 tests\n• one laptop\n\nThat matters because")
    assert write.validate_post(listed) == []
    many = "\n".join(f"• item {i}" for i in range(7))
    assert any("bullet" in p for p in write.validate_post(GOOD + "\n\n" + many))


def test_split_alternates():
    raw = "Post body?\n\n#AI\n=== ALTERNATE OPENINGS ===\n1. Bare number: ...\nPick: 1"
    body, tags = write.split_post(raw)
    assert body == "Post body?" and tags == ["#AI"]
    assert write.split_alternates(raw)[1].startswith("1. Bare number")


def test_voice_firewall_applies_clean_draft(monkeypatch):
    clean = GOOD.replace("quietly catching up with", "now matching")
    monkeypatch.setattr(write.llm, "complete", lambda *a, **k: (
        "SCORE: 6\n- \"x\" trips parallel repetition\n=== CLEAN DRAFT ===\n" + clean))
    out = write.voice_firewall(write.Draft(GOOD, [], "Src"), "ctx")
    assert out.body == clean and out.voice_score == 6 and len(out.notes) == 1


def test_voice_firewall_keeps_original_when_rewrite_is_worse(monkeypatch):
    monkeypatch.setattr(write.llm, "complete", lambda *a, **k: "SCORE: 5\n=== CLEAN DRAFT ===\nToo short. A game-changer.")
    out = write.voice_firewall(write.Draft(GOOD, [], "Src"), "ctx")
    assert out.body == GOOD and out.voice_score == 5


def test_voice_firewall_survives_llm_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(write.llm, "complete", boom)
    assert write.voice_firewall(write.Draft(GOOD, [], "Src"), "ctx").body == GOOD
