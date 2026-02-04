"""
Management command to expire PRE_BOOKED appointments past their expires_at.

Usage:
    python manage.py expire_prebookings

Cron (every minute):
    */1 * * * * cd /path/to/project && .venv/bin/python manage.py expire_prebookings >> /var/log/expire_prebookings.log 2>&1
"""
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Appointment


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Mark PRE_BOOKED appointments with expires_at < now as EXPIRED"

    def handle(self, *args, **options):
        now = timezone.now()
        qs = Appointment.all_objects.filter(
            status="PRE_BOOKED",
            expires_at__lt=now,
        )
        count = qs.update(status="EXPIRED")
        if count > 0:
            logger.info("expire_prebookings: %d appointment(s) marked EXPIRED", count)
        self.stdout.write(self.style.SUCCESS(f"Expired {count} pre-booked appointment(s)"))
