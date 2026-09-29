"""Universal LLM Client for EduJunction (Master Prompt §12).
Routes dynamic LLM calls according to scenario assignments (e.g., exam_generation, doubt_chat, evaluation).
Executes direct API calls based on configured provider credentials and Base URLs without code hardcoding.
"""
import json
import re
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
# Individual Provider Callers (Pure Database-Driven)
# ============================================================

def _format_chat_endpoint(url: str) -> str:
    """Ensures a local provider base_url ends with /api/chat if omitted."""
    if not url:
        return ""
    clean = url.strip().rstrip("/")
    if not clean.endswith(("/api/chat", "/chat/completions", "/messages")):
        if ":11434" in clean or ":3041" in clean or "ollama" in clean or "local" in clean:
            clean += "/api/chat"
        else:
            clean += "/chat/completions"
    return clean


def _call_gemini(messages: list, json_mode: bool, temperature: float, api_key: str, model_name: str, timeout: int = 600) -> str:
    genai = _get_genai()
    if not genai:
        raise MistralUnavailableError("google-generativeai package is not installed.")

    if not api_key:
        raise MistralUnavailableError("Gemini API Key is missing in database provider configuration.")
    if not model_name:
        raise MistralUnavailableError("Gemini Model Name is missing in database provider configuration.")

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
        raise MistralUnavailableError("Base URL is missing in database provider configuration for Mistral Cloud.")
    if not model_name:
        raise MistralUnavailableError("Model Name is missing in database provider configuration for Mistral Cloud.")
    if not api_key:
        raise MistralUnavailableError("API Key is missing in database provider configuration for Mistral Cloud.")

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
        raise MistralUnavailableError("Base URL is missing in database provider configuration for Local LLM.")
    if not model_name:
        raise MistralUnavailableError("Model Name is missing in database provider configuration for Local LLM.")

    resolved_url = _format_chat_endpoint(base_url)

    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False,
    }
    if temperature is not None:
        payload["options"] = {"temperature": temperature}
    if json_mode:
        payload["format"] = "json"

    res = requests.post(resolved_url, json=payload, timeout=timeout)
    res.raise_for_status()
    data = res.json()
    return data.get("message", {}).get("content", "").strip()


def _call_openai(messages: list, json_mode: bool, temperature: float, api_key: str, model_name: str, base_url: str = None, timeout: int = 600) -> str:
    if not base_url:
        raise MistralUnavailableError("Base URL is missing in database provider configuration for OpenAI/Custom Provider.")
    if not model_name:
        raise MistralUnavailableError("Model Name is missing in database provider configuration for OpenAI/Custom Provider.")

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
        raise MistralUnavailableError("Base URL is missing in database provider configuration for Claude Provider.")
    if not model_name:
        raise MistralUnavailableError("Model Name is missing in database provider configuration for Claude Provider.")
    if not api_key:
        raise MistralUnavailableError("API Key is missing in database provider configuration for Claude Provider.")

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


def get_all_active_providers() -> list:
    """Returns all active LLM configurations ordered by database ID index (ascending)."""
    try:
        from database.dbConnection import get_session
        from model.models import LLMConfig

        with get_session() as session:
            providers = session.query(LLMConfig).filter(LLMConfig.is_active == True).order_by(LLMConfig.id.asc()).all()
            return [
                {
                    "id": p.id,
                    "name": p.name,
                    "provider": (p.provider_type or "gemini").lower().strip(),
                    "base_url": p.base_url,
                    "api_key": p.api_key,
                    "model_name": p.model_name,
                    "timeout": p.timeout_seconds or 600,
                    "temperature": 0.30,
                    "max_tokens": 2048,
                }
                for p in providers
            ]
    except Exception as e:
        logger.warning(f"Error fetching active providers list: {e}")
        return []


def _execute_provider_call(provider_cfg: dict, messages: list, json_mode: bool, temperature: float) -> str:
    """Dispatches call strictly using credentials and model from the database provider record."""
    active_provider = str(provider_cfg.get("provider") or "gemini").lower().strip()
    effective_temp = temperature if temperature is not None else provider_cfg.get("temperature", 0.30)
    effective_timeout = provider_cfg.get("timeout", 600)
    model_name = provider_cfg.get("model_name")
    base_url = provider_cfg.get("base_url")
    api_key = provider_cfg.get("api_key")
    max_tokens = provider_cfg.get("max_tokens", 2048)

    if "gemini" in active_provider:
        return _call_gemini(messages, json_mode, effective_temp, api_key, model_name, timeout=effective_timeout)
    elif "mistral_local" in active_provider or "local" in active_provider or active_provider == "ollama":
        return _call_mistral_local(messages, json_mode, effective_temp, model_name, base_url, timeout=effective_timeout)
    elif "mistral" in active_provider:
        return _call_mistral_cloud(messages, json_mode, effective_temp, api_key, model_name, base_url, timeout=effective_timeout)
    elif "anthropic" in active_provider or "claude" in active_provider:
        return _call_claude(messages, json_mode, effective_temp, api_key, model_name, base_url, max_tokens, timeout=effective_timeout)
    else:
        return _call_openai(messages, json_mode, effective_temp, api_key, model_name, base_url, timeout=effective_timeout)


