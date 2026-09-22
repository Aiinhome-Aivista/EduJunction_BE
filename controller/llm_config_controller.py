"""Admin LLM Configuration Controller for EduJunction.
Manages dynamic multi-provider LLM configurations (Gemini, OpenAI, Claude, Ollama, Mistral, Groq, DeepSeek, Custom).
"""
import time
import uuid
import requests
from flask import request, g

from database.dbConnection import get_session
from middleware.authMiddleware import token_required
from middleware.roleMiddleware import roles_required
from model.models import LLMConfig
from utils.date_helper import now_ist
from utils.errors import AppError, NotFoundError, ValidationError
from utils.logger import logger
from utils.response import success


def _config_to_dict(c: LLMConfig) -> dict:
    masked_key = ""
    if c.api_key:
        if len(c.api_key) > 8:
            masked_key = f"{c.api_key[:4]}••••••••{c.api_key[-4:]}"
        else:
            masked_key = "••••••••"

    return {
        "id": c.id,
        "providerName": c.provider_name,
        "displayTitle": c.display_title,
        "baseUrl": c.base_url or "",
        "apiKey": c.api_key or "",
        "apiKeyMasked": masked_key,
        "hasApiKey": bool(c.api_key),
        "modelName": c.model_name,
        "maxTokens": c.max_tokens or 4096,
        "temperature": float(c.temperature) if c.temperature is not None else 0.30,
        "timeoutSeconds": c.timeout_seconds or 30,
        "isActive": bool(c.is_active),
        "createdAt": c.created_at.isoformat() if c.created_at else None,
        "updatedAt": c.updated_at.isoformat() if c.updated_at else None,
    }


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def get_llm_configs():
    """Retrieves all registered LLM provider configurations."""
    with get_session() as session:
        configs = session.query(LLMConfig).order_by(LLMConfig.created_at.asc()).all()
        return success({
            "configs": [_config_to_dict(c) for c in configs]
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def create_llm_config():
    """Registers a new LLM provider configuration."""
    payload = request.get_json(force=True, silent=True) or {}
    provider_name = str(payload.get("providerName", "gemini")).strip().lower()
    display_title = str(payload.get("displayTitle", "")).strip() or f"{provider_name.capitalize()} Engine"
    base_url = str(payload.get("baseUrl", "")).strip() or None
    api_key = str(payload.get("apiKey", "")).strip() or None
    model_name = str(payload.get("modelName", "")).strip()
    max_tokens = int(payload.get("maxTokens", 4096))
    temperature = float(payload.get("temperature", 0.30))
    timeout_seconds = int(payload.get("timeoutSeconds", 30))
    is_active = bool(payload.get("isActive", False))

    if not model_name:
        raise ValidationError("Model Name is required (e.g. gemini-2.0-flash, gpt-4o, llama3.2)")

    with get_session() as session:
        if is_active:
            session.query(LLMConfig).update({"is_active": False})

        new_config = LLMConfig(
            id=str(uuid.uuid4()),
            provider_name=provider_name,
            display_title=display_title,
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
            is_active=is_active,
            created_at=now_ist(),
        )
        session.add(new_config)
        session.commit()

        return success({
            "message": f"LLM provider '{display_title}' added successfully",
            "config": _config_to_dict(new_config)
        }, 201)


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def update_llm_config(config_id: str):
    """Updates an existing LLM provider configuration."""
    payload = request.get_json(force=True, silent=True) or {}
    with get_session() as session:
        c = session.get(LLMConfig, config_id)
        if not c:
            raise NotFoundError("LLM Configuration not found")

        if "providerName" in payload:
            c.provider_name = str(payload["providerName"]).strip().lower()
        if "displayTitle" in payload:
            c.display_title = str(payload["displayTitle"]).strip()
        if "baseUrl" in payload:
            c.base_url = str(payload["baseUrl"]).strip() or None
        if "apiKey" in payload and payload["apiKey"] is not None:
            c.api_key = str(payload["apiKey"]).strip() or None
        if "modelName" in payload:
            c.model_name = str(payload["modelName"]).strip()
        if "maxTokens" in payload:
            c.max_tokens = int(payload["maxTokens"])
        if "temperature" in payload:
            c.temperature = float(payload["temperature"])
        if "timeoutSeconds" in payload:
            c.timeout_seconds = int(payload["timeoutSeconds"])
        if "isActive" in payload:
            new_active = bool(payload["isActive"])
            if new_active and not c.is_active:
                session.query(LLMConfig).update({"is_active": False})
            c.is_active = new_active

        c.updated_at = now_ist()
        session.commit()

        return success({
            "message": "LLM Configuration updated successfully",
            "config": _config_to_dict(c)
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def set_active_llm_config(config_id: str):
    """Sets a specific LLM configuration as active across the whole backend."""
    with get_session() as session:
        c = session.get(LLMConfig, config_id)
        if not c:
            raise NotFoundError("LLM Configuration not found")

        session.query(LLMConfig).update({"is_active": False})
        c.is_active = True
        c.updated_at = now_ist()
        session.commit()

        return success({
            "message": f"'{c.display_title}' is now the ACTIVE LLM Engine for EduJunction.",
            "config": _config_to_dict(c)
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def delete_llm_config(config_id: str):
    """Deletes an LLM configuration."""
    with get_session() as session:
        c = session.get(LLMConfig, config_id)
        if not c:
            raise NotFoundError("LLM Configuration not found")

        if c.is_active:
            raise ValidationError("Cannot delete the currently ACTIVE LLM Engine. Please activate another provider first.")

        session.delete(c)
        session.commit()
        return success({"message": f"LLM Configuration '{c.display_title}' deleted successfully"})


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def test_llm_connection(config_id: str):
    """Executes a live test prompt to verify connectivity, authentication, and measure response latency."""
    with get_session() as session:
        c = session.get(LLMConfig, config_id)
        if not c:
            raise NotFoundError("LLM Configuration not found")

        provider = (c.provider_name or "").lower()
        model_name = c.model_name
        api_key = c.api_key
        base_url = c.base_url
        timeout = c.timeout_seconds or 30

        start_time = time.time()
        test_prompt = "Hello! Please respond with exactly: 'LLM Connection Verified Successfully.'"

        try:
            # 1. Google Gemini
            if "gemini" in provider:
                import google.generativeai as genai
                from utils.config import config as app_cfg
                effective_key = api_key or app_cfg.GEMINI_API_KEY
                if not effective_key:
                    raise ValidationError("Gemini API Key is missing. Please provide a valid key.")
                genai.configure(api_key=effective_key)
                m = genai.GenerativeModel(model_name=model_name or "gemini-2.0-flash")
                res = m.generate_content(test_prompt)
                reply = res.text.strip() if res else "No response"

            # 2. Native Ollama Local
            elif provider == "ollama" and base_url and "/api/chat" in base_url or (base_url and "11434" in base_url and not "/v1" in base_url):
                url = f"{base_url.rstrip('/')}/api/chat"
                r = requests.post(
                    url,
                    json={"model": model_name, "messages": [{"role": "user", "content": test_prompt}], "stream": False},
                    timeout=timeout,
                )
                r.raise_for_status()
                reply = r.json().get("message", {}).get("content", "").strip()

            # 3. Anthropic Claude
            elif "anthropic" in provider or "claude" in provider:
                url = f"{base_url.rstrip('/')}/v1/messages" if base_url else "https://api.anthropic.com/v1/messages"
                headers = {
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                }
                r = requests.post(
                    url,
                    headers=headers,
                    json={"model": model_name, "max_tokens": 50, "messages": [{"role": "user", "content": test_prompt}]},
                    timeout=timeout,
                )
                r.raise_for_status()
                reply = r.json()["content"][0]["text"].strip()

            # 4. Standard OpenAI-Compatible API (OpenAI, Groq, Mistral, DeepSeek, Custom)
            else:
                url = f"{base_url.rstrip('/')}/chat/completions" if base_url else "https://api.openai.com/v1/chat/completions"
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                r = requests.post(
                    url,
                    headers=headers,
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": test_prompt}],
                        "max_tokens": 50,
                    },
                    timeout=timeout,
                )
                r.raise_for_status()
                reply = r.json()["choices"][0]["message"]["content"].strip()

            elapsed_ms = round((time.time() - start_time) * 1000, 2)

            return success({
                "success": True,
                "provider": c.provider_name,
                "modelName": c.model_name,
                "latencyMs": elapsed_ms,
                "response": reply,
                "message": f"Connection verified in {elapsed_ms}ms! Response: {reply[:80]}"
            })

        except Exception as e:
            elapsed_ms = round((time.time() - start_time) * 1000, 2)
            logger.warning(f"LLM test connection failed for {c.display_title}: {e}")
            return success({
                "success": False,
                "provider": c.provider_name,
                "modelName": c.model_name,
                "latencyMs": elapsed_ms,
                "error": str(e),
                "message": f"Connection test failed ({str(e)})"
            }, 400)
