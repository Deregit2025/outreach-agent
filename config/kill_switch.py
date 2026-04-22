"""
Kill switch — required by the data-handling policy.

When KILL_SWITCH=true (the default), all outbound is redirected
to the program staff sink. Real prospects never receive anything
unless a human explicitly sets KILL_SWITCH=false.

Usage:
    from config.kill_switch import route_email, route_phone

    to_email = route_email("cto@realcompany.com")
    to_phone = route_phone("+12025551234")
    # During challenge week, both return the staff sink address.
"""

from config.settings import settings


def is_live() -> bool:
    """Returns True only when kill switch is explicitly disabled."""
    return not settings.kill_switch


def route_email(intended_recipient: str) -> str:
    """
    Returns the actual email address to send to.
    In safe mode (default): always returns staff sink.
    In live mode: returns the real recipient.
    """
    if not is_live():
        return settings.staff_sink_email
    return intended_recipient


def route_phone(intended_number: str) -> str:
    """
    Returns the actual phone number to SMS.
    In safe mode (default): always returns staff sink number.
    In live mode: returns the real number.
    """
    if not is_live():
        return settings.staff_sink_phone
    return intended_number


def assert_safe_mode() -> None:
    """
    Call at startup to log current kill-switch state clearly.
    Raises a warning (not an error) if live mode is active.
    """
    if is_live():
        print("⚠️  KILL SWITCH IS OFF — outbound will reach REAL prospects.")
        print("⚠️  Make sure Tenacious has approved live deployment.")
    else:
        print("✓  Kill switch ON — all outbound routes to staff sink.")
        print(f"   Sink email : {settings.staff_sink_email}")
        print(f"   Sink phone : {settings.staff_sink_phone}")