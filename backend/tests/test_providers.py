from types import SimpleNamespace

import groq
import httpx
import openai
import pytest

from app.config import ConfigError, Settings
from app.providers import build_provider
from app.providers.base import (
    FallbackProvider,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderQuotaExhausted,
    ProviderRateLimited,
    ProviderTimeout,
    strict_schema,
    with_retries,
)
from app.providers.chat import ChatCompletionsProvider, make_groq, make_openai
from app.providers.offline import OracleProvider, ScriptedProvider

REQ = httpx.Request("POST", "https://api.example/v1/chat/completions")


def settings(**kw) -> Settings:  # type: ignore[no-untyped-def]
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def test_missing_credentials_are_explained():
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        settings(ai_provider="groq").validate_startup()
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        settings(ai_provider="openai", openai_api_key="  ").validate_startup()
    with pytest.raises(ConfigError, match="FALLBACK_PROVIDER"):
        settings(ai_provider="groq", groq_api_key="x", fallback_provider="groq").validate_startup()
    settings(ai_provider="oracle").validate_startup()


def test_provider_switch_is_configuration_only():
    p = build_provider(settings(ai_provider="openai", openai_api_key="sk-test", openai_model="m-1"))
    assert (p.name, p.model) == ("openai", "m-1")
    p = build_provider(settings(ai_provider="groq", groq_api_key="gsk-test"))
    assert (p.name, p.model) == ("groq", "openai/gpt-oss-120b")
    assert build_provider(settings(ai_provider="oracle"), gold={}).name == "oracle"
    p = build_provider(settings(ai_provider="groq", groq_api_key="g", openai_api_key="o", fallback_provider="openai"))
    assert isinstance(p, FallbackProvider) and p.fallback.name == "openai"


def test_groq_capability_mode_depends_on_model():
    assert make_groq("k", "openai/gpt-oss-120b", 5, 0).strict is True
    assert make_groq("k", "llama-3.3-70b-versatile", 5, 0).strict is False
    o = make_openai("k", "gpt-6.1-sol", 5, 0)
    assert o.strict is True and o.send_temperature is False


def test_strict_schema_is_strict_mode_compatible():
    from app.domain import ContractExtractionLLM

    s = strict_schema(ContractExtractionLLM)

    def walk(n):  # type: ignore[no-untyped-def]
        if isinstance(n, dict):
            assert "$ref" not in n and "default" not in n
            if n.get("type") == "object" and "properties" in n:
                assert n["additionalProperties"] is False and set(n["required"]) == set(n["properties"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(s)


class FakeClient:
    def __init__(self, items):  # type: ignore[no-untyped-def]
        self.items = list(items)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):  # type: ignore[no-untyped-def]
        self.calls.append(kw)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def completion(content: str, finish: str = "stop"):  # type: ignore[no-untyped-def]
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)],
                           usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=200))


def provider(client, name="openai", sdk=openai, model="gpt-6.1-sol", strict=True, retries=2):  # type: ignore[no-untyped-def]
    return ChatCompletionsProvider(name, client, sdk, model, strict=strict, max_retries=retries,
                                   send_temperature=name == "groq")


def gen(p):  # type: ignore[no-untyped-def]
    return p.generate_json(system="s", user="u", schema_name="x", schema={"type": "object"})


def test_success_reports_usage_and_cost():
    c = FakeClient([completion('{"a": 1}')])
    r = gen(provider(c))
    assert r.data == {"a": 1} and r.input_tokens == 1000 and r.cost_usd == pytest.approx(0.004)
    assert c.calls[0]["response_format"]["type"] == "json_schema" and "temperature" not in c.calls[0]


def test_json_object_mode_puts_schema_in_prompt():
    c = FakeClient([completion('{"a": 1}')])
    gen(provider(c, name="groq", sdk=groq, model="llama-3.3-70b-versatile", strict=False))
    assert c.calls[0]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in c.calls[0]["messages"][0]["content"] and c.calls[0]["temperature"] == 0


