import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Idempotently ensure a superuser exists, reading credentials from the "
        "DJANGO_SUPERUSER_USERNAME / DJANGO_SUPERUSER_EMAIL / "
        "DJANGO_SUPERUSER_PASSWORD environment variables. Safe to run on every "
        "deploy: creates the user if missing, otherwise resets its password and "
        "ensures staff/superuser flags. No-ops (without error) if the env vars "
        "are not set, so it won't break deploys where it isn't configured."
    )

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "info@familiarfaces.la")

        if not username or not password:
            self.stdout.write(
                "ensure_admin: DJANGO_SUPERUSER_USERNAME / "
                "DJANGO_SUPERUSER_PASSWORD not set; skipping."
            )
            return

        User = get_user_model()
        user, created = User.objects.get_or_create(
            **{User.USERNAME_FIELD: username}
        )

        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()

        verb = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(f"ensure_admin: {verb} superuser {username!r}.")
        )
