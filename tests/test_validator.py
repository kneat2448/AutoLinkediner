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
    assert any("question" in p for p in write.validate_post(GOOD.rsplit("\n", 1)[0] + "\n\nThe end."))
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
