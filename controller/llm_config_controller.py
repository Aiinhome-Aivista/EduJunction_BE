"""Admin LLM Configuration & Scenario Routing Controller for EduJunction.
Manages dynamic multi-provider LLM configurations and scenario-wise AI assignments.
"""
import time
import requests
from flask import request, g

from database.dbConnection import get_session
from middleware.authMiddleware import token_required
from middleware.roleMiddleware import roles_required
from model.models import LLMConfig, LLMScenarioAssignment
from model.mistral_client import clear_routing_cache
from utils.date_helper import now_ist
from utils.errors import AppError, NotFoundError, ValidationError
from utils.logger import logger
from utils.response import success


# Human-friendly scenario labels & descriptions
SCENARIO_METADATA = {
    "exam_generation": {
        "label": "All Exams",
        "description": "Generates curriculum-aligned question papers (MCQ, Short, Long) with solution keys."
    },
    "pdf_generation": {
        "label": "PDF & Book Question Extractor",
        "description": "Extracts questions and answers from uploaded textbook and chapter PDFs."
    },
    "doubt_chat": {
        "label": "AI Doubt Chatbot & Assistant",
        "description": "Interactive, instant doubt solving assistant for students."
    },
    "evaluation": {
        "label": "Descriptive Copy Evaluation",
        "description": "Evaluates handwritten/descriptive student answer sheets with step-by-step grading."
    },
    "diagnostic": {
        "label": "Diagnostic Analytics & Recommendations",
        "description": "Generates weak-area diagnostics, mastery scores, and remedial study plans."
    },
    "embeddings": {
        "label": "RAG Vector Embeddings (K-Graph)",
        "description": "Generates text embeddings for syllabus RAG retrieval and vector similarity search."
    },
    "vision_ocr": {
        "label": "Handwritten / Image OCR",
        "description": "Transcribes scanned question papers, diagrams, and student answer sheets."
    }
}


def _config_to_dict(c: LLMConfig) -> dict:
    masked_key = ""
    if c.api_key:
        if len(c.api_key) > 8:
            masked_key = f"{c.api_key[:4]}••••••••{c.api_key[-4:]}"
        else:
            masked_key = "••••••••"

    return {
        "id": c.id,
        "name": c.name,
        "providerType": c.provider_type,
        "modelName": c.model_name,
        "baseUrl": c.base_url or "",
        "apiKey": c.api_key or "",
        "apiKeyMasked": masked_key,
        "hasApiKey": bool(c.api_key),
        "timeoutSeconds": c.timeout_seconds or 600,
        "isActive": bool(c.is_active),
        "createdAt": c.created_at.isoformat() if c.created_at else None,
        "updatedAt": c.updated_at.isoformat() if c.updated_at else None,
    }


# ============================================================
# 1. LLM Provider Management APIs
# ============================================================

