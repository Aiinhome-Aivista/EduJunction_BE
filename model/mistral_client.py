"""Universal LLM Client for EduJunction (Master Prompt §12).
Routes dynamic LLM calls according to scenario assignments (e.g., exam_generation, doubt_chat, evaluation).
Executes direct API calls based on configured provider credentials and Base URLs without code hardcoding.
"""
import json
import time
import warnings
import requests
import httpx

from utils.config import config
from utils.logger import logger, log_ai_call

MAX_RETRIES = config.LLM_MAX_RETRIES
TIMEOUT_SECONDS = config.LLM_TIMEOUT_SECONDS


def _get_genai():
    """Lazily import google.generativeai with FutureWarning suppressed."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            # pyrefly: ignore [missing-import]
            import google.generativeai as genai
            return genai
        except ImportError:
            return None


class MistralUnavailableError(Exception):
    """Raised when the LLM cannot be reached/authenticated after retries.
    Callers catch this specifically and switch to their deterministic fallback path."""


# In-memory routing cache for ultra-low database latency
_last_routing_cache_time = 0
_routing_cache = {}


def clear_routing_cache():
    """Clears the scenario routing cache so admin updates take effect instantly."""
    global _last_routing_cache_time, _routing_cache
    _last_routing_cache_time = 0
    _routing_cache = {}


def get_scenario_llm_config(scenario: str = "exam_generation") -> dict | None:
    """Fetches the assigned LLM provider credentials for a given scenario from the database with short TTL caching."""
    global _last_routing_cache_time, _routing_cache
    now = time.time()
    if (now - _last_routing_cache_time) < 10 and scenario in _routing_cache:
        return _routing_cache[scenario]

    try:
        from database.dbConnection import get_session
        from model.models import LLMConfig, LLMScenarioAssignment

        with get_session() as session:
            assignment = session.query(LLMScenarioAssignment).filter(
                LLMScenarioAssignment.scenario == scenario
            ).first()

            provider = None
            if assignment:
                provider = session.get(LLMConfig, assignment.provider_id)

            if not provider:
                # Fallback to active provider or first available
                provider = session.query(LLMConfig).filter(LLMConfig.is_active == True).first()
                if not provider:
                    provider = session.query(LLMConfig).first()

            if provider:
                cfg = {
                    "id": provider.id,
                    "name": provider.name,
                    "provider": (provider.provider_type or "gemini").lower().strip(),
                    "base_url": provider.base_url,
                    "api_key": provider.api_key,
                    "model_name": provider.model_name,
                    "timeout": provider.timeout_seconds or 600,
                    "temperature": float(assignment.temperature) if assignment and assignment.temperature is not None else 0.30,
                    "max_tokens": assignment.max_tokens if assignment and assignment.max_tokens else 2048,
                }
                _routing_cache[scenario] = cfg
                _last_routing_cache_time = now
                return cfg
    except Exception as e:
        logger.warning(f"Failed to fetch scenario LLM config for '{scenario}': {e}")

    return None


def is_configured(scenario: str = "exam_generation") -> bool:
    """Returns True if an active LLM configuration is available in database for the given scenario."""
    try:
        db_cfg = get_scenario_llm_config(scenario)
        if db_cfg:
            provider = str(db_cfg.get("provider", "")).lower().strip()
            model_name = db_cfg.get("model_name")
            if "local" in provider or provider == "ollama":
                return bool(db_cfg.get("base_url") and model_name)
            if db_cfg.get("api_key") and model_name:
                return True
    except Exception:
        pass
    return False


# ============================================================
# Individual Provider Callers (Reusable by Router & Live Test)
# ============================================================

def _call_gemini(messages: list, json_mode: bool, temperature: float, api_key: str, model_name: str, timeout: int = 600) -> str:
    genai = _get_genai()
    if not genai:
        raise MistralUnavailableError("google-generativeai package is not installed.")

    if not api_key:
        raise MistralUnavailableError("Gemini API Key is missing in database configuration.")
    if not model_name:
        raise MistralUnavailableError("Model Name is missing in database configuration for Gemini.")

    genai.configure(api_key=api_key)

    system_instruction = None
    contents = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if role == "system":
            system_instruction = content
        elif role == "user":
            contents.append({"role": "user", "parts": [content]})
        elif role in ("assistant", "model"):
            contents.append({"role": "model", "parts": [content]})

    generation_config = {}
    if json_mode:
        generation_config["response_mime_type"] = "application/json"
    if temperature is not None:
        generation_config["temperature"] = temperature

    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system_instruction,
        generation_config=generation_config
    )
    response = model.generate_content(contents)
    return response.text.strip() if response else ""


def _call_mistral_cloud(messages: list, json_mode: bool, temperature: float, api_key: str, model_name: str, base_url: str = None, timeout: int = 600) -> str:
    if not base_url:
        raise MistralUnavailableError("Endpoint URL (Base URL) is missing in database for Mistral Cloud.")
    if not model_name:
        raise MistralUnavailableError("Model Name is missing in database for Mistral Cloud.")
    if not api_key:
        raise MistralUnavailableError("API Key is missing in database for Mistral Cloud.")

    target_url = base_url.strip()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    payload = {
        "model": model_name,
        "messages": messages,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    res = requests.post(target_url, json=payload, headers=headers, timeout=timeout)
    res.raise_for_status()
    data = res.json()
    return data["choices"][0]["message"]["content"].strip()


def _call_mistral_local(messages: list, json_mode: bool, temperature: float, model_name: str, base_url: str = None, timeout: int = 600) -> str:
    if not base_url:
        raise MistralUnavailableError("Endpoint URL (Base URL) is missing in database for Local Provider.")
    if not model_name:
        raise MistralUnavailableError("Model Name is missing in database for Local Provider.")

    target_url = base_url.strip()

    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False,
    }
    if temperature is not None:
        payload["options"] = {"temperature": temperature}
    if json_mode:
        payload["format"] = "json"

    res = requests.post(target_url, json=payload, timeout=timeout)
    res.raise_for_status()
    data = res.json()
    return data.get("message", {}).get("content", "").strip()


def _call_openai(messages: list, json_mode: bool, temperature: float, api_key: str, model_name: str, base_url: str = None, timeout: int = 600) -> str:
    if not base_url:
        raise MistralUnavailableError("Endpoint URL (Base URL) is missing in database for OpenAI/Custom Provider.")
    if not model_name:
        raise MistralUnavailableError("Model Name is missing in database for OpenAI/Custom Provider.")

    target_url = base_url.strip()
    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model_name,
        "messages": messages,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    res = requests.post(target_url, json=payload, headers=headers, timeout=timeout)
    res.raise_for_status()
    data = res.json()
    return data["choices"][0]["message"]["content"].strip()


def _call_claude(messages: list, json_mode: bool, temperature: float, api_key: str, model_name: str, base_url: str = None, max_tokens: int = 2048, timeout: int = 600) -> str:
    if not base_url:
        raise MistralUnavailableError("Endpoint URL (Base URL) is missing in database for Claude Provider.")
    if not model_name:
        raise MistralUnavailableError("Model Name is missing in database for Claude Provider.")
    if not api_key:
        raise MistralUnavailableError("API Key is missing in database for Claude Provider.")

    target_url = base_url.strip()

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    system_text = None
    claude_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            system_text = msg.get("content")
        else:
            claude_messages.append({"role": msg.get("role"), "content": msg.get("content")})

    payload = {
        "model": model_name,
        "max_tokens": max_tokens or 2048,
        "messages": claude_messages,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if system_text:
        payload["system"] = system_text

    res = requests.post(target_url, headers=headers, json=payload, timeout=timeout)
    res.raise_for_status()
    return res.json()["content"][0]["text"].strip()


# ============================================================
# Main Routing Dispatcher
# ============================================================

def call_llm_chat(messages: list, json_mode: bool = False, temperature: float = None, scenario: str = "doubt_chat") -> str:
    """Executes a chat completion call routed to the LLM assigned to the given scenario."""
    db_cfg = get_scenario_llm_config(scenario)
    if not db_cfg:
        raise MistralUnavailableError(f"Active LLM Configuration is missing for scenario '{scenario}'")

    active_provider = str(db_cfg["provider"]).lower().strip()
    effective_temp = temperature if temperature is not None else db_cfg.get("temperature")
    effective_timeout = db_cfg.get("timeout", 600)
    model_name = db_cfg.get("model_name")
    base_url = db_cfg.get("base_url")
    api_key = db_cfg.get("api_key")

    print(f"[LLM CALL - {scenario.upper()}] Provider: {active_provider} | Model: {model_name} | Timeout: {effective_timeout}s", flush=True)

    try:
        if "gemini" in active_provider:
            return _call_gemini(messages, json_mode, effective_temp, api_key, model_name, timeout=effective_timeout)
        elif "mistral_local" in active_provider or "local" in active_provider or active_provider == "ollama":
            return _call_mistral_local(messages, json_mode, effective_temp, model_name, base_url, timeout=effective_timeout)
        elif "mistral" in active_provider:
            return _call_mistral_cloud(messages, json_mode, effective_temp, api_key, model_name, base_url, timeout=effective_timeout)
        elif "anthropic" in active_provider or "claude" in active_provider:
            return _call_claude(messages, json_mode, effective_temp, api_key, model_name, base_url, db_cfg.get("max_tokens", 2048), timeout=effective_timeout)
        else:
            return _call_openai(messages, json_mode, effective_temp, api_key, model_name, base_url, timeout=effective_timeout)

    except Exception as e:
        raise MistralUnavailableError(f"LLM Error ({active_provider} for {scenario}): {str(e)}") from e


def call_llm(prompt: str, scenario: str = "doubt_chat") -> str:
    """Convenience single-prompt text completion."""
    return call_llm_chat([{"role": "user", "content": prompt}], json_mode=False, scenario=scenario)


def _clean_and_parse_json(raw_text: str) -> dict:
    """Robust JSON extractor with guardrails against markdown wrappers and preamble text."""
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            sub = text[start_idx : end_idx + 1]
            return json.loads(sub)
        raise


def generate_json(system_prompt: str, user_prompt: str, *, temperature: float = None, scenario: str = "exam_generation") -> dict:
    """Calls the assigned LLM with JSON-object response formatting and returns the parsed dict with guardrails."""
    strict_system_prompt = (
        f"{system_prompt}\n\n"
        "STRICT GUARDRAIL INSTRUCTION:\n"
        "1. Output MUST be 100% valid, parseable JSON conforming to the requested schema.\n"
        "2. Do NOT output any markdown commentary, prefix, or explanation outside the JSON object.\n"
        "3. Strictly adhere to standard syllabus for national boards (CBSE, ICSE, ISC) without hallucinating unverified questions."
    )

    messages = [
        {"role": "system", "content": strict_system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    last_error = None
    for attempt in range(1, MAX_RETRIES + 2):
        start = time.time()
        try:
            content = call_llm_chat(messages, json_mode=True, temperature=temperature, scenario=scenario)
            duration_ms = (time.time() - start) * 1000

            parsed = _clean_and_parse_json(content)
            log_ai_call(f"llm_{scenario}", duration_ms, success=True)
            return parsed

        except (json.JSONDecodeError, MistralUnavailableError, Exception) as exc:
            duration_ms = (time.time() - start) * 1000
            last_error = str(exc)
            log_ai_call(f"llm_{scenario}", duration_ms, success=False)

        if attempt <= MAX_RETRIES:
            time.sleep(0.5 * attempt)

    logger.error(f"LLM generate_json failed for scenario '{scenario}' after retries: {last_error}")
    raise MistralUnavailableError(last_error or f"LLM failure in {scenario}")


def embed_texts(texts: list[str], scenario: str = "embeddings") -> list[list[float]]:
    """Returns embedding vectors for input texts using the provider assigned to embeddings."""
    if not texts:
        return []

    db_cfg = get_scenario_llm_config(scenario)
    if not db_cfg:
        raise MistralUnavailableError("LLM Configuration is missing for embeddings")

    active_provider = str(db_cfg["provider"]).lower().strip()
    api_key = db_cfg.get("api_key")
    base_url = db_cfg.get("base_url")
    model_name = db_cfg.get("model_name")
    timeout = db_cfg.get("timeout", 600)

    if not model_name:
        raise MistralUnavailableError("Embedding Model Name is missing in database configuration.")
    if not base_url:
        raise MistralUnavailableError("Base URL is missing in database for embeddings.")

    start = time.time()
    target_url = base_url.strip()

    try:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {"model": model_name, "input": texts}
        res = requests.post(target_url, json=payload, headers=headers, timeout=timeout)
        res.raise_for_status()
        data = res.json()
        duration_ms = (time.time() - start) * 1000
        log_ai_call(f"embed_{active_provider}", duration_ms, success=True)

        if "embeddings" in data:
            return data["embeddings"]
        elif "data" in data and isinstance(data["data"], list):
            return [item["embedding"] for item in data["data"] if "embedding" in item]
        elif isinstance(data, list):
            return data

        return []

    except Exception as exc:
        duration_ms = (time.time() - start) * 1000
        log_ai_call(f"embed_{active_provider}", duration_ms, success=False)
        raise MistralUnavailableError(str(exc)) from exc
