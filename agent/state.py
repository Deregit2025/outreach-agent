from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class QualificationAnswers(BaseModel):
    q1_initiative: Optional[str] = None    # top engineering priority
    q2_timeline: Optional[str] = None      # milestone / deadline pressure
    q3_blocker: Optional[str] = None       # what is slowing the initiative
    q4_stakeholders: Optional[str] = None  # who else decides

    def answered_count(self) -> int:
        return sum(
            1 for v in [self.q1_initiative, self.q2_timeline,
                        self.q3_blocker, self.q4_stakeholders]
            if v is not None
        )

    def is_complete(self) -> bool:
        return self.answered_count() == 4


class MessageRecord(BaseModel):
    direction: str          # "out" | "in"
    channel: str            # "email" | "sms"
    timestamp: str
    subject: Optional[str] = None
    body: str
    tone_score: Optional[float] = None
    send_result: Optional[dict] = None


class ConversationState(BaseModel):
    prospect_id: str
    company_name: str

    # Lead stage — drives channel routing and decision engine
    stage: str = "new"

    # ICP segment assigned by classifier; 0 = abstain
    segment: int = 0
    segment_confidence: str = "low"

    # Touch counts per channel
    email_touches: int = 0
    sms_touches: int = 0
    follow_up_sent: bool = False

    # Qualification progress
    qualification: QualificationAnswers = Field(default_factory=QualificationAnswers)

    # Full message log
    messages: list[MessageRecord] = Field(default_factory=list)

    # Timestamps
    first_contact_at: Optional[str] = None
    last_reply_at: Optional[str] = None
    booked_at: Optional[str] = None
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Escalation flag
    escalated: bool = False
    escalation_reason: Optional[str] = None

    def record_outbound(
        self,
        channel: str,
        body: str,
        subject: str | None = None,
        tone_score: float | None = None,
        send_result: dict | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.messages.append(MessageRecord(
            direction="out",
            channel=channel,
            timestamp=now,
            subject=subject,
            body=body,
            tone_score=tone_score,
            send_result=send_result,
        ))
        if channel == "email":
            self.email_touches += 1
        elif channel == "sms":
            self.sms_touches += 1
        if self.first_contact_at is None:
            self.first_contact_at = now
        self.updated_at = now

    def record_inbound(self, channel: str, body: str, subject: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.messages.append(MessageRecord(
            direction="in",
            channel=channel,
            timestamp=now,
            subject=subject,
            body=body,
        ))
        self.last_reply_at = now
        self.updated_at = now

    def transition_to(self, new_stage: str) -> None:
        self.stage = new_stage
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def has_replied(self) -> bool:
        return any(m.direction == "in" for m in self.messages)

    def next_unanswered_question(self) -> int | None:
        """Return Q number (1-4) of the next unanswered qualification question."""
        q = self.qualification
        if q.q1_initiative is None:
            return 1
        if q.q2_timeline is None:
            return 2
        if q.q3_blocker is None:
            return 3
        if q.q4_stakeholders is None:
            return 4
        return None
