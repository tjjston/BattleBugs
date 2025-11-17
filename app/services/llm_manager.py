"""
Unified LLM Service Manager
Supports: Anthropic Claude, OpenAI, and Ollama (local models)
"""

from enum import Enum
from typing import Optional, Dict, Any, List
from flask import current_app
import json


class LLMProvider(Enum):
    """Supported LLM providers"""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OLLAMA = "ollama"


class LLMModel(Enum):
    """Available models per provider"""
    # Anthropic
    CLAUDE_SONNET_4 = ("anthropic", "claude-sonnet-4-20250514")
    CLAUDE_OPUS_4 = ("anthropic", "claude-opus-4-20250514")
    
    # OpenAI
    GPT_4 = ("openai", "gpt-4")
    GPT_4_TURBO = ("openai", "gpt-4-turbo-preview")
    GPT_35_TURBO = ("openai", "gpt-3.5-turbo")
    
    # Ollama (local)
    LLAMA3 = ("ollama", "gpt-oss:120b")
    MISTRAL = ("ollama", "kimi-k2-thinking:cloud")
    CODELLAMA = ("ollama", 	"qwen3vl")
    
    def __init__(self, provider: str, model_name: str):
        self.provider = provider
        self.model_name = model_name


class LLMConfig:
    """
    Centralized LLM configuration
    Set your preferred model here or via environment variable
    """
    DEFAULT_MODEL = LLMModel.CLAUDE_SONNET_4

    TASK_MODELS = {
        'battle_narrative': LLMModel.CLAUDE_SONNET_4, 
        'stat_generation': LLMModel.GPT_4, 
        'vision_analysis': LLMModel.CLAUDE_SONNET_4,  
        'species_identification': LLMModel.GPT_4,     
        'quick_tasks': LLMModel.GPT_35_TURBO,      
    }
    
    @classmethod
    def get_model_for_task(cls, task: str) -> LLMModel:
        """Get the configured model for a specific task"""
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
        self._ollama_base_url = None
    
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
        
        print(f"Using {model.provider}/{model.model_name} for task: {task or 'general'}")
        
        # Route to appropriate provider
        if model.provider == "anthropic":
            return self._generate_anthropic(prompt, model, max_tokens, temperature, system_prompt, image_data, json_mode)
        elif model.provider == "openai":
            return self._generate_openai(prompt, model, max_tokens, temperature, system_prompt, json_mode)
        elif model.provider == "ollama":
            return self._generate_ollama(prompt, model, max_tokens, temperature, system_prompt)
        else:
            raise ValueError(f"Unsupported provider: {model.provider}")
    
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
        
        response_text = message.content[0].text
        
        # Clean up JSON if needed
        if json_mode:
            response_text = response_text.replace('```json\n', '').replace('\n```', '').strip()
        
        return response_text
    
    def _generate_openai(
        self,
        prompt: str,
        model: LLMModel,
        max_tokens: int,
        temperature: float,
        system_prompt: Optional[str],
        json_mode: bool
    ) -> str:
        """Generate using OpenAI"""
        client = self._get_openai_client()
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
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
    
    def _generate_ollama(
        self,
        prompt: str,
        model: LLMModel,
        max_tokens: int,
        temperature: float,
        system_prompt: Optional[str]
    ) -> str:
        """Generate using local Ollama"""
        import requests
        
        url = f"{self._get_ollama_url()}/api/generate"
        
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"
        
        data = {
            "model": model.model_name,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }
        
        response = requests.post(url, json=data, timeout=60)
        response.raise_for_status()
        
        return response.json()['response']
    
    def generate_json(
        self,
        prompt: str,
        task: Optional[str] = None,
        model: Optional[LLMModel] = None,
        max_tokens: int = 1024
    ) -> Dict[str, Any]:
        """
        Generate and parse JSON response
        
        Returns:
            Parsed JSON dictionary
        """
        response = self.generate(
            prompt=prompt,
            task=task,
            model=model,
            max_tokens=max_tokens,
            json_mode=True
        )
        
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