def test_timeout_and_rate_limit_are_retried_with_bound(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    rl = openai.RateLimitError("slow down", response=httpx.Response(429, request=REQ), body={"code": "rate_limit"})
    c = FakeClient([openai.APITimeoutError(request=REQ), rl, completion('{"ok": true}')])
    r = gen(provider(c))
    assert r.attempts == 3
    c = FakeClient([openai.APITimeoutError(request=REQ)] * 3)
    with pytest.raises(ProviderTimeout):
        gen(provider(c))
    assert len(c.calls) == 3


def test_quota_auth_and_bad_output_are_not_retried(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    quota = openai.RateLimitError("no credits", response=httpx.Response(429, request=REQ),
                                  body={"code": "credit_balance_exhausted", "type": "insufficient_quota"})
    for err, typ in [(quota, ProviderQuotaExhausted),
                     (openai.AuthenticationError("bad key", response=httpx.Response(401, request=REQ), body=None),
                      ProviderAuthError)]:
        c = FakeClient([err, completion("{}")])
        with pytest.raises(typ):
            gen(provider(c))
        assert len(c.calls) == 1
    for bad in [completion("not json"), completion("[1,2]"), completion('{"a":', finish="length")]:
        c = FakeClient([bad, completion("{}")])
        with pytest.raises(ProviderBadResponse):
            gen(provider(c))
        assert len(c.calls) == 1


def test_groq_sdk_errors_map_to_same_types(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    c = FakeClient([groq.RateLimitError("429", response=httpx.Response(429, request=REQ), body=None)] * 3)
    with pytest.raises(ProviderRateLimited):
        gen(provider(c, name="groq", sdk=groq, retries=2))
    c = FakeClient([groq.BadRequestError("Generated JSON does not match the expected schema",
                                         response=httpx.Response(400, request=REQ), body=None)])
    with pytest.raises(ProviderBadResponse):
        gen(provider(c, name="groq", sdk=groq))


def test_fallback_is_recorded_and_only_for_infrastructure_errors():
    primary = ScriptedProvider([ProviderTimeout("groq", "t")], name="groq")
    fb = ScriptedProvider([{"x": 1}], name="openai")
    r = FallbackProvider(primary, fb).generate_json(system="s", user="u", schema_name="n", schema={})
    assert r.provider == "openai" and r.fallback_from == "groq" and r.notes
    primary = ScriptedProvider([ProviderBadResponse("groq", "bad")], name="groq")
    fb = ScriptedProvider([{"x": 1}], name="openai")
    with pytest.raises(ProviderBadResponse):
        FallbackProvider(primary, fb).generate_json(system="s", user="u", schema_name="n", schema={})
    assert fb.calls == []


def test_with_retries_counts_attempts():
    calls = []

    def fn():  # type: ignore[no-untyped-def]
        calls.append(1)
        if len(calls) < 2:
            raise ProviderTimeout("x", "t")
        return ScriptedProvider([{}]).generate_json()

    assert with_retries(fn, max_retries=1, sleep=lambda s: None).attempts == 2


def test_oracle_is_labelled_and_refuses_unknown_documents():
    o = OracleProvider({"D1": {"x": 1}})
    assert o.generate_json(system="", user="", schema_name="contract_extraction", schema={}, cache_key="D1").provider == "oracle"
    with pytest.raises(Exception, match="no ground truth"):
        o.generate_json(system="", user="", schema_name="contract_extraction", schema={}, cache_key="D2")


def test_rate_limit_waits_for_retry_after_header():
    waits = []
    rl = groq.RateLimitError("429", response=httpx.Response(429, request=REQ, headers={"retry-after": "17"}), body=None)
    c = FakeClient([rl, completion('{"ok": true}')])
    p = provider(c, name="groq", sdk=groq)
    r = with_retries(lambda: p._call("s", "u", "x", {}), max_retries=2, sleep=waits.append)
    assert r.attempts == 2 and waits == [17.0]
