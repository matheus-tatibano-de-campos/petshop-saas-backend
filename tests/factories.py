"""
Factory Boy factories for test data generation.
"""
from datetime import timedelta
from decimal import Decimal

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory
from faker import Faker

from core.models import Appointment, Customer, Payment, Pet, Refund, Service, Tenant, User

fake = Faker("pt_BR")


class TenantFactory(DjangoModelFactory):
    class Meta:
        model = Tenant
        django_get_or_create = ("subdomain",)

    subdomain = factory.Sequence(lambda n: f"tenant{n}")
    name = factory.LazyAttribute(lambda o: f"{o.subdomain.title()} Company")
    is_active = True


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Faker("email")
    role = "OWNER"
    tenant = factory.SubFactory(TenantFactory)

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        if not create:
            return
        self.set_password(extracted or "testpass123")
        self.save()


class CustomerFactory(DjangoModelFactory):
    class Meta:
        model = Customer

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Faker("name", locale="pt_BR")
    cpf = factory.LazyFunction(lambda: fake.cpf().replace(".", "").replace("-", ""))
    email = factory.Faker("email")
    phone = factory.LazyFunction(lambda: fake.phone_number()[:20])


class PetFactory(DjangoModelFactory):
    class Meta:
        model = Pet

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Faker("first_name")
    species = factory.Iterator(["DOG", "CAT", "OTHER"])
    breed = factory.Iterator(["Labrador", "Poodle", "Siamês", "Persa", "Vira-lata"])
    customer = factory.SubFactory(CustomerFactory, tenant=factory.SelfAttribute("..tenant"))
    birth_date = factory.LazyFunction(lambda: timezone.now().date() - timedelta(days=365 * 2))


class ServiceFactory(DjangoModelFactory):
    class Meta:
        model = Service

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Iterator(["Banho", "Tosa", "Consulta Veterinária", "Vacina", "Hospedagem"])
    description = factory.Faker("sentence")
    price = factory.LazyFunction(lambda: Decimal(fake.random_int(min=30, max=200)))
    duration_minutes = factory.Iterator([30, 60, 90, 120])
    is_active = True


class AppointmentFactory(DjangoModelFactory):
    class Meta:
        model = Appointment

    tenant = factory.SubFactory(TenantFactory)
    pet = factory.SubFactory(PetFactory, tenant=factory.SelfAttribute("..tenant"))
    service = factory.SubFactory(ServiceFactory, tenant=factory.SelfAttribute("..tenant"))
    scheduled_at = factory.LazyFunction(lambda: timezone.now() + timedelta(hours=24))
    status = "PRE_BOOKED"

    # expires_at is set automatically by model.save() for PRE_BOOKED


class PaymentFactory(DjangoModelFactory):
    class Meta:
        model = Payment

    tenant = factory.SubFactory(TenantFactory)
    appointment = factory.SubFactory(
        AppointmentFactory, 
        tenant=factory.SelfAttribute("..tenant"),
        status="PRE_BOOKED"
    )
    amount = factory.LazyAttribute(lambda o: o.appointment.service.price * Decimal("0.5"))
    status = "PENDING"
    payment_id_external = factory.Sequence(lambda n: f"MP{n:010d}")
    webhook_processed = False


class RefundFactory(DjangoModelFactory):
    class Meta:
        model = Refund

    tenant = factory.SubFactory(TenantFactory)
    appointment = factory.SubFactory(
        AppointmentFactory,
        tenant=factory.SelfAttribute("..tenant"),
        status="CANCELLED"
    )
    amount = Decimal("45.00")
    status = "PENDING"
    reason = factory.Faker("sentence")
