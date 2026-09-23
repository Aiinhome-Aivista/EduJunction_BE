"""The ONLY module allowed to call the Mistral API directly (master prompt §12).
Controllers and helpers must go through this client, never httpx/requests
themselves. Handles retries and reports failure so callers can fall back
cleanly — it never fabricates a response pretending to be from Mistral.
"""
import json
import time
import warnings
import requests
import httpx

from utils.config import config
from utils.logger import logger, log_ai_call

MISTRAL_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_EMBED_URL = "https://api.mistral.ai/v1/embeddings"

MAX_RETRIES = config.LLM_MAX_RETRIES
TIMEOUT_SECONDS = config.LLM_TIMEOUT_SECONDS
LOCAL_TIMEOUT_SECONDS = config.LLM_LOCAL_TIMEOUT_SECONDS


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


def is_configured() -> bool:
    """Returns True if an active LLM configuration is available and valid."""
    try:
        db_cfg = _get_active_db_llm_config()
        if db_cfg:
            provider = str(db_cfg.get("provider", "")).lower().strip()
            if provider == "ollama":
                return True
            if db_cfg.get("api_key"):
                return True
        if config.MISTRAL_API_KEY or config.GEMINI_API_KEY:
            return True
    except Exception:
        pass
    return False


_last_db_cfg_time = 0
_cached_db_cfg = None


def _get_active_db_llm_config() -> dict | None:
    """Fetches the active LLM configuration from the database dynamically with short TTL cache."""
    global _last_db_cfg_time, _cached_db_cfg
    now = time.time()
    if _cached_db_cfg is not None and (now - _last_db_cfg_time) < 5:
        return _cached_db_cfg
    try:
        from database.dbConnection import get_session
        from model.models import LLMConfig
        with get_session() as session:
            active = session.query(LLMConfig).filter(LLMConfig.is_active == True).first()
            if active:
                _cached_db_cfg = {
                    "provider": (active.provider_name or "gemini").lower().strip(),
                    "display_title": active.display_title,
                    "base_url": active.base_url,
                    "api_key": active.api_key,
                    "model_name": active.model_name,
                    "max_tokens": active.max_tokens or 4096,
                    "temperature": float(active.temperature) if active.temperature is not None else 0.30,
                    "timeout": active.timeout_seconds or 30,
                }
                _last_db_cfg_time = now
                return _cached_db_cfg
    except Exception as e:
        pass
    return None


