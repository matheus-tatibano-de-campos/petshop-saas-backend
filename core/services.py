"""
Service Layer for business logic.

This module contains service classes that encapsulate business logic
and orchestrate operations across models.
"""
from decimal import Decimal

from django.utils import timezone

from .exceptions import InvalidTransitionError
from .models import Payment


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


class CancellationService:
    """Service for appointment cancellation and refund calculation."""

    # Refund policy: >24h=90%, 24h-2h=80%, <2h=0%
    REFUND_PERCENT_OVER_24H = Decimal("0.90")
    REFUND_PERCENT_24H_TO_2H = Decimal("0.80")
    REFUND_PERCENT_UNDER_2H = Decimal("0")

    @classmethod
    def calculate_refund(cls, appointment):
        """
        Calculate refund amount based on cancellation timing.

        >24h before scheduled_at: 90% of paid amount
        24h-2h before: 80% of paid amount
        <2h before: 0%

        Args:
            appointment: Appointment instance (must be CONFIRMED with Payment)

        Returns:
            Decimal: Refund amount (0 if no payment or <2h before)
        """
        try:
            payment = appointment.payment
        except Payment.DoesNotExist:
            return Decimal("0")

        if payment.status != "APPROVED":
            return Decimal("0")

        paid_amount = Decimal(str(payment.amount))
        now = timezone.now()
        scheduled_at = appointment.scheduled_at

        if scheduled_at.tzinfo is None:
            scheduled_at = timezone.make_aware(scheduled_at)

        hours_until = (scheduled_at - now).total_seconds() / 3600

        if hours_until > 24:
            refund_percent = cls.REFUND_PERCENT_OVER_24H
        elif hours_until >= 2:
            refund_percent = cls.REFUND_PERCENT_24H_TO_2H
        else:
            refund_percent = cls.REFUND_PERCENT_UNDER_2H

        refund_amount = (paid_amount * refund_percent).quantize(Decimal("0.01"))
        return refund_amount
