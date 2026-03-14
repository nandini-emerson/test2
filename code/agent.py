
import os
import re
import logging
import asyncio
from typing import Any, Dict, Optional, Tuple
from functools import wraps

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator, ValidationError, constr
from dotenv import load_dotenv
from loguru import logger
import httpx
import openai
from tenacity import retry, stop_after_attempt, wait_exponential, RetryError

# =========================
# Configuration Management
# =========================

load_dotenv()

class Config:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    TICKET_DB_API_URL: str = os.getenv("TICKET_DB_API_URL", "")
    TICKET_DB_API_TOKEN: str = os.getenv("TICKET_DB_API_TOKEN", "")
    AUDIT_LOG_API_URL: str = os.getenv("AUDIT_LOG_API_URL", "")
    AUDIT_LOG_API_TOKEN: str = os.getenv("AUDIT_LOG_API_TOKEN", "")
    NOTIFICATION_API_URL: str = os.getenv("NOTIFICATION_API_URL", "")
    NOTIFICATION_API_TOKEN: str = os.getenv("NOTIFICATION_API_TOKEN", "")
    EVENT_ID: str = os.getenv("EVENT_ID", "")
    MAX_INPUT_LENGTH: int = 50000

    @classmethod
    def validate(cls):
        missing = []
        for attr in [
            "OPENAI_API_KEY", "TICKET_DB_API_URL", "TICKET_DB_API_TOKEN",
            "AUDIT_LOG_API_URL", "AUDIT_LOG_API_TOKEN",
            "NOTIFICATION_API_URL", "NOTIFICATION_API_TOKEN",
            "EVENT_ID"
        ]:
            if not getattr(cls, attr):
                missing.append(attr)
        if missing:
            raise RuntimeError(f"Missing required configuration(s): {', '.join(missing)}")

# Validate configuration at startup
try:
    Config.validate()
except Exception as e:
    logger.error(f"Configuration error: {e}")
    raise

# =========================
# Logging Configuration
# =========================

logger.remove()
logger.add("assistant.log", rotation="10 MB", retention="10 days", level="INFO")
logger.add(lambda msg: print(msg, end=""), level="INFO")

# =========================
# Input Models & Validation
# =========================