def call_llm_chat(messages: list, json_mode: bool = False, temperature: float = 0.3) -> str:
    db_cfg = _get_active_db_llm_config()
    if not db_cfg:
        raise Exception("Active LLM Configuration is missing from database")

    active_provider = str(db_cfg["provider"]).lower().strip()
    
    if active_provider != "ollama" and not db_cfg.get("api_key"):
        raise Exception("LLM API Key is missing for the active configuration")
    model_name = db_cfg.get("model_name")
    print(f"[LLM CALL] Provider: {active_provider} | Model: {model_name} (from Database)", flush=True)

    try:
        # 1. Mistral API
        if "mistral" in active_provider:
            base_url = db_cfg.get("base_url")
            if base_url:
                base_url = base_url.rstrip('/')
                if not base_url.endswith('/v1') and not base_url.endswith('/api') and not base_url.endswith('/chat/completions') and (":" in base_url.split("://")[-1] or "localhost" in base_url or "127.0.0.1" in base_url):
                    base_url = f"{base_url}/v1"
                url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url
            else:
                url = "https://api.mistral.ai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {db_cfg['api_key']}",
                "Content-Type": "application/json",
            }
            model_name = db_cfg.get("model_name") or "mistral-small-latest"
            timeout = db_cfg.get("timeout") or 45

            payload = {
                "model": model_name,
                "messages": messages,
                "temperature": temperature if temperature is not None else db_cfg.get("temperature", 0.3),
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            res = requests.post(url, json=payload, headers=headers, timeout=timeout)
            res.raise_for_status()
            data = res.json()
            return data["choices"][0]["message"]["content"].strip()

        # 2. Google Gemini Cloud
        elif "gemini" in active_provider:
            genai = _get_genai()
            if not genai:
                raise MistralUnavailableError("google-generativeai package is not installed.")
            
            effective_key = db_cfg["api_key"]
            effective_model = db_cfg.get("model_name") or "gemini-2.0-flash"
            genai.configure(api_key=effective_key)
            
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
            elif db_cfg:
                generation_config["temperature"] = db_cfg.get("temperature", 0.3)

            model = genai.GenerativeModel(
                model_name=effective_model,
                system_instruction=system_instruction,
                generation_config=generation_config
            )
            response = model.generate_content(contents)
            return response.text.strip()

        # 3. Native Ollama (Local Engine)
        elif active_provider == "ollama" and db_cfg and db_cfg.get("base_url") and ("/api/chat" in db_cfg["base_url"] or "11434" in db_cfg["base_url"]):
            base_url = db_cfg["base_url"].rstrip("/")
            url = f"{base_url}/api/chat" if not base_url.endswith("/api/chat") else base_url
            payload = {
                "model": db_cfg["model_name"],
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature if temperature is not None else db_cfg.get("temperature", 0.3)}
            }
            if json_mode:
                payload["format"] = "json"

            res = requests.post(url, json=payload, timeout=db_cfg.get("timeout", 60))
            res.raise_for_status()
            return res.json().get("message", {}).get("content", "").strip()

        # 4. Anthropic Claude API
        elif "anthropic" in active_provider or "claude" in active_provider:
            base_url = db_cfg.get("base_url") if db_cfg else None
            url = f"{base_url.rstrip('/')}/v1/messages" if base_url else "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": (db_cfg.get("api_key") if db_cfg else None) or "",
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
                "model": (db_cfg.get("model_name") if db_cfg else None) or "claude-3-5-sonnet-20241022",
                "max_tokens": (db_cfg.get("max_tokens") if db_cfg else None) or 4096,
                "messages": claude_messages,
                "temperature": temperature if temperature is not None else (db_cfg.get("temperature", 0.3) if db_cfg else 0.3),
            }
            if system_text:
                payload["system"] = system_text

            res = requests.post(url, headers=headers, json=payload, timeout=db_cfg.get("timeout", 40) if db_cfg else 40)
            res.raise_for_status()
            return res.json()["content"][0]["text"].strip()

        # 5. Standard OpenAI-Compatible API (OpenAI, Groq, DeepSeek)
        else:
            base_url = (db_cfg.get("base_url") if db_cfg else None) or "https://api.openai.com/v1"
            url = f"{base_url.rstrip('/')}/chat/completions" if not base_url.endswith("/chat/completions") else base_url
            
            url = db_cfg.get("base_url") or "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {db_cfg['api_key']}",
                "Content-Type": "application/json",
            }
            model_name = db_cfg.get("model_name") or "gpt-4o-mini"
            timeout = db_cfg.get("timeout") or 30

            payload = {
                "model": model_name,
                "messages": messages,
                "temperature": temperature if temperature is not None else (db_cfg.get("temperature", 0.3) if db_cfg else 0.3)
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            res = requests.post(url, json=payload, headers=headers, timeout=timeout)
            res.raise_for_status()
            data = res.json()
            return data["choices"][0]["message"]["content"].strip()

    except Exception as e:
        raise MistralUnavailableError(f"LLM Error ({active_provider}): {str(e)}") from e


def call_llm(prompt: str) -> str:
    return call_llm_chat([{"role": "user", "content": prompt}], json_mode=False)


def _clean_and_parse_json(raw_text: str) -> dict:
    """Robust JSON extractor with guardrails against markdown wrappers, preamble text, and trailing commas."""
    text = raw_text.strip()
    # Strip markdown fences
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
        # Locate outermost brackets { ... }
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            sub = text[start_idx : end_idx + 1]
            return json.loads(sub)
        raise


def generate_json(system_prompt: str, user_prompt: str, *, temperature: float = 0.4) -> dict:
    """Calls the active LLM with JSON-object response formatting and returns the parsed dict with guardrails."""
    # Ensure system prompt explicitly reinforces JSON output guardrails
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
            content = call_llm_chat(messages, json_mode=True, temperature=temperature)
            duration_ms = (time.time() - start) * 1000
            
            parsed = _clean_and_parse_json(content)
            log_ai_call("llm_generate_json", duration_ms, success=True)
            return parsed

        except (json.JSONDecodeError, MistralUnavailableError, Exception) as exc:
            duration_ms = (time.time() - start) * 1000
            last_error = str(exc)
            log_ai_call("llm_generate_json", duration_ms, success=False)

        if attempt <= MAX_RETRIES:
            time.sleep(0.5 * attempt)

    logger.error(f"LLM generate_json failed after retries: {last_error}")
    raise MistralUnavailableError(last_error or "Unknown LLM failure")


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Returns one embedding vector per input text via active provider's embeddings endpoint."""
    if not texts:
        return []

    db_cfg = _get_active_db_llm_config()
    if not db_cfg:
        raise MistralUnavailableError("Active LLM Configuration is missing from database")

    active_provider = str(db_cfg["provider"]).lower().strip()
    
    if active_provider != "ollama" and not db_cfg.get("api_key"):
        raise MistralUnavailableError("LLM API Key is missing for the active configuration")
        
    start = time.time()
    
    try:
        # 1. Mistral API
        if "mistral" in active_provider:
            base_url = db_cfg.get("base_url")
            if base_url:
                base_url = base_url.rstrip('/')
                if not base_url.endswith('/v1') and not base_url.endswith('/api') and not base_url.endswith('/embeddings') and (":" in base_url.split("://")[-1] or "localhost" in base_url or "127.0.0.1" in base_url):
                    base_url = f"{base_url}/v1"
                url = f"{base_url}/embeddings" if not base_url.endswith("/embeddings") else base_url
            else:
                url = "https://api.mistral.ai/v1/embeddings"
            
            headers = {
                "Authorization": f"Bearer {db_cfg['api_key']}",
                "Content-Type": "application/json",
            }
            payload = {"model": "mistral-embed", "input": texts}
            
            res = requests.post(url, json=payload, headers=headers, timeout=db_cfg.get("timeout") or 45)
            res.raise_for_status()
            data = res.json()["data"]
            duration_ms = (time.time() - start) * 1000
            log_ai_call(f"{active_provider}_embed", duration_ms, success=True)
            return [item["embedding"] for item in data]
            
        # 2. Native Ollama (Local Engine)
        elif active_provider == "ollama":
            base_url = db_cfg.get("base_url", "http://localhost:11434").rstrip("/")
            if "/api/chat" in base_url:
                base_url = base_url.replace("/api/chat", "")
            
            url = f"{base_url}/api/embed" if not base_url.endswith("/api/embed") else base_url
            payload = {
                "model": "nomic-embed-text",
                "input": texts
            }
            res = requests.post(url, json=payload, timeout=db_cfg.get("timeout") or 60)
            res.raise_for_status()
            data = res.json()
            duration_ms = (time.time() - start) * 1000
            log_ai_call(f"{active_provider}_embed", duration_ms, success=True)
            return data.get("embeddings", [])
            
        # 3. Standard OpenAI-Compatible API (OpenAI, Groq, DeepSeek)
        else:
            base_url = db_cfg.get("base_url")
            if base_url:
                base_url = base_url.rstrip('/')
                if not base_url.endswith('/v1') and not base_url.endswith('/api') and not base_url.endswith('/embeddings') and (":" in base_url.split("://")[-1] or "localhost" in base_url or "127.0.0.1" in base_url):
                    base_url = f"{base_url}/v1"
                url = f"{base_url}/embeddings" if not base_url.endswith("/embeddings") else base_url
            else:
                url = "https://api.openai.com/v1/embeddings"
            
            headers = {
                "Authorization": f"Bearer {db_cfg['api_key']}",
                "Content-Type": "application/json",
            }
            payload = {"model": "text-embedding-3-small", "input": texts}
            
            res = requests.post(url, json=payload, headers=headers, timeout=db_cfg.get("timeout") or 45)
            res.raise_for_status()
            data = res.json()["data"]
            duration_ms = (time.time() - start) * 1000
            log_ai_call(f"{active_provider}_embed", duration_ms, success=True)
            return [item["embedding"] for item in data]
            
    except Exception as exc:
        duration_ms = (time.time() - start) * 1000
        log_ai_call(f"{active_provider}_embed", duration_ms, success=False)
        raise MistralUnavailableError(str(exc)) from exc
