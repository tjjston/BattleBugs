"""
Unified LLM Service Manager
Supports: Anthropic Claude, OpenAI, DeepSeek, and Ollama (local models)
"""

from enum import Enum
from typing import Optional, Dict, Any, List
from flask import current_app
import json


class LLMProvider(Enum):
    """Supported LLM providers"""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    OLLAMA = "ollama"


class LLMModel(Enum):
    """Available models per provider"""
    # Anthropic
    CLAUDE_SONNET_4 = ("anthropic", "claude-sonnet-4-6")
    CLAUDE_OPUS_4 = ("anthropic", "claude-opus-4-7")

    # OpenAI
    GPT_4O = ("openai", "gpt-4o")
    GPT_4 = ("openai", "gpt-4")
    GPT_4_TURBO = ("openai", "gpt-4-turbo-preview")
    GPT_35_TURBO = ("openai", "gpt-3.5-turbo")

    # DeepSeek (OpenAI-compatible API; text-only)
    DEEPSEEK_V4_FLASH = ("deepseek", "deepseek-v4-flash")
    DEEPSEEK_V4_PRO = ("deepseek", "deepseek-v4-pro")

    # Ollama (local)
    QWEN36_35B = ("ollama", "qwen3.6:35b")    # thinking-only via /v1 (broken for text output)
    QWEN36_UC  = ("ollama", "qwen3.6-uc:latest")  # thinking model that outputs via native endpoint
    QWEN35_35B = ("ollama", "qwen3.6:35b")  # Backward-compatible config alias
    GEMMA4_E2B = ("ollama", "gemma4:e2b")   # Multimodal vision model (2B, fastest)
    GEMMA4_E4B = ("ollama", "gemma4:e4b")   # Multimodal vision model (4B, fast)
    GEMMA4_31B = ("ollama", "gemma4:31b")   # Large text model
    GEMMA_UC_E4B = ("ollama", "gemma-uc:e4b")  # Creative writing / fast tasks
    LLAMA3 = ("ollama", "gpt-oss:120b")
    MISTRAL = ("ollama", "kimi-k2-thinking:cloud")
    CODELLAMA = ("ollama", "qwen3vl")
    
    def __init__(self, provider: str, model_name: str):
        self.provider = provider
        self.model_name = model_name


class LLMConfig:
    """
    Centralized LLM configuration
    Set your preferred model here or via environment variable
    """
    DEFAULT_MODEL = LLMModel.QWEN36_UC

    TASK_MODELS = {
        'battle_narrative': LLMModel.GEMMA_UC_E4B,
        'stat_generation': LLMModel.QWEN36_UC,
        'vision_analysis': LLMModel.GEMMA4_31B,  # 18.5 GB; slow but much more accurate
        'species_identification': LLMModel.GEMMA4_E4B,
        'quick_tasks': LLMModel.GEMMA_UC_E4B,  # non-thinking, fast — used for lore/species/nickname helpers
    }
    
    @classmethod
    def get_model_for_task(cls, task: str) -> LLMModel:
        """Get the configured model for a specific task.

        Priority: admin SystemSetting DB > app config env var > TASK_MODELS default.
        """
        # 1. Check admin DB override for this specific task
        try:
            from app.models import SystemSetting
            db_task_model = SystemSetting.get(f'llm_model_{task}')
            if db_task_model:
                try:
                    return LLMModel[db_task_model]
                except KeyError:
                    pass
            # 2. Check global provider override
            db_provider = SystemSetting.get('llm_provider')
            if db_provider == 'anthropic':
                return LLMModel.CLAUDE_SONNET_4
            elif db_provider == 'openai':
                if task == 'vision_analysis':
                    return LLMModel.GPT_4O
                return LLMModel.GPT_4
            elif db_provider == 'deepseek':
                # Text-only — vision tasks fall through to default vision model.
                if task != 'vision_analysis':
                    return LLMModel.DEEPSEEK_V4_FLASH
            elif db_provider == 'ollama':
                pass  # fall through to default Ollama config
        except Exception:
            pass

        # 3. Fall back to app config / env var
        model_name = current_app.config.get(f'LLM_MODEL_{task.upper()}')
        if model_name:
            try:
                return LLMModel[model_name]
            except KeyError:
                pass
        return cls.TASK_MODELS.get(task, cls.DEFAULT_MODEL)


