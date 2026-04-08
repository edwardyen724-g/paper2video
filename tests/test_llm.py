from paper2video.llm import FakeLLMClient, LLMClient


def test_fake_llm_returns_queued_responses():
    llm: LLMClient = FakeLLMClient(responses=["first", "second"])
    assert llm.complete("prompt a") == "first"
    assert llm.complete("prompt b") == "second"


def test_fake_llm_records_prompts():
    llm = FakeLLMClient(responses=["x"])
    llm.complete("hello")
    assert llm.calls == [("hello", None)]


def test_fake_llm_json_mode():
    llm = FakeLLMClient(responses=['{"k": 1}'])
    result = llm.complete_json("give me json")
    assert result == {"k": 1}
