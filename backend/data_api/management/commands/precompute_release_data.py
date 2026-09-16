import time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from data_api.models import Release
from data_api.release_precomputation import PRECOMPUTATION_VERSION, precompute_release


class Command(BaseCommand):
    help = "Precompute expensive stats, facets, and download stats for one or more releases."

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group()
        target.add_argument(
            "--release-id",
            help="Release ID to precompute. Defaults to the active/latest release.",
        )
        target.add_argument(
            "--all",
            action="store_true",
            help="Precompute every release in newest-first order.",
        )

    def handle(self, *args, **options):
        queryset = Release.objects.order_by("-generated_at", "-created_at")
        release_id = options.get("release_id")

        if release_id:
            queryset = queryset.filter(release_id=release_id)
        elif not options.get("all"):
            latest = queryset.filter(is_latest=True).first() or queryset.first()
            queryset = queryset.filter(pk=latest.pk) if latest else queryset.none()

        release_ids = list(queryset.values_list("release_id", flat=True))
        if not release_ids:
            if release_id:
                raise CommandError("Release not found: %s" % release_id)
            raise CommandError("No releases exist to precompute.")

        for target_release_id in release_ids:
            started = time.monotonic()
            self.stdout.write("Precomputing release %s..." % target_release_id)
            with transaction.atomic():
                release = Release.objects.select_for_update().get(
                    release_id=target_release_id
                )
                payloads = precompute_release(release)

            elapsed = time.monotonic() - started
            self.stdout.write(
                self.style.SUCCESS(
                    "Precomputed %s (version=%s, stats=%s keys, facets=%s keys, "
                    "download_stats=%s keys) in %.2fs"
                    % (
                        target_release_id,
                        PRECOMPUTATION_VERSION,
                        len(payloads["stats"]),
                        len(payloads["facets"]),
                        len(payloads["download_stats"]),
                        elapsed,
                    )
                )
            )
