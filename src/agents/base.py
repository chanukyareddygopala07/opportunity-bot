"""Base agent classes and interfaces for the AAWARA agent system.

Every agent inherits from BaseAgent and implements process().
The base class handles state management, metrics, retry logic, and event emission.
"""
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from src import db

logger = logging.getLogger(__name__)


class AgentStatus(str, Enum):
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    PAUSED = "paused"
    DISABLED = "disabled"
    REVIEW_REQUIRED = "review_required"


class AgentCategory(str, Enum):
    DISCOVERY = "discovery"
    INTELLIGENCE = "intelligence"
    USER = "user"
    QUALITY = "quality"


class AgentHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"
    OFFLINE = "offline"


class AgentEvent:
    """Structured event emitted by agents."""

    def __init__(self, event_type: str, agent_id: str, data: dict = None):
        self.event_id = str(uuid.uuid4())[:12]
        self.event_type = event_type
        self.agent_id = agent_id
        self.data = data or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self):
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "agent_id": self.agent_id,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class AgentEvidence:
    """Traceable evidence for extracted facts."""

    def __init__(self, field: str, value: Any, source_url: str = None,
                 source_text: str = None, confidence: float = 0.0,
                 agent_id: str = None):
        self.field = field
        self.value = value
        self.source_url = source_url
        self.source_text = source_text[:500] if source_text else None
        self.confidence = max(0.0, min(1.0, confidence))
        self.agent_id = agent_id
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self):
        return {
            "field": self.field,
            "value": self.value,
            "source_url": self.source_url,
            "source_text": self.source_text,
            "confidence": self.confidence,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
        }


class AgentResult:
    """Standardized result from agent processing."""

    def __init__(self, agent_id: str, status: AgentStatus = AgentStatus.COMPLETED,
                 data: dict = None, confidence: float = 0.0,
                 evidence: List[AgentEvidence] = None, error: str = None):
        self.agent_id = agent_id
        self.status = status
        self.data = data or {}
        self.confidence = max(0.0, min(1.0, confidence))
        self.evidence = evidence or []
        self.error = error
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self):
        return {
            "agent_id": self.agent_id,
            "status": self.status.value,
            "data": self.data,
            "confidence": self.confidence,
            "evidence": [e.to_dict() for e in self.evidence],
            "error": self.error,
            "timestamp": self.timestamp,
        }


