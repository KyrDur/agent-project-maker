"""Tests for app.agent_runtime.model_factory — LLM provider instantiation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_model_cache_between_tests():
    from app.agent_runtime.model_factory import clear_model_cache

    clear_model_cache()
    yield
    clear_model_cache()


class TestCreateChatModel:
    """Tests for create_chat_model()."""

    def test_openai_provider(self):
        mock_cls = MagicMock()
        with (
            patch.dict(
                "app.agent_runtime.model_factory.PROVIDER_MAP",
                {"openai": mock_cls},
            ),
        ):
            from app.agent_runtime.model_factory import create_chat_model

            result = create_chat_model("openai", "gpt-4o", api_key="sk-test")

        mock_cls.assert_called_once()
        kwargs = mock_cls.call_args[1]
        assert kwargs["model"] == "gpt-4o"
        assert kwargs["api_key"] == "sk-test"
        assert result is mock_cls.return_value

    def test_anthropic_provider(self):
        mock_cls = MagicMock()
        with (
            patch.dict(
                "app.agent_runtime.model_factory.PROVIDER_MAP",
                {"anthropic": mock_cls},
            ),
        ):
            from app.agent_runtime.model_factory import create_chat_model

            result = create_chat_model("anthropic", "claude-3-opus", api_key="sk-ant-test")

        mock_cls.assert_called_once()
        kwargs = mock_cls.call_args[1]
        assert kwargs["model"] == "claude-3-opus"
        assert kwargs["api_key"] == "sk-ant-test"
        assert result is mock_cls.return_value

    def test_google_provider(self):
        mock_cls = MagicMock()
        with (
            patch.dict(
                "app.agent_runtime.model_factory.PROVIDER_MAP",
                {"google": mock_cls},
            ),
        ):
            from app.agent_runtime.model_factory import create_chat_model

            result = create_chat_model("google", "gemini-pro", api_key="goog-key")

        mock_cls.assert_called_once()
        kwargs = mock_cls.call_args[1]
        assert kwargs["model"] == "gemini-pro"
        assert kwargs["api_key"] == "goog-key"
        assert result is mock_cls.return_value

    def test_unknown_provider_defaults_to_openai_class(self):
        """Unknown provider should fall back to ChatOpenAI (the default in .get())."""
        from app.agent_runtime.model_factory import PROVIDER_MAP

        # "ollama" is not in PROVIDER_MAP, so it falls through to the default
        assert "ollama" not in PROVIDER_MAP

    def test_unknown_provider_uses_default(self):
        """Unknown provider dispatches to the ChatOpenAI default."""
        mock_cls = MagicMock()
        with (
            patch("app.agent_runtime.model_factory.ChatOpenAI", mock_cls),
            patch.dict(
                "app.agent_runtime.model_factory.PROVIDER_MAP",
                clear=True,  # empty map so "ollama" misses
            ),
        ):
            from app.agent_runtime.model_factory import create_chat_model

            result = create_chat_model("ollama", "llama3", api_key="test-key")

        mock_cls.assert_called_once()
        kwargs = mock_cls.call_args[1]
        assert kwargs["model"] == "llama3"
        assert result is mock_cls.return_value

    def test_with_base_url(self):
        mock_cls = MagicMock()
        with patch.dict(
            "app.agent_runtime.model_factory.PROVIDER_MAP",
            {"openai": mock_cls},
        ):
            from app.agent_runtime.model_factory import create_chat_model

            create_chat_model("openai", "gpt-4o", api_key="k", base_url="http://localhost:11434")

        kwargs = mock_cls.call_args[1]
        assert kwargs["base_url"] == "http://localhost:11434"

    def test_no_base_url_pins_canonical_endpoint(self):
        """openai provider + 未指定 base_url → 强制 canonical OpenAI endpoint。

        OS env ``OPENAI_BASE_URL`` 绕过阻断守卫（即使通过 RunPod proxy / 公司内部 辅助工具
        等 export，也路由到 OpenAI 官方 endpoint）。
        """
        mock_cls = MagicMock()
        with patch.dict(
            "app.agent_runtime.model_factory.PROVIDER_MAP",
            {"openai": mock_cls},
        ):
            from app.agent_runtime.model_factory import create_chat_model

            create_chat_model("openai", "gpt-4o", api_key="k")

        kwargs = mock_cls.call_args[1]
        assert kwargs["base_url"] == "https://api.openai.com/v1"

    def test_api_key_none_falls_back_to_settings(self):
        """api_key=None 时从 PROVIDER_API_KEY_MAP 的 settings 项 fallback。

        新版 langchain-anthropic / langchain-openai 的 pydantic strict 会拒绝 None，因此
        显式 fallback 后若仍为 None，则从 kwargs 中排除（库环境变量 fallback）。
        """
        mock_cls = MagicMock()
        with (
            patch.dict(
                "app.agent_runtime.model_factory.PROVIDER_MAP",
                {"openai": mock_cls},
            ),
            patch.dict(
                "app.agent_runtime.model_factory.PROVIDER_API_KEY_MAP",
                {"openai": "settings-fallback"},
            ),
        ):
            from app.agent_runtime.model_factory import create_chat_model

            create_chat_model("openai", "gpt-4o", api_key=None)

        kwargs = mock_cls.call_args[1]
        assert kwargs["api_key"] == "settings-fallback"

    def test_api_key_none_with_no_settings_excluded_from_kwargs(self):
        """api_key 参数为 None、settings 也为 None 时，从 kwargs 中完全排除（让库
        直接从环境变量获取）。"""
        mock_cls = MagicMock()
        with (
            patch.dict(
                "app.agent_runtime.model_factory.PROVIDER_MAP",
                {"openai": mock_cls},
            ),
            patch.dict(
                "app.agent_runtime.model_factory.PROVIDER_API_KEY_MAP",
                {"openai": None},
            ),
        ):
            from app.agent_runtime.model_factory import create_chat_model

            create_chat_model("openai", "gpt-4o", api_key=None)

        kwargs = mock_cls.call_args[1]
        assert "api_key" not in kwargs

    def test_api_key_none_can_disable_settings_fallback(self):
        """User-facing runtime can opt out of env/system fallback entirely."""
        mock_cls = MagicMock()
        with (
            patch.dict(
                "app.agent_runtime.model_factory.PROVIDER_MAP",
                {"openai": mock_cls},
            ),
            patch.dict(
                "app.agent_runtime.model_factory.PROVIDER_API_KEY_MAP",
                {"openai": "settings-fallback"},
            ),
        ):
            from app.agent_runtime.model_factory import create_chat_model

            create_chat_model(
                "openai",
                "gpt-4o",
                api_key=None,
                allow_env_fallback=False,
            )

        kwargs = mock_cls.call_args[1]
        assert "api_key" not in kwargs

    def test_explicit_api_key_overrides_settings(self):
        """Explicit api_key parameter should take precedence over settings."""
        mock_cls = MagicMock()
        with (
            patch.dict(
                "app.agent_runtime.model_factory.PROVIDER_MAP",
                {"openai": mock_cls},
            ),
            patch.dict(
                "app.agent_runtime.model_factory.PROVIDER_API_KEY_MAP",
                {"openai": "settings-key"},
            ),
        ):
            from app.agent_runtime.model_factory import create_chat_model

            create_chat_model("openai", "gpt-4o", api_key="explicit-key")

        kwargs = mock_cls.call_args[1]
        assert kwargs["api_key"] == "explicit-key"

    def test_reuses_cached_model_for_same_config(self):
        mock_cls = MagicMock()
        mock_cls.side_effect = [MagicMock(name="first"), MagicMock(name="second")]
        with patch.dict(
            "app.agent_runtime.model_factory.PROVIDER_MAP",
            {"openai": mock_cls},
        ):
            from app.agent_runtime.model_factory import clear_model_cache, create_chat_model

            clear_model_cache()
            first = create_chat_model("openai", "gpt-4o", api_key="sk-same")
            second = create_chat_model("openai", "gpt-4o", api_key="sk-same")
            clear_model_cache()

        assert first is second
        assert mock_cls.call_count == 1

    def test_cache_key_uses_api_key_fingerprint(self):
        mock_cls = MagicMock()
        mock_cls.side_effect = [MagicMock(name="first"), MagicMock(name="second")]
        with patch.dict(
            "app.agent_runtime.model_factory.PROVIDER_MAP",
            {"openai": mock_cls},
        ):
            from app.agent_runtime.model_factory import clear_model_cache, create_chat_model

            clear_model_cache()
            first = create_chat_model("openai", "gpt-4o", api_key="sk-one")
            second = create_chat_model("openai", "gpt-4o", api_key="sk-two")
            clear_model_cache()

        assert first is not second
        assert mock_cls.call_count == 2


class TestCreateChatModelGpt5Family:
    """Tests for ``create_chat_model`` GPT-5 / o-series reasoning model guard.

    Reasoning models (gpt-5*, o1*, o3*, o4*) reject ``max_tokens`` and
    non-default ``temperature`` from the OpenAI Chat Completions API. They
    also burn output tokens on hidden reasoning chains, so a tight cap
    leaves the visible ``content`` empty even when the API responds 200 OK.
    """

    @staticmethod
    def _patched_create(model_name: str, **extra):
        from unittest.mock import MagicMock, patch

        mock_cls = MagicMock()
        with patch.dict(
            "app.agent_runtime.model_factory.PROVIDER_MAP",
            {"openai": mock_cls},
        ):
            from app.agent_runtime.model_factory import create_chat_model

            create_chat_model("openai", model_name, api_key="sk-test", **extra)
        return mock_cls.call_args[1]

    def test_gpt5_drops_max_tokens_and_forwards_max_completion_tokens(self):
        kwargs = self._patched_create("gpt-5.5-2026-04-23", max_tokens=512)
        assert "max_tokens" not in kwargs
        # langchain-openai 0.3+ 仅通过 top-level kwarg forward
        assert kwargs["max_completion_tokens"] == 512

    def test_gpt5_drops_non_default_temperature(self):
        kwargs = self._patched_create("gpt-5", temperature=0.7)
        assert "temperature" not in kwargs

    def test_gpt5_default_completion_tokens_when_caller_omits_cap(self):
        """No max_tokens passed → default 4096 to avoid empty content regression."""
        kwargs = self._patched_create("gpt-5")
        assert kwargs["max_completion_tokens"] == 4096

    def test_o3_family_also_guarded(self):
        kwargs = self._patched_create("o3-mini")
        assert "max_tokens" not in kwargs
        assert kwargs["max_completion_tokens"] == 4096

    def test_non_gpt5_keeps_max_tokens_top_level(self):
        """gpt-4o is NOT a reasoning family — max_tokens stays as-is."""
        kwargs = self._patched_create("gpt-4o", max_tokens=256)
        assert kwargs["max_tokens"] == 256
        assert "max_completion_tokens" not in kwargs

    def test_gpt5_no_userwarning_from_model_kwargs(self):
        """``max_completion_tokens`` 位于 top-level — 若放进 model_kwargs，
        LangChain 会在 UserWarning 后移除，因此不会向 OpenAI forward。"""
        kwargs = self._patched_create("gpt-5.5", max_tokens=200)
        model_kw = kwargs.get("model_kwargs", {})
        assert "max_completion_tokens" not in model_kw


class TestCreateChatModelBaseUrlGuard:
    """``OPENAI_BASE_URL`` env 绕过阻断守卫。

    ChatOpenAI 未指定 base_url 时，OpenAI Python SDK 会从 ``OPENAI_BASE_URL``
    env fallback。用户终端若把 RunPod proxy / Claude Code helper / 公司内部
    代理 export 出去，就会路由到并非 OpenAI 官方 endpoint 的错误主机，
    导致 404 回归。provider 通过 canonical endpoint 显式 set 来阻断。
    """

    @staticmethod
    def _patched_create(provider: str, model_name: str, base_url=None):
        from unittest.mock import MagicMock, patch

        mock_cls = MagicMock()
        with patch.dict(
            "app.agent_runtime.model_factory.PROVIDER_MAP",
            {provider: mock_cls},
        ):
            from app.agent_runtime.model_factory import create_chat_model

            create_chat_model(provider, model_name, api_key="sk-test", base_url=base_url)
        return mock_cls.call_args[1]

    def test_openai_base_url_pinned_when_caller_omits(self):
        """openai provider + 未指定 base_url → 强制 canonical endpoint（阻断 RunPod env）。"""
        kwargs = self._patched_create("openai", "gpt-5.5")
        assert kwargs["base_url"] == "https://api.openai.com/v1"

    def test_openrouter_base_url_pinned_when_caller_omits(self):
        """openrouter provider 也使用相同守卫 — qwen/llama/* 等 OpenRouter 模型。"""
        kwargs = self._patched_create("openrouter", "qwen/qwen3.6-27b")
        assert kwargs["base_url"] == "https://openrouter.ai/api/v1"

    def test_explicit_base_url_takes_precedence(self):
        """caller 显式指定 base_url → 绕过守卫（保留用户意图）。"""
        custom = "https://custom.proxy.example/v1"
        kwargs = self._patched_create("openai", "gpt-4o", base_url=custom)
        assert kwargs["base_url"] == custom

    def test_anthropic_no_base_url_pin(self):
        """anthropic 不是 ChatOpenAI，因此不受 base_url 守卫影响。"""
        kwargs = self._patched_create("anthropic", "claude-sonnet-4-6")
        assert "base_url" not in kwargs


class TestContextWindowProfileInjection:
    """Phase 0 — context_window → 注入 model.profile['max_input_tokens']。

    让 deepagents 自动 SummarizationMiddleware 的 compute_summarization_defaults
    使用我们的单一 source(context_window) 作为阈值。
    """

    def test_context_window_not_forwarded_to_model_constructor(self):
        """context_window 用于 profile 注入，不是模型创建 kwarg — 禁止泄漏。"""
        mock_cls = MagicMock()
        with patch.dict(
            "app.agent_runtime.model_factory.PROVIDER_MAP",
            {"openai_compatible": mock_cls},
        ):
            from app.agent_runtime.model_factory import create_chat_model

            create_chat_model(
                "openai_compatible",
                "gw-model",
                api_key="sk-x",
                base_url="https://gw/v1",
                context_window=1500,
            )
        kwargs = mock_cls.call_args[1]
        assert "context_window" not in kwargs

    def test_profileless_model_flips_to_fraction_trigger(self):
        """openai_compatible（无配置）：注入 cw → 固定 170k → ('fraction', 0.85)。"""
        from deepagents.middleware.summarization import compute_summarization_defaults

        from app.agent_runtime.model_factory import create_chat_model

        model = create_chat_model(
            "openai_compatible",
            "gw-model",
            api_key="sk-x",
            base_url="https://gw/v1",
            context_window=1500,
        )
        assert (model.profile or {}).get("max_input_tokens") == 1500
        assert compute_summarization_defaults(model)["trigger"] == ("fraction", 0.85)

    def test_no_context_window_keeps_default_threshold(self):
        """未指定 cw：保持配置原样 → 保留现有行为(profile-less = 固定 170k)。"""
        from deepagents.middleware.summarization import compute_summarization_defaults

        from app.agent_runtime.model_factory import create_chat_model

        model = create_chat_model(
            "openai_compatible",
            "gw-model",
            api_key="sk-x",
            base_url="https://gw/v1",
        )
        assert model.profile is None
        assert compute_summarization_defaults(model)["trigger"] == ("tokens", 170000)

    def test_our_window_overrides_builtin_profile(self):
        """正式模型（具有内置配置）也由我们的 cw 作为单一 source 进行 override。"""
        from app.agent_runtime.model_factory import create_chat_model

        model = create_chat_model(
            "anthropic", "claude-sonnet-4-6", api_key="sk-x", context_window=200000
        )
        assert (model.profile or {}).get("max_input_tokens") == 200000

    def test_distinct_windows_are_not_cache_shared(self):
        """cw 不同时拆分缓存槽位 — tiny-window 构建 不会污染运行实例。"""
        from app.agent_runtime.model_factory import create_chat_model

        small = create_chat_model(
            "openai_compatible",
            "same",
            api_key="sk-x",
            base_url="https://gw/v1",
            context_window=1500,
        )
        big = create_chat_model(
            "openai_compatible",
            "same",
            api_key="sk-x",
            base_url="https://gw/v1",
            context_window=200000,
        )
        assert small is not big
        assert (small.profile or {}).get("max_input_tokens") == 1500
        assert (big.profile or {}).get("max_input_tokens") == 200000

    def test_invalid_window_is_ignored(self):
        """忽略 0/负数/非整数 cw — 不注入 profile。"""
        from app.agent_runtime.model_factory import create_chat_model

        model = create_chat_model(
            "openai_compatible",
            "gw-model",
            api_key="sk-x",
            base_url="https://gw/v1",
            context_window=0,
        )
        assert model.profile is None