class UserInputModel(BaseModel):
    user_input: constr(strip_whitespace=True, min_length=1, max_length=Config.MAX_INPUT_LENGTH)
    user_context: Optional[Dict[str, Any]] = None

    @field_validator("user_input")
    @classmethod
    def clean_input(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Input cannot be empty.")
        # Remove dangerous characters, excessive whitespace, and control chars
        v = re.sub(r"[\x00-\x1f\x7f]", "", v)
        v = re.sub(r"\s+", " ", v)
        return v

class TicketCodeModel(BaseModel):
    ticket_code: constr(strip_whitespace=True, min_length=4, max_length=64)
    event_id: constr(strip_whitespace=True, min_length=1, max_length=64)

    @field_validator("ticket_code")
    @classmethod
    def validate_ticket_code(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.match(r"^[A-Z0-9\-]+$", v):
            raise ValueError("Ticket code must be alphanumeric (A-Z, 0-9, -).")
        return v

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("Event ID cannot be empty.")
        return v

# =========================
# Utility Functions
# =========================

def async_retry(*retry_args, **retry_kwargs):
    """Decorator for retrying async functions with tenacity."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            @retry(*retry_args, **retry_kwargs)
            async def inner():
                return await func(*args, **kwargs)
            return await inner()
        return wrapper
    return decorator

def error_response(message: str, error_type: str = "GeneralError", tips: Optional[str] = None, status_code: int = 400):
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error_type": error_type,
            "message": message,
            "tips": tips or "Please check your input and try again. If the problem persists, contact support."
        }
    )

# =========================
# LLM Interaction Module
# =========================

class LLMInteractionModule:
    """
    Handles prompt construction, LLM calls, and response parsing.
    """
    def __init__(self, api_key: str, model: str = "gpt-4o", temperature: float = 0.7, max_tokens: int = 2000):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.client = openai.AsyncOpenAI(api_key=self.api_key)
        self.backup_model = "gpt-3.5-turbo"

    @async_retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
    async def generate_llm_response(
        self,
        system_prompt: str,
        user_prompt: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Construct prompt and interact with LLM for natural language responses.
        Handles LLM API errors and timeouts with fallback to backup model.
        """
        messages = [{"role": "system", "content": system_prompt}]
        if context and "history" in context:
            for turn in context["history"]:
                messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": user_prompt})

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"LLM primary model failed: {e}. Trying backup model.")
            try:
                response = await self.client.chat.completions.create(
                    model=self.backup_model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens
                )
                return response.choices[0].message.content.strip()
            except Exception as e2:
                logger.error(f"LLM backup model also failed: {e2}")
                raise RuntimeError("LLM service is currently unavailable. Please try again later.")

# =========================
# Integration Layer Classes
# =========================

class TicketVerificationService:
    """
    Validates ticket authenticity and usage status by querying the ticket database.
    """
    def __init__(self, api_url: str, api_token: str):
        self.api_url = api_url
        self.api_token = api_token

    @async_retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
    async def verify_ticket(self, ticket_code: str, event_id: str) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        payload = {"ticket_code": ticket_code, "event_id": event_id}
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.post(
                    f"{self.api_url}/verify",
                    json=payload,
                    headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
                return data
            except httpx.HTTPStatusError as e:
                logger.error(f"Ticket DB API error: {e.response.text}")
                raise RuntimeError("Ticket database error.")
            except Exception as e:
                logger.error(f"Ticket verification failed: {e}")
                raise RuntimeError("Unable to verify ticket at this time.")

class AuditLogger:
    """
    Logs all ticket validation attempts and suspicious activities.
    """
    def __init__(self, api_url: str, api_token: str):
        self.api_url = api_url
        self.api_token = api_token

    @async_retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
    async def log_audit_event(self, ticket_code: str, event_id: str, action: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "ticket_code": ticket_code,
            "event_id": event_id,
            "action": action
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.post(
                    f"{self.api_url}/log",
                    json=payload,
                    headers=headers
                )
                resp.raise_for_status()
                return "Audit logged"
            except Exception as e:
                logger.error(f"Audit logging failed: {e}")
                raise RuntimeError("Audit logging failed.")

class NotificationDispatcher:
    """
    Sends notifications to attendees and alerts staff as needed.
    """
    def __init__(self, api_url: str, api_token: str):
        self.api_url = api_url
        self.api_token = api_token

    @async_retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
    async def send_notification(self, attendee_contact: str, message: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "contact": attendee_contact,
            "message": message
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.post(
                    f"{self.api_url}/notify",
                    json=payload,
                    headers=headers
                )
                resp.raise_for_status()
                return "Notification sent"
            except Exception as e:
                logger.error(f"Notification sending failed: {e}")
                raise RuntimeError("Notification delivery failed.")

# =========================
# Application Logic Layer
# =========================

class EntryAuthorizationEngine:
    """
    Determines entry eligibility based on ticket validation and usage status using decision tables.
    """
    @staticmethod
    def authorize_entry(validation_status: str, usage_status: str) -> bool:
        # Only valid and unused tickets are authorized
        if validation_status.lower() == "valid" and usage_status.lower() == "unused":
            return True
        return False

class EscalationManager:
    """
    Handles escalation of unresolved or complex issues to human staff.
    """
    def __init__(self, notification_dispatcher: NotificationDispatcher, audit_logger: AuditLogger):
        self.notification_dispatcher = notification_dispatcher
        self.audit_logger = audit_logger

    async def escalate_issue(self, issue_details: str, user_context: Optional[Dict[str, Any]] = None) -> str:
        try:
            staff_contact = "event_staff@concert.com"  # Placeholder; in real system, lookup staff contact
            await self.notification_dispatcher.send_notification(
                staff_contact,
                f"Escalation required: {issue_details}"
            )
            await self.audit_logger.log_audit_event(
                ticket_code=user_context.get("ticket_code", "N/A") if user_context else "N/A",
                event_id=user_context.get("event_id", "N/A") if user_context else "N/A",
                action="escalation"
            )
            return "Issue escalated to human staff."
        except Exception as e:
            logger.error(f"Escalation failed: {e}")
            return "Failed to escalate issue. Please contact event staff directly."

# =========================
# Presentation Layer
# =========================

class OutputFormatter:
    """
    Formats responses according to templates and output requirements.
    """
    @staticmethod
    def format_output(response_data: Dict[str, Any], template_type: str = "default") -> str:
        try:
            if template_type == "ticket_valid":
                return (
                    f"✅ Ticket {response_data['ticket_code']} is valid and unused. "
                    "You are authorized for entry. Enjoy the concert!"
                )
            elif template_type == "ticket_invalid":
                return (
                    f"❌ Ticket {response_data['ticket_code']} is invalid or already used. "
                    "Please contact event staff for assistance."
                )
            elif template_type == "escalation":
                return (
                    "Your issue has been escalated to human staff. Please wait for assistance."
                )
            elif template_type == "help":
                return (
                    "If you need help, please provide your ticket code or visit the event help desk with your ID."
                )
            else:
                return response_data.get("message", "Sorry, an error occurred.")
        except Exception as e:
            logger.error(f"Output formatting failed: {e}")
            return "Sorry, we could not process your request. Please try again."

class InputHandler:
    """
    Receives and parses user input from chat or email.
    """
    @staticmethod
    def parse_input(user_input: str) -> Tuple[str, Optional[str]]:
        """
        Returns (intent, ticket_code)
        """
        user_input = user_input.strip()
        if re.search(r"\bhelp\b", user_input, re.IGNORECASE):
            return ("help", None)
        match = re.search(r"\b([A-Z0-9\-]{4,64})\b", user_input.upper())
        if match:
            return ("verify_ticket", match.group(1))
        return ("unknown", None)

# =========================
# Main Agent Class
# =========================

class ConcertTicketCollectionAssistant:
    """
    Orchestrates all components for ticket verification and attendee assistance.
    """
    def __init__(self):
        self.llm = LLMInteractionModule(
            api_key=Config.OPENAI_API_KEY,
            model="gpt-4o",
            temperature=0.7,
            max_tokens=2000
        )
        self.ticket_verifier = TicketVerificationService(
            api_url=Config.TICKET_DB_API_URL,
            api_token=Config.TICKET_DB_API_TOKEN
        )
        self.audit_logger = AuditLogger(
            api_url=Config.AUDIT_LOG_API_URL,
            api_token=Config.AUDIT_LOG_API_TOKEN
        )
        self.notification_dispatcher = NotificationDispatcher(
            api_url=Config.NOTIFICATION_API_URL,
            api_token=Config.NOTIFICATION_API_TOKEN
        )
        self.entry_authorizer = EntryAuthorizationEngine()
        self.escalation_manager = EscalationManager(
            notification_dispatcher=self.notification_dispatcher,
            audit_logger=self.audit_logger
        )
        self.output_formatter = OutputFormatter()
        self.input_handler = InputHandler()
        self.system_prompt = (
            "You are the Concert Ticket Collection Assistant. Your role is to verify tickets, "
            "assist attendees, and ensure a smooth entry process for concert events. "
            "Always communicate professionally and escalate issues as needed."
        )
        self.user_prompt_template = (
            "Hello! Please provide your ticket code for verification. If you need assistance, type 'help'."
        )

    async def handle_user_input(self, user_input: str, user_context: Optional[Dict[str, Any]] = None) -> str:
        """
        Parse and route user input to the appropriate handler.
        """
        try:
            intent, ticket_code = self.input_handler.parse_input(user_input)
            if intent == "help":
                return self.output_formatter.format_output({}, template_type="help")
            elif intent == "verify_ticket" and ticket_code:
                ticket_result = await self.verify_ticket(ticket_code, Config.EVENT_ID)
                if ticket_result.get("validation_status") == "valid" and ticket_result.get("usage_status") == "unused":
                    await self.audit_logger.log_audit_event(ticket_code, Config.EVENT_ID, "validation_success")
                    return self.output_formatter.format_output(
                        {"ticket_code": ticket_code}, template_type="ticket_valid"
                    )
                else:
                    await self.audit_logger.log_audit_event(ticket_code, Config.EVENT_ID, "validation_failure")
                    return self.output_formatter.format_output(
                        {"ticket_code": ticket_code}, template_type="ticket_invalid"
                    )
            else:
                # Use LLM for unknown or general queries
                llm_response = await self.llm.generate_llm_response(
                    self.system_prompt,
                    user_input,
                    context=user_context
                )
                return llm_response
        except Exception as e:
            logger.error(f"Error in handle_user_input: {e}")
            return self.output_formatter.format_output(
                {"message": "Sorry, we could not process your request. Please try again."}
            )

    async def verify_ticket(self, ticket_code: str, event_id: str) -> Dict[str, Any]:
        """
        Validate ticket authenticity and usage status.
        """
        try:
            result = await self.ticket_verifier.verify_ticket(ticket_code, event_id)
            return result
        except Exception as e:
            logger.error(f"verify_ticket error: {e}")
            raise

    async def authorize_entry(self, validation_status: str, usage_status: str) -> bool:
        """
        Determine if attendee is authorized for entry.
        """
        try:
            return self.entry_authorizer.authorize_entry(validation_status, usage_status)
        except Exception as e:
            logger.error(f"authorize_entry error: {e}")
            return False

    async def log_audit_event(self, ticket_code: str, event_id: str, action: str) -> str:
        """
        Record ticket validation attempts and suspicious activities.
        """
        try:
            return await self.audit_logger.log_audit_event(ticket_code, event_id, action)
        except Exception as e:
            logger.error(f"log_audit_event error: {e}")
            raise

    async def send_notification(self, attendee_contact: str, message: str) -> str:
        """
        Send notifications to attendees or staff.
        """
        try:
            return await self.notification_dispatcher.send_notification(attendee_contact, message)
        except Exception as e:
            logger.error(f"send_notification error: {e}")
            raise

    async def escalate_issue(self, issue_details: str, user_context: Optional[Dict[str, Any]] = None) -> str:
        """
        Escalate unresolved or complex issues to human staff.
        """
        try:
            return await self.escalation_manager.escalate_issue(issue_details, user_context)
        except Exception as e:
            logger.error(f"escalate_issue error: {e}")
            return "Failed to escalate issue."

    async def generate_llm_response(self, system_prompt: str, user_prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Construct prompt and interact with LLM for natural language responses.
        """
        try:
            return await self.llm.generate_llm_response(system_prompt, user_prompt, context)
        except Exception as e:
            logger.error(f"generate_llm_response error: {e}")
            return "Sorry, I am unable to process your request at the moment."

    def format_output(self, response_data: Dict[str, Any], template_type: str = "default") -> str:
        """
        Format responses according to templates and output requirements.
        """
        try:
            return self.output_formatter.format_output(response_data, template_type)
        except Exception as e:
            logger.error(f"format_output error: {e}")
            return "Sorry, we could not process your request. Please try again."

# =========================
# FastAPI App & Endpoints
# =========================

app = FastAPI(
    title="Concert Ticket Collection Assistant API",
    description="API for verifying concert tickets and assisting attendees.",
    version="1.0.0"
)

# CORS middleware for cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

assistant_agent = ConcertTicketCollectionAssistant()

@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    logger.warning(f"Validation error: {exc}")
    return error_response(
        message="Invalid input data.",
        error_type="ValidationError",
        tips="Ensure your JSON is well-formed and all required fields are present."
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(f"HTTPException: {exc.detail}")
    return error_response(
        message=exc.detail,
        error_type="HTTPException",
        tips="Check your request and try again.",
        status_code=exc.status_code
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return error_response(
        message="An unexpected error occurred.",
        error_type="InternalServerError",
        tips="Please try again later or contact support.",
        status_code=500
    )

@app.post("/api/assistant/message")
async def assistant_message(input_data: UserInputModel):
    """
    Main endpoint for user interaction.
    """
    try:
        response_text = await assistant_agent.handle_user_input(
            input_data.user_input,
            input_data.user_context
        )
        return {
            "success": True,
            "response": response_text
        }
    except ValidationError as ve:
        logger.warning(f"Input validation error: {ve}")
        return error_response(
            message="Malformed JSON or invalid input.",
            error_type="JSONParseError",
            tips="Check for missing quotes, commas, or brackets. Ensure your input is valid JSON."
        )
    except Exception as e:
        logger.error(f"Error in /api/assistant/message: {e}")
        return error_response(
            message="Failed to process your request.",
            error_type="ProcessingError",
            tips="Try again or contact support."
        )

@app.post("/api/assistant/verify_ticket")
async def verify_ticket_endpoint(ticket_data: TicketCodeModel):
    """
    Endpoint for direct ticket verification.
    """
    try:
        result = await assistant_agent.verify_ticket(ticket_data.ticket_code, ticket_data.event_id)
        authorized = await assistant_agent.authorize_entry(
            result.get("validation_status", ""),
            result.get("usage_status", "")
        )
        if authorized:
            await assistant_agent.log_audit_event(ticket_data.ticket_code, ticket_data.event_id, "validation_success")
            response_text = assistant_agent.format_output(
                {"ticket_code": ticket_data.ticket_code}, template_type="ticket_valid"
            )
        else:
            await assistant_agent.log_audit_event(ticket_data.ticket_code, ticket_data.event_id, "validation_failure")
            response_text = assistant_agent.format_output(
                {"ticket_code": ticket_data.ticket_code}, template_type="ticket_invalid"
            )
        return {
            "success": True,
            "authorized": authorized,
            "response": response_text
        }
    except ValidationError as ve:
        logger.warning(f"Ticket validation error: {ve}")
        return error_response(
            message="Malformed JSON or invalid ticket data.",
            error_type="JSONParseError",
            tips="Check for missing quotes, commas, or brackets. Ensure your input is valid JSON."
        )
    except Exception as e:
        logger.error(f"Error in /api/assistant/verify_ticket: {e}")
        return error_response(
            message="Failed to verify ticket.",
            error_type="TicketVerificationError",
            tips="Ensure your ticket code and event ID are correct."
        )

@app.post("/api/assistant/escalate")
async def escalate_issue_endpoint(request: Request):
    """
    Endpoint to escalate an issue to human staff.
    """
    try:
        data = await request.json()
        issue_details = data.get("issue_details", "")
        user_context = data.get("user_context", {})
        if not issue_details:
            raise HTTPException(status_code=400, detail="issue_details is required.")
        result = await assistant_agent.escalate_issue(issue_details, user_context)
        return {
            "success": True,
            "response": result
        }
    except Exception as e:
        logger.error(f"Error in /api/assistant/escalate: {e}")
        return error_response(
            message="Failed to escalate issue.",
            error_type="EscalationError",
            tips="Provide issue details and try again."
        )

@app.post("/api/assistant/llm")
async def llm_response_endpoint(request: Request):
    """
    Endpoint to interact directly with the LLM.
    """
    try:
        data = await request.json()
        user_prompt = data.get("user_prompt", "")
        context = data.get("context", {})
        if not user_prompt:
            raise HTTPException(status_code=400, detail="user_prompt is required.")
        response = await assistant_agent.generate_llm_response(
            assistant_agent.system_prompt,
            user_prompt,
            context
        )
        return {
            "success": True,
            "response": response
        }
    except Exception as e:
        logger.error(f"Error in /api/assistant/llm: {e}")
        return error_response(
            message="Failed to generate LLM response.",
            error_type="LLMError",
            tips="Try again or contact support."
        )

@app.exception_handler(Exception)
async def catch_all_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return error_response(
        message="An unexpected error occurred.",
        error_type="InternalServerError",
        tips="Please try again later or contact support.",
        status_code=500
    )

@app.middleware("http")
async def catch_json_parsing_errors(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        logger.error(f"JSON parsing error: {exc}")
        return error_response(
            message="Malformed JSON in request body.",
            error_type="JSONParseError",
            tips="Check for missing quotes, commas, or brackets. Ensure your input is valid JSON.",
            status_code=400
        )

# =========================
# Main Execution
# =========================

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Concert Ticket Collection Assistant API...")
    uvicorn.run("agent:app", host="0.0.0.0", port=8000, reload=False)
