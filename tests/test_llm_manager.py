"""Tests for the multi-provider LLM manager, focused on the DeepSeek path."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.llm_manager import (
    LLMConfig,
    LLMModel,
    LLMProvider,
    LLMService,
)


class _DeepSeekTestConfig:
    TESTING = True
    SECRET_KEY = 'test-secret'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    ENABLE_BACKGROUND_JOBS = False
    ENABLE_DB_EXPLORER = False
    DB_EXPLORER_ALLOW_WRITES = False
    UPLOAD_FOLDER = '/tmp/battlebugs-test-uploads'
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    BUGS_PER_PAGE = 20
    BATTLES_PER_PAGE = 10
    DEEPSEEK_API_KEY = 'test-deepseek-key'
    DEEPSEEK_API_URL = 'https://api.deepseek.com'


@pytest.fixture()
def deepseek_app():
    from app import create_app, db
    app = create_app(_DeepSeekTestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_deepseek_provider_and_models_registered():
    assert LLMProvider.DEEPSEEK.value == 'deepseek'
    assert LLMModel.DEEPSEEK_V4_FLASH.provider == 'deepseek'
    assert LLMModel.DEEPSEEK_V4_FLASH.model_name == 'deepseek-v4-flash'
    assert LLMModel.DEEPSEEK_V4_PRO.model_name == 'deepseek-v4-pro'


def test_deepseek_generate_uses_openai_compat_client(deepseek_app):
    service = LLMService()

    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content='{"ok": true}'))]
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    with patch.object(service, '_get_deepseek_client', return_value=fake_client):
        out = service.generate(
            prompt='hello',
            model=LLMModel.DEEPSEEK_V4_FLASH,
            system_prompt='You are a test.',
            max_tokens=64,
            temperature=0.2,
        )

    assert out == '{"ok": true}'
    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs['model'] == 'deepseek-v4-flash'
    assert call_kwargs['max_tokens'] == 64
    assert call_kwargs['temperature'] == 0.2
    assert call_kwargs['messages'][0]['role'] == 'system'
    assert call_kwargs['messages'][-1] == {'role': 'user', 'content': 'hello'}


def test_deepseek_json_mode_sets_response_format(deepseek_app):
    service = LLMService()

    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content='{"value": 1}'))]
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    with patch.object(service, '_get_deepseek_client', return_value=fake_client):
        service.generate(
            prompt='give json',
            model=LLMModel.DEEPSEEK_V4_FLASH,
            json_mode=True,
        )

    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs['response_format'] == {'type': 'json_object'}


def test_deepseek_ignores_images_with_warning(deepseek_app, caplog):
    service = LLMService()

    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content='text-only'))]
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    with patch.object(service, '_get_deepseek_client', return_value=fake_client):
        out = service.generate(
            prompt='look at this',
            model=LLMModel.DEEPSEEK_V4_FLASH,
            image_data={'base64': 'aGVsbG8=', 'media_type': 'image/jpeg'},
        )

    assert out == 'text-only'
    # The call payload should not carry any image content — DeepSeek chat models are text-only.
    sent_messages = fake_client.chat.completions.create.call_args.kwargs['messages']
    for msg in sent_messages:
        content = msg['content']
        if isinstance(content, list):
            for block in content:
                assert block.get('type') != 'image_url'


def test_deepseek_missing_key_raises(deepseek_app):
    deepseek_app.config['DEEPSEEK_API_KEY'] = None
    service = LLMService()
    with pytest.raises(ValueError, match='DEEPSEEK_API_KEY'):
        service._get_deepseek_client()


def test_classifier_prefers_deepseek_when_requested(deepseek_app):
    from app.services.bug_classifier import LLMBugClassifier

    classifier = LLMBugClassifier(preferred_provider='deepseek')
    assert classifier._get_preferred_model() == LLMModel.DEEPSEEK_V4_FLASH


def test_classifier_falls_back_to_vision_model_for_deepseek(deepseek_app):
    from app.services.bug_classifier import LLMBugClassifier

    classifier = LLMBugClassifier(preferred_provider='deepseek')
    chosen = classifier._ensure_vision_model(LLMModel.DEEPSEEK_V4_FLASH)
    assert chosen.provider == 'ollama'
    assert chosen == LLMModel.GEMMA4_E4B


def test_get_model_for_task_routes_deepseek_for_text_only(deepseek_app):
    """Admin DB override 'deepseek' should pick DeepSeek for text tasks, not vision."""
    from app.models import SystemSetting

    SystemSetting.set('llm_provider', 'deepseek')

    assert LLMConfig.get_model_for_task('stat_generation') == LLMModel.DEEPSEEK_V4_FLASH
    assert LLMConfig.get_model_for_task('battle_narrative') == LLMModel.DEEPSEEK_V4_FLASH
    # Vision should NOT route to DeepSeek
    assert LLMConfig.get_model_for_task('vision_analysis').provider != 'deepseek'


# ── Parity tests: DeepSeek must behave the same as Ollama text path ──────────
#
# These exist because the user reported "test the deepseek llms to make sure
# they act the same as ollama". The two providers travel different code paths
# (DeepSeek -> OpenAI-compat SDK; Ollama text -> /api/chat or /v1) but every
# caller (visual_lore, tier_system, bug_classifier text fallback) expects:
#   1. <think>...</think> blocks stripped before return
#   2. ```json ... ``` fences stripped when json_mode=True
#   3. Identical clean response for identical raw LLM output
# If those invariants drift, swapping providers via admin DB override silently
# breaks JSON parsing in the stat generator etc.


def _patch_deepseek_response(service, raw):
    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content=raw))]
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response
    return patch.object(service, '_get_deepseek_client', return_value=fake_client)


def _patch_ollama_text_response(raw):
    """Patch the OpenAI client constructor that the Ollama text path imports lazily.

    _generate_ollama does `from openai import OpenAI` inside the function, so
    we need to patch it on the openai package itself, not on llm_manager.
    """
    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content=raw))]
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response
    return patch('openai.OpenAI', return_value=fake_client), fake_client


@pytest.mark.parametrize('raw,json_mode,expected', [
    # plain text — both providers should pass through untouched
    ('Hello world.', False, 'Hello world.'),
    # thinking block stripped (Qwen/DeepSeek emit these on either provider)
    ('<think>internal reasoning</think>{"a": 1}', True, '{"a": 1}'),
    # markdown JSON fence stripped in json_mode
    ('```json\n{"a": 1}\n```', True, '{"a": 1}'),
    # both stripped together
    ('<think>plan</think>```json\n{"x": 2}\n```', True, '{"x": 2}'),
])
def test_deepseek_and_ollama_clean_response_identically(deepseek_app, raw, json_mode, expected):
    """Same raw model output must clean to the same string on either provider."""
    service = LLMService()
    # Ollama config — point to the OpenAI-compat path, not native /api/chat
    # (we test a non-thinking, non-vision model so the OpenAI-compat branch is used).
    deepseek_app.config['OLLAMA_API_URL'] = 'http://test-ollama:11434'

    with _patch_deepseek_response(service, raw):
        deepseek_out = service.generate(
            prompt='p', model=LLMModel.DEEPSEEK_V4_FLASH, json_mode=json_mode,
        )

    # LLAMA3/MISTRAL aren't multimodal/thinking — they hit the OpenAI-compat /v1 path,
    # which mirrors the DeepSeek path so this is a fair apples-to-apples comparison.
    ollama_patch, _ = _patch_ollama_text_response(raw)
    with ollama_patch:
        ollama_out = service.generate(
            prompt='p', model=LLMModel.LLAMA3, json_mode=json_mode,
        )

    assert deepseek_out == expected
    assert ollama_out == expected
    assert deepseek_out == ollama_out, (
        f"Provider drift: DeepSeek returned {deepseek_out!r}, "
        f"Ollama returned {ollama_out!r} for raw={raw!r}"
    )


def test_deepseek_and_ollama_pass_same_generation_kwargs(deepseek_app):
    """Temperature, max_tokens, and system prompt should reach both providers identically."""
    service = LLMService()
    deepseek_app.config['OLLAMA_API_URL'] = 'http://test-ollama:11434'

    # DeepSeek path — capture the fake client we patch in.
    ds_fake_response = MagicMock()
    ds_fake_response.choices = [MagicMock(message=MagicMock(content='ok'))]
    ds_client = MagicMock()
    ds_client.chat.completions.create.return_value = ds_fake_response
    with patch.object(service, '_get_deepseek_client', return_value=ds_client):
        service.generate(
            prompt='hi', model=LLMModel.DEEPSEEK_V4_FLASH,
            system_prompt='be terse', max_tokens=128, temperature=0.3,
        )
    deepseek_kwargs = ds_client.chat.completions.create.call_args.kwargs

    ollama_patch, ollama_client = _patch_ollama_text_response('ok')
    with ollama_patch:
        service.generate(
            prompt='hi', model=LLMModel.LLAMA3,
            system_prompt='be terse', max_tokens=128, temperature=0.3,
        )
    ollama_kwargs = ollama_client.chat.completions.create.call_args.kwargs

    assert deepseek_kwargs['max_tokens'] == ollama_kwargs['max_tokens'] == 128
    assert deepseek_kwargs['temperature'] == ollama_kwargs['temperature'] == 0.3
    # System prompt arrives as the first message on both paths.
    assert deepseek_kwargs['messages'][0]['role'] == 'system'
    assert ollama_kwargs['messages'][0]['role'] == 'system'
    assert 'be terse' in deepseek_kwargs['messages'][0]['content']
    assert 'be terse' in ollama_kwargs['messages'][0]['content']
