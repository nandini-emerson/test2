
import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

# --- API Key Management and Validation ---
def get_env_var(var_name, default=None, required=False):
    value = os.getenv(var_name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {var_name}")
    return value

# --- LLM Configuration ---
LLM_CONFIG = {
    "provider": "openai",
    "model": os.getenv("LLM_MODEL", "gpt-4o"),
    "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
    "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "2000")),
    "system_prompt": os.getenv(
        "LLM_SYSTEM_PROMPT",
        "You are the Concert Ticket Collection Assistant. Your role is to verify tickets, assist attendees, and ensure a smooth entry process for concert events. Always communicate professionally and escalate issues as needed."
    ),
    "user_prompt_template": os.getenv(
        "LLM_USER_PROMPT_TEMPLATE",
        "Hello! Please provide your ticket code for verification. If you need assistance, type 'help'."
    ),
    "few_shot_examples": [
        "User: My ticket code is ABC12345. Assistant: Thank you. I am verifying your ticket now. Please wait a moment.",
        "User: I lost my ticket. What should I do? Assistant: I'm sorry to hear that. Please visit the event help desk with your ID for further assistance."
    ]
}

# --- API Integrations ---
API_CONFIG = {
    "ticket_database": {
        "url": get_env_var("TICKET_DB_API_URL", required=True),
        "auth_token": get_env_var("TICKET_DB_API_TOKEN", required=True),
        "rate_limit": int(os.getenv("TICKET_DB_API_RATE_LIMIT", "200")),
        "auth_type": "OAuth 2.0"
    },
    "audit_logging": {
        "url": get_env_var("AUDIT_LOG_API_URL", required=True),
        "auth_token": get_env_var("AUDIT_LOG_API_TOKEN", required=True),
        "rate_limit": int(os.getenv("AUDIT_LOG_API_RATE_LIMIT", "1000")),
        "auth_type": "OAuth 2.0"
    },
    "notification_service": {
        "url": get_env_var("NOTIFICATION_API_URL", required=True),
        "auth_token": get_env_var("NOTIFICATION_API_TOKEN", required=True),
        "rate_limit": int(os.getenv("NOTIFICATION_API_RATE_LIMIT", "100")),
        "auth_type": "OAuth 2.0"
    }
}

# --- Domain-Specific Settings ---
DOMAIN_SETTINGS = {
    "event_id": get_env_var("EVENT_ID", required=True),
    "max_concurrent_requests": int(os.getenv("MAX_CONCURRENT_REQUESTS", "200")),
    "ticket_code_pattern": os.getenv("TICKET_CODE_PATTERN", r"^[A-Z0-9\-]{4,64}$"),
    "purge_attendee_data_days": int(os.getenv("PURGE_ATTENDEE_DATA_DAYS", "30")),
    "audit_log_retention_days": int(os.getenv("AUDIT_LOG_RETENTION_DAYS", "90"))
}

# --- Validation and Error Handling ---
def validate_config():
    errors = []
    # Check LLM API key
    if not os.getenv("OPENAI_API_KEY"):
        errors.append("OPENAI_API_KEY is missing.")
    # Check API endpoints and tokens
    for api_name, api in API_CONFIG.items():
        if not api["url"]:
            errors.append(f"{api_name.upper()}_URL is missing.")
        if not api["auth_token"]:
            errors.append(f"{api_name.upper()}_TOKEN is missing.")
    # Check event ID
    if not DOMAIN_SETTINGS["event_id"]:
        errors.append("EVENT_ID is missing.")
    if errors:
        raise RuntimeError("Configuration validation failed: " + "; ".join(errors))

try:
    validate_config()
except Exception as e:
    logging.error(str(e))
    raise

# --- Default Values and Fallbacks ---
FALLBACKS = {
    "llm_backup_model": os.getenv("LLM_BACKUP_MODEL", "gpt-3.5-turbo"),
    "ticket_db_backup_url": os.getenv("TICKET_DB_BACKUP_API_URL", ""),
    "escalation_contact": os.getenv("ESCALATION_CONTACT", "event_staff@concert.com")
}

# --- Exported Configuration Object ---
class AgentConfig:
    # LLM
    LLM_PROVIDER = LLM_CONFIG["provider"]
    LLM_MODEL = LLM_CONFIG["model"]
    LLM_TEMPERATURE = LLM_CONFIG["temperature"]
    LLM_MAX_TOKENS = LLM_CONFIG["max_tokens"]
    LLM_SYSTEM_PROMPT = LLM_CONFIG["system_prompt"]
    LLM_USER_PROMPT_TEMPLATE = LLM_CONFIG["user_prompt_template"]
    LLM_FEW_SHOT_EXAMPLES = LLM_CONFIG["few_shot_examples"]
    LLM_BACKUP_MODEL = FALLBACKS["llm_backup_model"]

    # APIs
    TICKET_DB_API_URL = API_CONFIG["ticket_database"]["url"]
    TICKET_DB_API_TOKEN = API_CONFIG["ticket_database"]["auth_token"]
    TICKET_DB_API_RATE_LIMIT = API_CONFIG["ticket_database"]["rate_limit"]
    AUDIT_LOG_API_URL = API_CONFIG["audit_logging"]["url"]
    AUDIT_LOG_API_TOKEN = API_CONFIG["audit_logging"]["auth_token"]
    AUDIT_LOG_API_RATE_LIMIT = API_CONFIG["audit_logging"]["rate_limit"]
    NOTIFICATION_API_URL = API_CONFIG["notification_service"]["url"]
    NOTIFICATION_API_TOKEN = API_CONFIG["notification_service"]["auth_token"]
    NOTIFICATION_API_RATE_LIMIT = API_CONFIG["notification_service"]["rate_limit"]

    # Domain
    EVENT_ID = DOMAIN_SETTINGS["event_id"]
    MAX_CONCURRENT_REQUESTS = DOMAIN_SETTINGS["max_concurrent_requests"]
    TICKET_CODE_PATTERN = DOMAIN_SETTINGS["ticket_code_pattern"]
    PURGE_ATTENDEE_DATA_DAYS = DOMAIN_SETTINGS["purge_attendee_data_days"]
    AUDIT_LOG_RETENTION_DAYS = DOMAIN_SETTINGS["audit_log_retention_days"]

    # Fallbacks
    TICKET_DB_BACKUP_URL = FALLBACKS["ticket_db_backup_url"]
    ESCALATION_CONTACT = FALLBACKS["escalation_contact"]

# --- End of config.py ---
