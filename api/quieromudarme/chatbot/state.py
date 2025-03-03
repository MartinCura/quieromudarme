"""Holds current state for chat conversations."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from enum import StrEnum, auto

from quieromudarme.chatbot.base import TelegramID
from quieromudarme.logging import setup_logger

logger = setup_logger()


class ConversationStatus(StrEnum):
    """Enum for user conversation status."""

    IDLE = auto()
    CREATING_SEARCH = auto()
    DELETING_SEARCH = auto()
    SENDING_FEEDBACK = auto()


class ConversationState:
    """Current state for a chat conversation, which is reset after a period of inactivity."""

    _status: ConversationStatus
    _last_change_at: datetime

    EXPIRATION_TIMEDELTA = timedelta(hours=12)

    def __init__(self, status: ConversationStatus = ConversationStatus.IDLE) -> None:
        """Initialize with a status and the current time."""
        self._last_change_at = datetime.now(tz=UTC)
        self._status = status

    @property
    def last_change_at(self) -> datetime:
        """Get the last time the conversation status was updated."""
        return self._last_change_at

    @property
    def status(self) -> ConversationStatus:
        """Get the current status."""
        if datetime.now(tz=UTC) > self._last_change_at + ConversationState.EXPIRATION_TIMEDELTA:
            logger.debug("Status expired, resetting to IDLE")
            self._status = ConversationStatus.IDLE
            self._last_change_at = datetime.now(tz=UTC)
        return self._status

    @status.setter
    def status(self, status: ConversationStatus) -> None:
        """Set the status, updating timestamp."""
        logger.debug("Setting status to %s", status)
        self._status = status
        self._last_change_at = datetime.now(tz=UTC)

    @status.deleter
    def status(self) -> None:
        """Reset status to IDLE, updating timestamp."""
        self._status = ConversationStatus.IDLE
        self._last_change_at = datetime.now(tz=UTC)


# TODO: this doesn't survive dev reloads, persist it somewhere?
conversation_states: defaultdict[TelegramID, ConversationState] = defaultdict(ConversationState)
