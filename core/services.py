"""
Service Layer for business logic.

This module contains service classes that encapsulate business logic
and orchestrate operations across models.
"""


class InvalidTransitionError(Exception):
    """Raised when an invalid status transition is attempted."""

    def __init__(self, current_status, new_status, allowed_transitions):
        self.current_status = current_status
        self.new_status = new_status
        self.allowed_transitions = allowed_transitions
        message = (
            f"Cannot transition from '{current_status}' to '{new_status}'. "
            f"Allowed transitions: {allowed_transitions}"
        )
        super().__init__(message)


class AppointmentService:
    """Service for managing Appointment business logic."""

    # State machine: defines valid transitions for each status
    ALLOWED_TRANSITIONS = {
        "PRE_BOOKED": ["CONFIRMED", "EXPIRED", "CANCELLED"],
        "CONFIRMED": ["COMPLETED", "NO_SHOW", "CANCELLED"],
        "COMPLETED": [],  # Terminal state
        "CANCELLED": [],  # Terminal state
        "NO_SHOW": [],    # Terminal state
        "EXPIRED": [],    # Terminal state
    }

    @classmethod
    def transition(cls, appointment, new_status):
        """
        Transition an appointment to a new status.

        Validates that the transition is allowed according to ALLOWED_TRANSITIONS.
        
        Args:
            appointment: Appointment instance
            new_status: Target status (str)
        
        Returns:
            Appointment: Updated appointment instance
        
        Raises:
            InvalidTransitionError: If transition is not allowed
        """
        current_status = appointment.status
        allowed = cls.ALLOWED_TRANSITIONS.get(current_status, [])

        if new_status not in allowed:
            raise InvalidTransitionError(current_status, new_status, allowed)

        appointment.status = new_status
        appointment.save()
        return appointment

    @classmethod
    def get_allowed_transitions(cls, current_status):
        """
        Get list of allowed transitions for a given status.
        
        Args:
            current_status: Current appointment status (str)
        
        Returns:
            list: List of allowed target statuses
        """
        return cls.ALLOWED_TRANSITIONS.get(current_status, [])

    @classmethod
    def can_transition(cls, current_status, new_status):
        """
        Check if a transition is allowed.
        
        Args:
            current_status: Current appointment status (str)
            new_status: Target status (str)
        
        Returns:
            bool: True if transition is allowed, False otherwise
        """
        return new_status in cls.ALLOWED_TRANSITIONS.get(current_status, [])