@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def get_llm_configs():
    """Retrieves all registered LLM provider configurations."""
    with get_session() as session:
        configs = session.query(LLMConfig).order_by(LLMConfig.id.asc()).all()
        return success({
            "configs": [_config_to_dict(c) for c in configs]
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def create_llm_config():
    """Registers a new LLM provider configuration."""
    payload = request.get_json(force=True, silent=True) or {}
    name = str(payload.get("name") or payload.get("displayTitle") or "").strip()
    provider_type = str(payload.get("providerType") or payload.get("providerName") or "gemini").strip().lower()
    model_name = str(payload.get("modelName", "")).strip()
    base_url = str(payload.get("baseUrl", "")).strip() or None
    api_key = str(payload.get("apiKey", "")).strip() or None
    timeout_seconds = int(payload.get("timeoutSeconds") or payload.get("timeout_seconds") or 600)
    is_active = bool(payload.get("isActive", True))

    if not name:
        name = f"{provider_type.capitalize()} ({model_name or 'Default'})"

    if not model_name:
        raise ValidationError("Model Name is required (e.g. gemini-2.0-flash, mistral-small-latest, gpt-4o)")

    with get_session() as session:
        if is_active:
            session.query(LLMConfig).update({"is_active": False})

        new_config = LLMConfig(
            name=name,
            provider_type=provider_type,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            is_active=is_active,
            created_at=now_ist(),
        )
        session.add(new_config)
        session.commit()
        session.refresh(new_config)

        return success({
            "message": f"LLM provider '{name}' added successfully",
            "config": _config_to_dict(new_config)
        }, 201)


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def update_llm_config(config_id: int):
    """Updates an existing LLM provider configuration."""
    payload = request.get_json(force=True, silent=True) or {}
    with get_session() as session:
        c = session.get(LLMConfig, int(config_id))
        if not c:
            raise NotFoundError("LLM Configuration not found")

        if "name" in payload or "displayTitle" in payload:
            c.name = str(payload.get("name") or payload.get("displayTitle")).strip()
        if "providerType" in payload or "providerName" in payload:
            c.provider_type = str(payload.get("providerType") or payload.get("providerName")).strip().lower()
        if "modelName" in payload:
            c.model_name = str(payload["modelName"]).strip()
        if "baseUrl" in payload:
            c.base_url = str(payload["baseUrl"]).strip() or None
        if "apiKey" in payload and payload["apiKey"] is not None:
            c.api_key = str(payload["apiKey"]).strip() or None
        if "timeoutSeconds" in payload and payload["timeoutSeconds"] is not None:
            c.timeout_seconds = int(payload["timeoutSeconds"])
        elif "timeout_seconds" in payload and payload["timeout_seconds"] is not None:
            c.timeout_seconds = int(payload["timeout_seconds"])
        if "isActive" in payload:
            c.is_active = bool(payload["isActive"])

        c.updated_at = now_ist()
        session.commit()
        clear_routing_cache()

        return success({
            "message": "LLM Configuration updated successfully",
            "config": _config_to_dict(c)
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def set_active_llm_config(config_id: int):
    """Sets a specific LLM configuration as active."""
    with get_session() as session:
        c = session.get(LLMConfig, int(config_id))
        if not c:
            raise NotFoundError("LLM Configuration not found")

        c.is_active = True
        c.updated_at = now_ist()
        session.commit()
        clear_routing_cache()

        return success({
            "message": f"'{c.name}' is now Active.",
            "config": _config_to_dict(c)
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def delete_llm_config(config_id: int):
    """Deletes an LLM configuration."""
    with get_session() as session:
        c = session.get(LLMConfig, int(config_id))
        if not c:
            raise NotFoundError("LLM Configuration not found")

        count = session.query(LLMConfig).count()
        if count <= 1:
            raise ValidationError("Cannot delete the only remaining LLM provider.")

        session.delete(c)
        session.commit()
        return success({"message": f"LLM Configuration '{c.name}' deleted successfully"})


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def test_llm_connection(config_id: int):
    """POST /api/v1/admin/llm-config/<id>/test — Quick, robust connectivity test using DB credentials."""
    with get_session() as session:
        c = session.get(LLMConfig, int(config_id))
        if not c:
            raise NotFoundError("LLM Configuration not found")

        provider = (c.provider_type or "").lower().strip()
        model_name = c.model_name
        api_key = c.api_key
        base_url = c.base_url

        start_time = time.time()
        test_messages = [{"role": "user", "content": "Say 'OK' in one word."}]

        print(f"[LLM TEST] Provider ID: {config_id} | Provider: {provider} | Model: {model_name} | URL: {base_url}", flush=True)

        from model.mistral_client import (
            _call_gemini, _call_mistral_cloud, _call_mistral_local, _call_openai, _call_claude
        )

        timeout = c.timeout_seconds or 600
        try:
            if "gemini" in provider:
                reply = _call_gemini(test_messages, False, 0.1, api_key, model_name, timeout=timeout)
            elif "mistral_local" in provider or "local" in provider or provider == "ollama":
                reply = _call_mistral_local(test_messages, False, 0.1, model_name, base_url, timeout=timeout)
            elif "mistral" in provider:
                reply = _call_mistral_cloud(test_messages, False, 0.1, api_key, model_name, base_url, timeout=timeout)
            elif "claude" in provider or "anthropic" in provider:
                reply = _call_claude(test_messages, False, 0.1, api_key, model_name, base_url, timeout=timeout)
            else:
                reply = _call_openai(test_messages, False, 0.1, api_key, model_name, base_url, timeout=timeout)

            elapsed_ms = round((time.time() - start_time) * 1000, 2)

            return success({
                "status": True,
                "success": True,
                "provider": c.provider_type,
                "modelName": c.model_name,
                "latencyMs": elapsed_ms,
                "msg": f"Connection verified in {elapsed_ms}ms!",
                "message": f"Connection verified in {elapsed_ms}ms!",
                "response": reply[:200]
            }, message=f"Connection verified in {elapsed_ms}ms!")

        except Exception as e:
            elapsed_ms = round((time.time() - start_time) * 1000, 2)
            err_str = str(e).lower()
            logger.warning(f"LLM test connection failed for {c.name}: {e}")

            short_msg = "Connection test failed."
            if "401" in err_str or "unauthorized" in err_str:
                short_msg = "API Key is invalid or expired."
            elif "429" in err_str or "quota" in err_str or "billing" in err_str or "too many requests" in err_str:
                short_msg = "API quota exceeded."
            elif "404" in err_str or "not found" in err_str:
                if "model" in err_str:
                    short_msg = f"Invalid Model Name '{model_name}'."
                else:
                    short_msg = "The provider API URL is incorrect."
            elif "405" in err_str or "method not allowed" in err_str:
                short_msg = "The provider API endpoint is incorrect (e.g. use /api/chat)."
            elif "timeout" in err_str:
                short_msg = "Server took too long to respond."
            elif "connection refused" in err_str or "failed to establish" in err_str or "max retries" in err_str:
                short_msg = "The server is offline or unreachable."
            else:
                short_msg = f"Connection failed ({str(e)[:80]})"

            return success({
                "status": False,
                "success": False,
                "provider": c.provider_type,
                "modelName": c.model_name,
                "latencyMs": elapsed_ms,
                "msg": short_msg,
                "message": short_msg,
                "error": str(e)
            }, message=short_msg, statusCode=400)


# ============================================================
# 2. Scenario-wise Dynamic Routing APIs
# ============================================================

@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def get_llm_scenarios():
    """Retrieves all business scenarios and their currently assigned LLM providers."""
    with get_session() as session:
        assignments = session.query(LLMScenarioAssignment).order_by(LLMScenarioAssignment.id.asc()).all()
        providers = session.query(LLMConfig).all()
        provider_map = {p.id: p for p in providers}

        result = []
        for a in assignments:
            p = provider_map.get(a.provider_id)
            meta = SCENARIO_METADATA.get(a.scenario, {
                "label": a.scenario.replace("_", " ").title(),
                "description": "AI-powered educational service."
            })
            result.append({
                "id": a.id,
                "scenario": a.scenario,
                "label": meta["label"],
                "description": meta["description"],
                "providerId": a.provider_id,
                "providerName": p.name if p else "Unassigned",
                "providerType": p.provider_type if p else "unknown",
                "modelName": p.model_name if p else "unknown",
                "temperature": a.temperature if a.temperature is not None else 0.30,
                "maxTokens": a.max_tokens if a.max_tokens is not None else 2048,
            })

        return success({
            "scenarios": result,
            "providers": [_config_to_dict(p) for p in providers]
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def update_llm_scenarios():
    """Updates scenario-wise LLM provider assignments in bulk."""
    payload = request.get_json(force=True, silent=True) or {}
    assignments_data = payload.get("assignments", [])

    if not assignments_data or not isinstance(assignments_data, list):
        raise ValidationError("assignments list is required in payload")

    with get_session() as session:
        updated_count = 0
        for item in assignments_data:
            scenario_key = str(item.get("scenario", "")).strip()
            provider_id = item.get("provider_id") or item.get("providerId")

            if not scenario_key or provider_id is None:
                continue

            p = session.get(LLMConfig, int(provider_id))
            if not p:
                continue

            assignment = session.query(LLMScenarioAssignment).filter(
                LLMScenarioAssignment.scenario == scenario_key
            ).first()

            if assignment:
                changed = False
                if assignment.provider_id != int(provider_id):
                    assignment.provider_id = int(provider_id)
                    changed = True
                if "temperature" in item and item["temperature"] is not None:
                    new_temp = float(item["temperature"])
                    if assignment.temperature != new_temp:
                        assignment.temperature = new_temp
                        changed = True
                if "max_tokens" in item and item["max_tokens"] is not None:
                    new_tok = int(item["max_tokens"])
                    if assignment.max_tokens != new_tok:
                        assignment.max_tokens = new_tok
                        changed = True
                elif "maxTokens" in item and item["maxTokens"] is not None:
                    new_tok = int(item["maxTokens"])
                    if assignment.max_tokens != new_tok:
                        assignment.max_tokens = new_tok
                        changed = True

                if changed:
                    updated_count += 1
            else:
                new_assignment = LLMScenarioAssignment(
                    scenario=scenario_key,
                    provider_id=int(provider_id),
                    temperature=float(item.get("temperature", 0.30)),
                    max_tokens=int(item.get("max_tokens") or item.get("maxTokens") or 2048)
                )
                session.add(new_assignment)
                updated_count += 1

        if updated_count > 0:
            session.commit()
            try:
                from model.mistral_client import clear_routing_cache
                clear_routing_cache()
            except Exception:
                pass
            msg = f"Successfully updated {updated_count} scenario routing assignment(s)."
        else:
            msg = "No changes detected in scenario routing."

        return success({
            "message": msg,
            "updatedCount": updated_count
        })
