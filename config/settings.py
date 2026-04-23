from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):

    # ── Kill switch ───────────────────────────────────────────
    kill_switch: bool = Field(True, env="KILL_SWITCH")
    staff_sink_email: str = Field("sink@program-staff.dev", env="STAFF_SINK_EMAIL")
    staff_sink_phone: str = Field("+000000000000", env="STAFF_SINK_PHONE")

    # ── LLM ──────────────────────────────────────────────────
    openrouter_api_key: str = Field("", env="OPENROUTER_API_KEY")
    anthropic_api_key: str = Field("", env="ANTHROPIC_API_KEY")
    llm_provider: str = Field("openrouter", env="LLM_PROVIDER")
    llm_model_dev: str = Field("deepseek/deepseek-chat", env="LLM_MODEL_DEV")
    llm_model_eval: str = Field("claude-sonnet-4-6", env="LLM_MODEL_EVAL")

    # ── Email ─────────────────────────────────────────────────
    resend_api_key: str = Field("", env="RESEND_API_KEY")
    resend_from_email: str = Field("", env="RESEND_FROM_EMAIL")
    email_reply_webhook_url: str = Field("", env="EMAIL_REPLY_WEBHOOK_URL")

    # ── SMS ──────────────────────────────────────────────────
    at_username: str = Field("sandbox", env="AT_USERNAME")
    at_api_key: str = Field("", env="AT_API_KEY")
    at_short_code: str = Field("", env="AT_SHORT_CODE")
    sms_webhook_url: str = Field("", env="SMS_WEBHOOK_URL")

    # ── HubSpot ───────────────────────────────────────────────
    hubspot_access_token: str = Field("", env="HUBSPOT_ACCESS_TOKEN")
    hubspot_portal_id: str = Field("", env="HUBSPOT_PORTAL_ID")

    # ── Cal.com ───────────────────────────────────────────────
    calcom_booking_url: str = Field("", env="CALCOM_BOOKING_URL")
    calcom_api_key: str = Field("", env="CALCOM_API_KEY")
    calcom_base_url: str = Field("http://localhost:3000", env="CALCOM_BASE_URL")
    calcom_event_type_id: str = Field("", env="CALCOM_EVENT_TYPE_ID")
    calcom_webhook_url: str = Field("", env="CALCOM_WEBHOOK_URL")

    # ── Langfuse ──────────────────────────────────────────────
    langfuse_public_key: str = Field("", env="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field("", env="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field("https://cloud.langfuse.com", env="LANGFUSE_HOST")

    # ── Server ────────────────────────────────────────────────
    server_host: str = Field("0.0.0.0", env="SERVER_HOST")
    server_port: int = Field(8000, env="SERVER_PORT")

    # ── Budget caps (USD) ─────────────────────────────────────
    budget_dev_llm: float = Field(4.00, env="BUDGET_DEV_LLM")
    budget_eval_llm: float = Field(12.00, env="BUDGET_EVAL_LLM")
    budget_total: float = Field(20.00, env="BUDGET_TOTAL")

    # ── Pricing (from tenacious_sales_data/seed) ──────────────
    junior_monthly_rate: int = Field(2500, env="JUNIOR_MONTHLY_RATE")
    mid_monthly_rate: int = Field(3500, env="MID_MONTHLY_RATE")
    senior_monthly_rate: int = Field(5000, env="SENIOR_MONTHLY_RATE")
    manager_monthly_rate: int = Field(7000, env="MANAGER_MONTHLY_RATE")
    junior_hourly_rate: int = Field(35, env="JUNIOR_HOURLY_RATE")
    senior_hourly_rate: int = Field(65, env="SENIOR_HOURLY_RATE")
    blended_hourly_rate: int = Field(50, env="BLENDED_HOURLY_RATE")
    project_acv_min: int = Field(15000, env="PROJECT_ACV_MIN")
    small_tool_project: int = Field(25000, env="SMALL_TOOL_PROJECT")
    mvp_project: int = Field(50000, env="MVP_PROJECT")
    mid_system_min: int = Field(75000, env="MID_SYSTEM_MIN")
    mid_system_max: int = Field(150000, env="MID_SYSTEM_MAX")
    large_platform_min: int = Field(200000, env="LARGE_PLATFORM_MIN")
    large_platform_max: int = Field(500000, env="LARGE_PLATFORM_MAX")
    
    # ── ACV ranges (from baseline_numbers.md) ────────────────
    acv_min: int = Field(10800, env="ACV_MIN")  # 3-engineer, 12-month at junior rate
    acv_max: int = Field(300000, env="ACV_MAX")
    project_acv_max: int = Field(500000, env="PROJECT_ACV_MAX")
    training_acv_min: int = Field(10000, env="TRAINING_ACV_MIN")
    training_acv_max: int = Field(50000, env="TRAINING_ACV_MAX")
    mid_outsourcing_min: int = Field(50000, env="MID_OUTSOURCING_MIN")
    mid_outsourcing_max: int = Field(200000, env="MID_OUTSOURCING_MAX")
    squad_min: int = Field(25000, env="SQUAD_MIN")
    platform_max: int = Field(500000, env="PLATFORM_MAX")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Single instance imported everywhere
settings = Settings()