class BaseAgent:
    """Base class for all AAWARA agents.

    Subclasses must implement:
    - AGENT_ID: unique string identifier
    - AGENT_NAME: human-readable name
    - AGENT_CATEGORY: discovery/intelligence/user/quality
    - AGENT_DESCRIPTION: what this agent does
    - process(input_data) -> AgentResult: the main processing logic
    """

    AGENT_ID = "base_agent"
    AGENT_NAME = "Base Agent"
    AGENT_CATEGORY = AgentCategory.INTELLIGENCE
    AGENT_DESCRIPTION = "Base agent class"
    MAX_RETRIES = 3
    RETRY_DELAYS = [2, 5, 15]  # seconds

    def __init__(self):
        self.status = AgentStatus.IDLE
        self.current_task_id = None
        self._metrics = {
            "total_tasks": 0,
            "successful_tasks": 0,
            "failed_tasks": 0,
            "total_duration_ms": 0,
            "avg_confidence": 0.0,
            "confidence_sum": 0.0,
            "last_run": None,
            "errors": [],
        }

    def process(self, input_data: dict) -> AgentResult:
        """Main processing method. Must be implemented by subclasses."""
        raise NotImplementedError(f"{self.AGENT_ID} must implement process()")

    def run(self, input_data: dict, task_id: str = None) -> AgentResult:
        """Execute the agent with metrics tracking and error handling."""
        task_id = task_id or str(uuid.uuid4())[:8]
        self.current_task_id = task_id
        self.status = AgentStatus.RUNNING
        start_time = time.monotonic()

        try:
            result = self.process(input_data)
            duration_ms = int((time.monotonic() - start_time) * 1000)

            self._metrics["total_tasks"] += 1
            if result.status == AgentStatus.COMPLETED:
                self._metrics["successful_tasks"] += 1
            elif result.status in (AgentStatus.FAILED, AgentStatus.REVIEW_REQUIRED):
                self._metrics["failed_tasks"] += 1

            self._metrics["total_duration_ms"] += duration_ms
            self._metrics["confidence_sum"] += result.confidence
            self._metrics["avg_confidence"] = (
                self._metrics["confidence_sum"] / self._metrics["total_tasks"]
            )
            self._metrics["last_run"] = datetime.now(timezone.utc).isoformat()

            self.status = result.status
            self._record_task(task_id, input_data, result, duration_ms)
            self._emit_event(result)

            return result

        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            self._metrics["total_tasks"] += 1
            self._metrics["failed_tasks"] += 1
            self._metrics["last_run"] = datetime.now(timezone.utc).isoformat()
            self._metrics["errors"].append(str(exc)[:200])

            self.status = AgentStatus.FAILED
            error_result = AgentResult(
                agent_id=self.AGENT_ID,
                status=AgentStatus.FAILED,
                error=str(exc)[:500],
            )
            self._record_task(task_id, input_data, error_result, duration_ms)
            self._emit_event(error_result)
            return error_result

    def _record_task(self, task_id: str, input_data, result: AgentResult,
                     duration_ms: int):
        """Record task execution to the agent_tasks table."""
        try:
            conn = db.get_connection()
            try:
                conn.execute(
                    "INSERT INTO agent_tasks "
                    "(task_id, agent_id, status, input_data, output_data, "
                    "confidence, error, duration_ms, created_at, completed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        task_id,
                        self.AGENT_ID,
                        result.status.value,
                        json.dumps(input_data, default=str),
                        json.dumps(result.to_dict(), default=str),
                        result.confidence,
                        result.error,
                        duration_ms,
                        result.timestamp,
                        result.timestamp,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("Failed to record agent task: %s", exc)

    def _emit_event(self, result: AgentResult):
        """Emit an agent event."""
        try:
            event_type = {
                AgentStatus.COMPLETED: f"{self.AGENT_ID}.completed",
                AgentStatus.FAILED: f"{self.AGENT_ID}.failed",
                AgentStatus.REVIEW_REQUIRED: f"{self.AGENT_ID}.review_required",
            }.get(result.status, f"{self.AGENT_ID}.status_changed")

            event = AgentEvent(event_type, self.AGENT_ID, {
                "task_id": self.current_task_id,
                "status": result.status.value,
                "confidence": result.confidence,
            })
            conn = db.get_connection()
            try:
                conn.execute(
                    "INSERT INTO agent_events (event_id, event_type, agent_id, data, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (event.event_id, event.event_type, event.agent_id,
                     json.dumps(event.data), event.timestamp),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("Failed to emit agent event: %s", exc)

    def get_health(self) -> AgentHealth:
        """Calculate agent health from metrics."""
        total = self._metrics["total_tasks"]
        if total == 0:
            return AgentHealth.HEALTHY
        success_rate = self._metrics["successful_tasks"] / total
        if success_rate >= 0.9:
            return AgentHealth.HEALTHY
        if success_rate >= 0.7:
            return AgentHealth.DEGRADED
        if success_rate >= 0.3:
            return AgentHealth.FAILING
        return AgentHealth.OFFLINE

    def get_metrics(self) -> dict:
        """Return current agent metrics."""
        return {
            "agent_id": self.AGENT_ID,
            "agent_name": self.AGENT_NAME,
            "status": self.status.value,
            "health": self.get_health().value,
            **self._metrics,
            "errors": self._metrics["errors"][-10:],  # last 10 errors
        }

    def to_dict(self) -> dict:
        """Serializable agent info."""
        return {
            "agent_id": self.AGENT_ID,
            "agent_name": self.AGENT_NAME,
            "category": self.AGENT_CATEGORY.value,
            "description": self.AGENT_DESCRIPTION,
            "status": self.status.value,
            "health": self.get_health().value,
            "metrics": self.get_metrics(),
        }
