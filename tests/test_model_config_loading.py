from secgo.config.config import _apply_settings_json


def test_default_model_and_planner_reuse_arbitrary_custom_provider() -> None:
    subscriptions = {}
    agents = {}
    model = _apply_settings_json(
        subscriptions,
        agents,
        {
            "llm": {
                "enabled": True,
                "provider": "SiliconFlow",
                "base_url": "https://api.siliconflow.cn/v1",
                "model": "Qwen/Qwen3-32B",
                "api_key": "secret",
            },
            "subscriptions": {},
            "agents": {},
        },
    )

    assert model == "Qwen/Qwen3-32B"
    assert subscriptions["coding"].provider == "SiliconFlow"
    assert agents["planner"].subscription == "coding"
    assert agents["planner"].modelId == "Qwen/Qwen3-32B"


def test_explicit_planner_subscription_wins_over_default_model() -> None:
    subscriptions = {
        "planner": type("Subscription", (), {
            "provider": "Anthropic-compatible",
            "baseURL": "https://planner.example/v1",
            "modelId": "planner-model",
            "apiKey": "planner-key",
        })(),
    }
    agents = {
        "planner": type("Agent", (), {
            "subscription": "planner",
            "modelId": "planner-model",
            "thinkingLevel": "medium",
        })(),
    }
    _apply_settings_json(
        subscriptions,
        agents,
        {
            "llm": {
                "provider": "custom-default",
                "base_url": "https://default.example/v1",
                "model": "default-model",
                "api_key": "default-key",
            },
        },
    )

    assert agents["planner"].subscription == "planner"
    assert agents["planner"].modelId == "planner-model"
    assert subscriptions["planner"].provider == "Anthropic-compatible"