class LLMService:
    """
    Unified interface for all LLM providers
    Usage:
        llm = LLMService()
        response = llm.generate("Your prompt", task='battle_narrative')
    """

    def __init__(self):
        self._anthropic_client = None
        self._openai_client = None
        self._deepseek_client = None
        self._ollama_base_url = None

    @staticmethod
    def _clean_response(text: str, json_mode: bool = False) -> str:
        """Strip chain-of-thought blocks and markdown fences from LLM output.

        Ollama models (Qwen, Gemma, DeepSeek) emit <think>…</think> before the
        actual answer. If we try to JSON-parse the raw output we get
        "Expecting value: line 1 column 1 (char 0)" because the parser hits the
        tag, not the opening brace.
        """
        if not text:
            return ''
        import re
        # Remove <think>…</think> (and <thinking>…</thinking>) blocks entirely
        text = re.sub(r'<think(?:ing)?>.*?</think(?:ing)?>', '', text, flags=re.DOTALL)
        text = text.strip()
        if json_mode:
            # Strip ```json … ``` or plain ``` … ``` fences
            text = re.sub(r'^```(?:json)?\s*\n?', '', text)
            text = re.sub(r'\n?```\s*$', '', text)
            text = text.strip()
        return text
    
    def _get_anthropic_client(self):
        """Lazy load Anthropic client"""
        if not self._anthropic_client:
            api_key = current_app.config.get('ANTHROPIC_API_KEY')
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not configured")
            from anthropic import Anthropic
            self._anthropic_client = Anthropic(api_key=api_key)
        return self._anthropic_client
    
    def _get_openai_client(self):
        """Lazy load OpenAI client"""
        if not self._openai_client:
            api_key = current_app.config.get('OPENAI_API_KEY')
            if not api_key:
                raise ValueError("OPENAI_API_KEY not configured")
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=api_key)
        return self._openai_client
    
    def _get_deepseek_client(self):
        """Lazy load DeepSeek client (OpenAI-compatible)."""
        if not self._deepseek_client:
            api_key = current_app.config.get('DEEPSEEK_API_KEY')
            if not api_key:
                raise ValueError("DEEPSEEK_API_KEY not configured")
            base_url = current_app.config.get('DEEPSEEK_API_URL', 'https://api.deepseek.com')
            from openai import OpenAI
            self._deepseek_client = OpenAI(api_key=api_key, base_url=base_url, timeout=240.0)
        return self._deepseek_client

    def _get_ollama_url(self):
        """Get Ollama base URL"""
        if not self._ollama_base_url:
            self._ollama_base_url = current_app.config.get('OLLAMA_API_URL', 'http://localhost:11434')
        return self._ollama_base_url
    
    def generate(
        self,
        prompt: str,
        task: Optional[str] = None,
        model: Optional[LLMModel] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
        image_data: Optional[Dict[str, str]] = None,
        json_mode: bool = False
    ) -> str:
        """
        Generate text using the appropriate LLM
        
        Args:
            prompt: The user prompt
            task: Task type (uses configured model for task)
            model: Override model selection
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-1)
            system_prompt: System instructions
            image_data: For vision tasks: {'base64': str, 'media_type': str}
            json_mode: Enforce JSON output
            
        Returns:
            Generated text response
        """
        # Determine which model to use
        if model is None:
            if task:
                model = LLMConfig.get_model_for_task(task)
            else:
                model = LLMConfig.DEFAULT_MODEL
        
        current_app.logger.info("Using %s/%s for task: %s", model.provider, model.model_name, task or 'general')
        
        # Route to appropriate provider
        if model.provider == "anthropic":
            raw = self._generate_anthropic(prompt, model, max_tokens, temperature, system_prompt, image_data, json_mode)
        elif model.provider == "openai":
            raw = self._generate_openai(prompt, model, max_tokens, temperature, system_prompt, image_data, json_mode)
        elif model.provider == "deepseek":
            raw = self._generate_deepseek(prompt, model, max_tokens, temperature, system_prompt, image_data, json_mode)
        elif model.provider == "ollama":
            raw = self._generate_ollama(prompt, model, max_tokens, temperature, system_prompt, image_data)
        else:
            raise ValueError(f"Unsupported provider: {model.provider}")

        # Strip thinking blocks and (if JSON expected) markdown fences uniformly
        cleaned = self._clean_response(raw, json_mode=json_mode)

        # Qwen3 / DeepSeek thinking models sometimes emit ONLY a <think> block with
        # nothing after.  If clean_response stripped everything, fall back to the raw
        # content inside the last <think> block so at least something is returned.
        if not cleaned and raw:
            import re
            think_match = re.search(r'<think(?:ing)?>(.*?)</think(?:ing)?>', raw, re.DOTALL)
            if think_match:
                cleaned = think_match.group(1).strip()

        return cleaned
    
    def _generate_anthropic(
        self,
        prompt: str,
        model: LLMModel,
        max_tokens: int,
        temperature: float,
        system_prompt: Optional[str],
        image_data: Optional[Dict[str, str]],
        json_mode: bool
    ) -> str:
        """Generate using Anthropic Claude"""
        client = self._get_anthropic_client()
        
        # Build content
        content = []
        
        # Add image if provided (Claude supports vision)
        if image_data:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_data.get('media_type', 'image/jpeg'),
                    "data": image_data['base64']
                }
            })
        
        # Add text prompt
        content.append({
            "type": "text",
            "text": prompt
        })
        
        # Make API call
        message = client.messages.create(
            model=model.model_name,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt if system_prompt else "You are a helpful assistant.",
            messages=[{"role": "user", "content": content}]
        )
        
        return message.content[0].text
    
    def _generate_openai(
        self,
        prompt: str,
        model: LLMModel,
        max_tokens: int,
        temperature: float,
        system_prompt: Optional[str],
        image_data: Optional[Dict[str, str]],
        json_mode: bool
    ) -> str:
        """Generate using OpenAI"""
        client = self._get_openai_client()
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if image_data and image_data.get('base64'):
            media_type = image_data.get("media_type", "image/jpeg")
            messages.append({"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:{media_type};base64,{image_data['base64']}"
                }},
            ]})
        else:
            messages.append({"role": "user", "content": prompt})
        
        kwargs = {
            "model": model.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        
        # JSON mode for GPT-4
        if json_mode and "gpt-4" in model.model_name:
            kwargs["response_format"] = {"type": "json_object"}
            if system_prompt and "json" not in system_prompt.lower():
                messages[0]["content"] += "\n\nRespond with valid JSON only."
        
        response = client.chat.completions.create(**kwargs)
        
        return response.choices[0].message.content
    
    def _generate_deepseek(
        self,
        prompt: str,
        model: LLMModel,
        max_tokens: int,
        temperature: float,
        system_prompt: Optional[str],
        image_data: Optional[Dict[str, str]],
        json_mode: bool,
    ) -> str:
        """Generate using DeepSeek (OpenAI-compatible chat completions).

        DeepSeek V4 chat models are text-only. Image data is ignored with a
        logged warning — callers should route vision tasks elsewhere.
        """
        if image_data and image_data.get('base64'):
            current_app.logger.warning(
                "DeepSeek model %s is text-only; ignoring image_data. "
                "Use a vision-capable provider for image classification.",
                model.model_name,
            )

        client = self._get_deepseek_client()

        messages: list = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if json_mode and system_prompt and "json" not in system_prompt.lower():
            messages[0]["content"] += "\n\nRespond with valid JSON only."
        elif json_mode and not system_prompt:
            messages.append({"role": "system", "content": "Respond with valid JSON only."})
        messages.append({"role": "user", "content": prompt})

        kwargs: Dict[str, Any] = {
            "model": model.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ''

    # Per-model capability registry.
    # 'thinking': model emits <think> blocks; /no_think suppresses them.
    # 'native_vision': model requires Ollama's /api/chat images[] instead of
    #                  the OpenAI-compat image_url wrapper (which returns 500).
    # Keys are matched as prefixes/substrings against the lowercase model name.
    _OLLAMA_MODEL_CAPS: Dict[str, Dict[str, bool]] = {
        'qwen3':            {'thinking': True,  'native_vision': False},
        'qwq':              {'thinking': True,  'native_vision': False},
        'deepseek-r1':      {'thinking': True,  'native_vision': False},
        'kimi-k2-thinking': {'thinking': True,  'native_vision': False},
        'gemma4':           {'thinking': False, 'native_vision': True},
        'gemma3':           {'thinking': False, 'native_vision': True},
        'gemma-uc':         {'thinking': False, 'native_vision': False},
        'gemma':            {'thinking': False, 'native_vision': True},
        'llava':            {'thinking': False, 'native_vision': True},
        'minicpm-v':        {'thinking': False, 'native_vision': True},
        'qwen3vl':          {'thinking': False, 'native_vision': True},
        'llama3':           {'thinking': False, 'native_vision': False},
        'mistral':          {'thinking': False, 'native_vision': False},
    }

    def _get_model_caps(self, model_name: str) -> Dict[str, bool]:
        name = model_name.lower()
        for prefix, caps in self._OLLAMA_MODEL_CAPS.items():
            if name.startswith(prefix) or prefix in name:
                return caps
        return {'thinking': False, 'native_vision': False}

    def _generate_ollama(
        self,
        prompt: str,
        model: LLMModel,
        max_tokens: int,
        temperature: float,
        system_prompt: Optional[str],
        image_data: Optional[Dict[str, str]] = None,
    ) -> str:
        """Generate using Ollama.

        Vision requests go to the native /api/chat endpoint (images[] array)
        because the OpenAI-compat /v1 endpoint fails for many multimodal models.
        Thinking models (Qwen3/DeepSeek) also use the native endpoint for text
        because /v1 returns empty content — the answer lands in a separate
        `thinking` field that the OpenAI SDK never exposes.
        """
        caps = self._get_model_caps(model.model_name)
        base_system = (system_prompt or "You are a helpful assistant.")

        # /no_think suppresses thinking-only output on Qwen3/DeepSeek models.
        # Do NOT inject it for non-thinking models — they return empty responses.
        if caps.get('thinking') and '/no_think' not in base_system:
            base_system = '/no_think\n' + base_system

        has_image = bool(image_data and image_data.get("base64"))

        # Use native /api/chat for: vision models with images, OR any thinking model.
        # The OpenAI-compat /v1 endpoint silently drops content for thinking models.
        if (has_image and caps.get('native_vision')) or caps.get('thinking'):
            return self._generate_ollama_native(
                prompt, model, max_tokens, temperature, base_system,
                image_data if has_image else None,
            )

        # ── OpenAI-compat path (non-thinking text-only models) ──
        from openai import OpenAI
        base_url = self._get_ollama_url().rstrip('/')
        if not base_url.endswith('/v1'):
            base_url = f"{base_url}/v1"
        # 240s is too long when Ollama is intermittently hung — the UI sits
        # waiting. 45s is enough for one cold load + a normal completion;
        # the route layer can retry once if needed.
        client = OpenAI(base_url=base_url, api_key="ollama", timeout=45.0)

        messages: list = [{"role": "system", "content": base_system}]
        if has_image:
            media_type = image_data.get("media_type", "image/jpeg")
            messages.append({"role": "user", "content": [
                {"type": "image_url", "image_url": {
                    "url": f"data:{media_type};base64,{image_data['base64']}"
                }},
                {"type": "text", "text": prompt},
            ]})
        else:
            messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=model.model_name,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content or ''

    def _generate_ollama_native(
        self,
        prompt: str,
        model: LLMModel,
        max_tokens: int,
        temperature: float,
        system_prompt: str,
        image_data: Optional[Dict[str, str]] = None,
    ) -> str:
        """Native /api/chat endpoint for Ollama.

        Used for:
        - Multimodal models (images[] field, raw base64)
        - Thinking models (Qwen3/DeepSeek) — /v1 silently drops content for these
        """
        import urllib.request as _urllib
        import urllib.error as _urlerr

        base_url = self._get_ollama_url().rstrip('/')
        if base_url.endswith('/v1'):
            base_url = base_url[:-3]

        user_msg: Dict = {"role": "user", "content": prompt}
        if image_data and image_data.get("base64"):
            user_msg["images"] = [image_data["base64"]]

        messages = [
            {"role": "system", "content": system_prompt},
            user_msg,
        ]
        payload = json.dumps({
            "model": model.model_name,
            "messages": messages,
            "stream": False,
            "keep_alive": "30m",  # keep big vision models resident between calls
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }).encode()

        req = _urllib.Request(
            f"{base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            # 1200s tolerates: VRAM-eviction-driven cold load on big GGUFs
            # (can be 90-180s when another model is resident) + vision token
            # encoding + slow inference. User has explicitly OK'd long waits
            # in exchange for accuracy.
            with _urllib.urlopen(req, timeout=1200) as resp:
                result = json.loads(resp.read())
            return result.get("message", {}).get("content", "") or ""
        except _urlerr.HTTPError as exc:
            body = exc.read().decode(errors='replace')
            raise RuntimeError(f"Ollama /api/chat {exc.code}: {body}") from exc
    
    def generate_stream(
        self,
        prompt: str,
        task: Optional[str] = None,
        model: Optional[LLMModel] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
    ):
        """Yield text chunks as the model produces them.

        Currently implemented for Ollama (native /api/chat with stream=True).
        Other providers fall back to a single-chunk yield of the full response
        so callers can use one consumer pattern everywhere.
        """
        if model is None:
            if task:
                model = LLMConfig.get_model_for_task(task)
            else:
                model = LLMConfig.DEFAULT_MODEL

        if model.provider != 'ollama':
            # Non-Ollama providers: degrade to single-chunk emission.
            full = self.generate(prompt, task=task, model=model, max_tokens=max_tokens,
                                 temperature=temperature, system_prompt=system_prompt)
            if full:
                yield full
            return

        import urllib.request as _urllib
        base_url = self._get_ollama_url().rstrip('/')
        if base_url.endswith('/v1'):
            base_url = base_url[:-3]

        base_system = system_prompt or "You are a helpful assistant."
        # Mirror generate()'s /no_think prepend for Qwen3-style thinking models
        # so streamed text isn't a chain-of-thought leak.
        caps = self._get_model_caps(model.model_name)
        if caps.get('thinking') and '/no_think' not in base_system:
            base_system = '/no_think\n' + base_system

        payload = json.dumps({
            "model": model.model_name,
            "messages": [
                {"role": "system", "content": base_system},
                {"role": "user", "content": prompt},
            ],
            "stream": True,
            "keep_alive": "30m",
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }).encode()

        req = _urllib.Request(
            f"{base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        in_think = False
        with _urllib.urlopen(req, timeout=1200) as resp:
            for line in resp:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except (TypeError, ValueError):
                    continue
                msg = obj.get('message') or {}
                chunk = msg.get('content') or ''
                if not chunk:
                    if obj.get('done'):
                        break
                    continue
                # Strip <think>…</think> from streamed output incrementally.
                while chunk:
                    if in_think:
                        end = chunk.find('</think>')
                        if end < 0:
                            chunk = ''
                            break
                        chunk = chunk[end + len('</think>'):]
                        in_think = False
                    else:
                        start = chunk.find('<think>')
                        if start < 0:
                            yield chunk
                            chunk = ''
                            break
                        if start > 0:
                            yield chunk[:start]
                        chunk = chunk[start + len('<think>'):]
                        in_think = True
                if obj.get('done'):
                    break

    def generate_json(
        self,
        prompt: str,
        task: Optional[str] = None,
        model: Optional[LLMModel] = None,
        max_tokens: int = 1024,
        image_data: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Generate and parse JSON response."""
        response = self.generate(
            prompt=prompt,
            task=task,
            model=model,
            max_tokens=max_tokens,
            json_mode=True,
            image_data=image_data,
        )
        if not response:
            raise ValueError("LLM returned an empty response")
        return json.loads(response)


# Example helper functions for common tasks

def generate_battle_narrative(bug1, bug2, winner, secret_lore: bool = True) -> str:
    """Generate battle narrative using configured LLM"""
    llm = LLMService()
    
    prompt = f"""Generate an epic 3-paragraph battle narrative between two bug gladiators.

**{bug1.nickname}** ({bug1.common_name or bug1.scientific_name})
Stats: ATK:{bug1.attack} DEF:{bug1.defense} SPD:{bug1.speed}

**{bug2.nickname}** ({bug2.common_name or bug2.scientific_name})
Stats: ATK:{bug2.attack} DEF:{bug2.defense} SPD:{bug2.speed}

**WINNER: {winner.nickname}**

Write a dramatic battle with Opening, Mid-battle, and Climax. Keep under 300 words.
Make it exciting and use the stats naturally."""
    
    if secret_lore:
        # Add secret lore if we want enhanced narratives
        prompt += f"\n\nSecret advantages (weave subtly):\n"
        prompt += f"{bug1.nickname}: {bug1.visual_lore_items or 'standard equipment'}\n"
        prompt += f"{bug2.nickname}: {bug2.visual_lore_items or 'standard equipment'}"
    
    return llm.generate(prompt, task='battle_narrative', max_tokens=800)


def generate_bug_stats(bug_info: Dict[str, Any]) -> Dict[str, Any]:
    """Generate stats using configured LLM"""
    llm = LLMService()
    
    prompt = f"""Generate combat stats (1-10 scale) for this bug:
- Scientific Name: {bug_info.get('scientific_name', 'Unknown')}
- Common Name: {bug_info.get('common_name', 'Unknown')}
- Size: {bug_info.get('size_mm', 'Unknown')}mm
- Traits: {bug_info.get('traits', [])}

Respond in JSON format:
{{
  "attack": 1-10,
  "defense": 1-10,
  "speed": 1-10,
  "special_ability": "ability name",
  "reasoning": "brief explanation"
}}

BE REALISTIC: Most bugs should be 18-22 total stats. Only legendary bugs get 27+."""
    
    return llm.generate_json(prompt, task='stat_generation', max_tokens=512)


def analyze_bug_image(image_path: str, user_lore: Optional[Dict] = None) -> Dict[str, Any]:
    """Analyze bug image for hidden advantages"""
    llm = LLMService()
    
    # Read and encode image
    import base64
    with open(image_path, 'rb') as f:
        image_data = base64.standard_b64encode(f.read()).decode('utf-8')
    
    # Determine media type
    ext = image_path.lower().split('.')[-1]
    media_types = {
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'png': 'image/png', 'gif': 'image/gif', 'webp': 'image/webp'
    }
    media_type = media_types.get(ext, 'image/jpeg')
    
    prompt = """Analyze this bug photo for secret combat advantages. Look for:
- Items/objects the bug might use as weapons
- Environmental advantages
- Posture/battle stance
- Unique visual traits

Respond in JSON:
{
  "visual_lore_analysis": "narrative description",
  "visual_lore_items": "items found or 'none'",
  "visual_lore_environment": "environmental advantages",
  "xfactor": 0.0 (score from -5.0 to +5.0),
  "xfactor_reason": "why this score"
}

Significant advantages should be rare - center around 0."""
    
    if user_lore:
        prompt += f"\n\nUser-provided context:\n{json.dumps(user_lore, indent=2)}"
    
    return llm.generate_json(
        prompt,
        task='vision_analysis',
        image_data={'base64': image_data, 'media_type': media_type},
        max_tokens=1024
    )
