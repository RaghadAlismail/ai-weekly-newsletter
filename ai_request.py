"""OpenAI requests with safe, actionable errors; never expose provider text or keys."""
import requests

def post_completion(url, *, headers, json, timeout=60):
    try:
        response = requests.post(url, headers=headers, json=json, timeout=timeout)
    except requests.Timeout:
        raise ValueError("AI request timed out. Retry generation.") from None
    except requests.RequestException:
        raise ValueError("Could not connect to the AI service. Retry generation.") from None
    if response.ok:
        return response
    try:
        error = response.json().get("error", {})
        if not isinstance(error, dict):
            error = {}
    except (ValueError, AttributeError):
        error = {}
    code = error.get("code")
    kind = error.get("type")
    status = response.status_code
    billing = {"insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached",
               "organization_spend_limit_exceeded", "project_spend_limit_exceeded",
               "organization_usage_limit_exceeded"}
    if code in billing or kind == "insufficient_quota":
        message = "OpenAI API credits or spending limit exhausted. Check API billing and project limits."
    elif status == 401:
        message = "OpenAI API key was rejected. Replace OPENAI_API_KEY in Render with a valid project key."
    elif code == "model_not_found" or status == 404:
        message = "Configured AI model is unavailable to this API project. Check OPENAI_MODEL and model access."
    elif status == 429:
        message = "OpenAI API rate limit reached. Wait briefly and retry generation."
    elif status == 403:
        message = "OpenAI API permission denied. Check key permissions and project access."
    elif status >= 500:
        message = "OpenAI service is temporarily unavailable. Retry generation."
    else:
        message = "OpenAI rejected the request settings. Contact the platform administrator."
    raise ValueError(message) from None
