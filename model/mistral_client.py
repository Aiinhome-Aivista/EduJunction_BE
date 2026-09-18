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

MISTRAL_CHAT_URL = config.MISTRAL_CHAT_URL
MISTRAL_EMBED_URL = config.MISTRAL_EMBED_URL

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
    # Now it depends on ACTIVE_LLM, but assuming True as routing handles it
    return True


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.MISTRAL_API_KEY}",
        "Content-Type": "application/json",
    }


def call_llm_chat(messages: list, json_mode: bool = False, temperature: float = 0.3) -> str:
    print(f"[LLM Client] Using ACTIVE_LLM: {config.ACTIVE_LLM}")
    try:
        # 1. Gemini Cloud
        if config.ACTIVE_LLM == "gemini":
            genai = _get_genai()
            if not genai:
                raise MistralUnavailableError("google-generativeai package is not installed.")
            genai.configure(api_key=config.GEMINI_API_KEY)
            
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
                model_name=config.MODEL_NAME or "gemini-2.5-flash",
                system_instruction=system_instruction,
                generation_config=generation_config
            )
            response = model.generate_content(contents)
            return response.text.strip()

        # 2. Mistral Cloud API
        elif config.ACTIVE_LLM == "mistral_cloud":
            url = config.MISTRAL_CHAT_URL
            headers = _headers()
            payload = {
                "model": config.MISTRAL_MODEL,
                "messages": messages,
                "temperature": temperature
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
                
            res = requests.post(url, json=payload, headers=headers, timeout=config.LLM_TIMEOUT_SECONDS)
            res.raise_for_status()
            data = res.json()
            return data["choices"][0]["message"]["content"].strip()

        # 3. 🧠 Local Ollama
        elif config.ACTIVE_LLM == "mistral_local":
            start_time = time.time()
            payload = {
                "model": config.MISTRAL_LOCAL_MODEL,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature}
            }
            if json_mode:
                payload["format"] = "json"

            url = f"{config.MISTRAL_LOCAL_URL}/api/chat"
            try:
                res = requests.post(url, json=payload, timeout=config.LLM_LOCAL_TIMEOUT_SECONDS)
                res.raise_for_status()
                data = res.json()
                print(f"[LLM Client] Local Mistral responded in {time.time() - start_time:.2f} seconds (Remote IP)")
                return data["message"]["content"].strip()
            except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError, requests.exceptions.HTTPError) as e:
                print(f"[LLM Client] Remote IP failed ({e}), trying fallback URL...")
                fallback_url = f"{config.MISTRAL_LOCAL_FALLBACK_URL}/api/chat"
                res = requests.post(fallback_url, json=payload, timeout=config.LLM_LOCAL_TIMEOUT_SECONDS)
                res.raise_for_status()
                data = res.json()
                print(f"[LLM Client] Local Mistral responded in {time.time() - start_time:.2f} seconds (Fallback Localhost)")
                return data["message"]["content"].strip()

        else:
            raise ValueError(f"Invalid ACTIVE_LLM configuration: {config.ACTIVE_LLM}")

    except Exception as e:
        raise MistralUnavailableError(f"LLM Error: {str(e)}") from e


def call_llm(prompt: str) -> str:
    return call_llm_chat([{"role": "user", "content": prompt}], json_mode=False)


def generate_json(system_prompt: str, user_prompt: str, *, temperature: float = 0.4) -> dict:
    """Calls the active LLM with JSON-object response formatting and returns the parsed dict."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    last_error = None
    for attempt in range(1, MAX_RETRIES + 2):
        start = time.time()
        try:
            content = call_llm_chat(messages, json_mode=True, temperature=temperature)
            duration_ms = (time.time() - start) * 1000
            
            parsed = json.loads(content)
            log_ai_call("llm_generate_json", duration_ms, success=True)
            return parsed

        except (json.JSONDecodeError, MistralUnavailableError) as exc:
            duration_ms = (time.time() - start) * 1000
            last_error = str(exc)
            log_ai_call("llm_generate_json", duration_ms, success=False)

        if attempt <= MAX_RETRIES:
            time.sleep(0.5 * attempt)

    logger.error(f"LLM generate_json failed after retries: {last_error}")
    raise MistralUnavailableError(last_error or "Unknown LLM failure")


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Returns one embedding vector per input text via Mistral's embeddings
    endpoint. Used by helper/embedding_engine.py for document ingestion."""
    if not is_configured():
        raise MistralUnavailableError("MISTRAL_API_KEY is not configured")
    if not texts:
        return []

    payload = {"model": config.MISTRAL_EMBED_MODEL, "input": texts}
    start = time.time()
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            resp = client.post(MISTRAL_EMBED_URL, headers=_headers(), json=payload)
        duration_ms = (time.time() - start) * 1000
        if resp.status_code != 200:
            log_ai_call("mistral_embed", duration_ms, success=False)
            raise MistralUnavailableError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()["data"]
        log_ai_call("mistral_embed", duration_ms, success=True)
        return [item["embedding"] for item in data]
    except httpx.HTTPError as exc:
        raise MistralUnavailableError(str(exc)) from exc