# ============================================================
# Main Routing Dispatcher with Database Index-Wise Fallback
# ============================================================

def call_llm_chat(messages: list, json_mode: bool = False, temperature: float = None, scenario: str = "doubt_chat") -> str:
    """Executes a chat completion call routed to the LLM assigned to the given scenario from the Database.
    If the assigned provider fails or is missing, automatically cascades through active providers
    in database index order (LLMConfig.id ASC) with transparent terminal logging.
    """
    primary_cfg = get_scenario_llm_config(scenario)
    active_providers = get_all_active_providers()

    # Build candidates chain: Primary Assigned Provider first, then remaining active providers by ID index
    candidates = []
    if primary_cfg:
        candidates.append(primary_cfg)

    for p in active_providers:
        if not any(c.get("id") == p.get("id") for c in candidates):
            candidates.append(p)

    if not candidates:
        raise MistralUnavailableError(f"No active LLM configuration available in database for scenario '{scenario}'")

    last_error = None
    for idx, cfg in enumerate(candidates):
        p_id = cfg.get("id", "N/A")
        p_name = cfg.get("name", "Unknown")
        p_type = cfg.get("provider", "Unknown")
        m_name = cfg.get("model_name", "Default")
        b_url = cfg.get("base_url") or "Cloud Native"

        is_fallback = idx > 0
        if is_fallback:
            print(f"[LLM FALLBACK] Switching to Provider: '{p_name}' ({p_type}) | Model: '{m_name}' | URL: '{b_url}'", flush=True)
        else:
            print(f"[LLM ROUTING] Scenario: '{scenario}' -> Provider: '{p_name}' ({p_type}) | Model: '{m_name}' | URL: '{b_url}'", flush=True)

        try:
            res = _execute_provider_call(cfg, messages, json_mode, temperature)
            if res and res.strip():
                print(f"[LLM SUCCESS] Provider: '{p_name}' (Model: '{m_name}') responded successfully.", flush=True)
                return res
        except Exception as e:
            last_error = e
            print(f"[LLM ERROR] Provider: '{p_name}' (Model: '{m_name}') failed: {e}", flush=True)

    raise MistralUnavailableError(f"All active LLM providers in database failed for scenario '{scenario}'. Last error: {last_error}")


def call_llm(prompt: str, scenario: str = "doubt_chat") -> str:
    """Convenience single-prompt text completion."""
    return call_llm_chat([{"role": "user", "content": prompt}], json_mode=False, scenario=scenario)


def _clean_and_parse_json(raw_text: str) -> dict:
    """Robust JSON extractor with guardrails against markdown wrappers, preamble text, and stream truncation."""
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # 1. Direct JSON parse
    try:
        res = json.loads(text)
        if isinstance(res, list):
            return {"questions": res}
        return res
    except json.JSONDecodeError:
        pass

    # 2. Extract substring between first '{' and last '}'
    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        sub = text[start_idx : end_idx + 1]
        try:
            return json.loads(sub)
        except json.JSONDecodeError:
            pass

    # 3. Truncation Auto-Repair: Close truncated JSON arrays
    if '"questions"' in text or "'questions'" in text:
        q_pos = text.rfind("}")
        if q_pos != -1:
            repaired = text[:q_pos + 1].strip()
            if not repaired.endswith("]"):
                repaired += "\n  ]"
            if not repaired.endswith("}"):
                repaired += "\n}"
            if not repaired.startswith("{"):
                repaired = "{\n  \"questions\": [\n" + repaired
            try:
                parsed = json.loads(repaired)
                if isinstance(parsed, dict) and parsed.get("questions"):
                    return parsed
            except Exception:
                pass

    # 4. Regex extraction of individual valid JSON objects matching question structure
    question_objects = []
    object_matches = re.finditer(r'\{\s*"question"\s*:\s*.*?(?=\n\s*\{\s*"question"|\Z)', text, re.DOTALL)
    for m in object_matches:
        chunk = m.group(0).strip().rstrip(",")
        last_b = chunk.rfind("}")
        if last_b != -1:
            candidate = chunk[:last_b + 1]
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict) and "question" in obj:
                    question_objects.append(obj)
            except Exception:
                pass

    if question_objects:
        return {"questions": question_objects}

    return json.loads(text)



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
    api_key = db_cfg.get("api_key") or getattr(config, "MISTRAL_API_KEY", None)
    base_url = (db_cfg.get("base_url") or "").strip() or getattr(config, "MISTRAL_EMBED_URL", None)
    if not base_url and getattr(config, "MISTRAL_LOCAL_URL", None):
        base_url = getattr(config, "MISTRAL_LOCAL_URL", "").rstrip("/") + "/api/embeddings"

    model_name = db_cfg.get("model_name") or getattr(config, "MISTRAL_EMBED_MODEL", "mistral-embed")
    timeout = db_cfg.get("timeout", 600)

    if not base_url:
        raise MistralUnavailableError("Base URL for embeddings is missing in database and .env configuration.")

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
