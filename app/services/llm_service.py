from ast import List
from typing import Optional
from anthropic import Anthropic
from flask import current_app
from app.models import Bug
from app.services.llm_service import LLMService
from OLLAMA import Ollama
from OPENAI import OpenAI

api_key = [
    'Ollama': 'http://192.168.0.99:11434',
    'OpenAI': current_app.config.get('OPENAI_API_KEY'),
    'Anthropic': current_app.config.get('ANTHROPIC_API_KEY')
]

def generate_battle_narrative(
    bug1: Bug,
    bug2: Bug,
    winner: Optional[Bug],
    matchup_notes: Optional[List[str]] = None,
    tournament_id: Optional[int] = None,
    round_number: Optional[int] = None,
) -> str:
    """Generate an engaging battle narrative.

    This function prefers to use an LLM if API keys are configured. If not, or if
    the LLM call fails, a human-readable fallback narrative is returned.

    The `winner` may be None (draw) and `matchup_notes` can be used to highlight
    special modifiers applied by `battle_engine.py`.
    """
    # Build a compact, deterministic prompt for the LLM or fallback generator
    def bug_summary(b: Bug) -> str:
        return (
            f"{b.name} (Species: {getattr(b, 'species', 'Unknown')}) — "
            f"Atk:{b.attack} Def:{b.defense} Spd:{b.speed} "
            f"SA:{getattr(b, 'special_attack', 0)} SD:{getattr(b, 'special_defense', 0)}"
        )

    notes_text = "\n".join(matchup_notes) if matchup_notes else ""
    winner_text = winner.name if winner else "No clear winner (draw)"

    prompt = (
        "You are an energetic sports announcer describing an arena battle between two combat bugs.\n"
        f"Bug A: {bug_summary(bug1)}\n"
        f"Bug B: {bug_summary(bug2)}\n"
        f"Matchup notes:\n{notes_text}\n"
        f"Tournament: {tournament_id or 'N/A'}, Round: {round_number or 'N/A'}\n"
        "Write a short 3-paragraph narrative (Opening, Mid-battle, Climax). Keep it vivid, use the stats naturally, and end with the result: "
        f"{winner_text}. Keep it under ~250 words."
    )

    # Try Anthropic if configured (best-effort; fallback if anything goes wrong)
    try:
        anthropic_key = current_app.config.get("ANTHROPIC_API_KEY")
        if anthropic_key:
            # Defer to installed Anthropic client if available. This is a best-effort
            # call; if the client's API differs it will raise and fall back to the
            # local generator below.
            from anthropic import Anthropic

            client = Anthropic(api_key=anthropic_key)
            # Many Anthropic SDKs expose a `completion` or `completions.create` API.
            # Use a conservative call pattern and accept any working response shape.
            try:
                resp = client.completions.create(model="claude-2", prompt=prompt, max_tokens=500)
                # Try common response shapes
                if hasattr(resp, "completion"):
                    return resp.completion
                if isinstance(resp, dict) and "completion" in resp:
                    return resp["completion"]
                if hasattr(resp, "text"):
                    return resp.text
            except Exception:
                # Fall back to alternate client surface
                resp = client.create_completion(prompt=prompt, max_tokens=500)
                if isinstance(resp, dict) and "text" in resp:
                    return resp["text"]

    except Exception as e:
        logger.debug("Anthropic LLM call failed or not available: %s", e)

    # If no LLM is available or the call failed, return a deterministic fallback narrative
    return generate_fallback_narrative(bug1, bug2, winner, matchup_notes, tournament_id, round_number)


def generate_fallback_narrative(bug1: Bug, bug2: Bug, winner: Bug):
    """
    Generate a simple fallback narrative if LLM is unavailable.
    """
    return f"""🏟️ THE BATTLE BEGINS

Round 1: {bug1.name} and {bug2.name} enter the arena, circling each other cautiously. 
The crowd roars as both competitors assess their opponent's strengths.

Round 2: The battle intensifies! {bug1.name} uses its {bug1.attack} attack power while 
{bug2.name} relies on its {bug2.defense} defense. The arena shakes with their clashes.

CLIMAX: In a stunning finale, {winner.name} emerges victorious! Using superior 
{'speed' if winner.speed > (bug1.speed if winner == bug2 else bug2.speed) else 'strength'}, 
{winner.name} claims victory and the crowd goes wild!

Winner: {winner.name} 🏆"""

def generate_bug_analysis(bug: Bug) -> str:
    """Produce a short human-friendly analysis for a single bug.

    This function prefers Anthropic if configured, otherwise falls back to a
    deterministic one-liner.
    """
    try:
        anthropic_key = current_app.config.get("ANTHROPIC_API_KEY")
        if anthropic_key:
            from anthropic import Anthropic

            client = Anthropic(api_key=anthropic_key)
            prompt = (
                f"Provide a 2-sentence combat analysis for {bug.name}. "
                f"Stats Attack:{bug.attack} Defense:{bug.defense} Speed:{bug.speed}."
            )
            try:
                resp = client.completions.create(model="claude-2", prompt=prompt, max_tokens=120)
                if hasattr(resp, "completion"):
                    return resp.completion
                if isinstance(resp, dict) and "completion" in resp:
                    return resp["completion"]
                if hasattr(resp, "text"):
                    return resp.text
            except Exception:
                resp = client.create_completion(prompt=prompt, max_tokens=120)
                if isinstance(resp, dict) and "text" in resp:
                    return resp["text"]
    except Exception as e:
        logger.debug("Anthropic analysis failed: %s", e)

    # Fallback analysis
    return f"{bug.name} is a fighter with Attack {bug.attack}, Defense {bug.defense} and Speed {bug.speed}." 
