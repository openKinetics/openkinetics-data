from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from .models import Measurement, Release, ReleaseArtifact, Sequence, Substrate
from .release_precomputation import PRECOMPUTATION_VERSION


class ReleasePrecomputationTests(TestCase):
    def setUp(self):
        self.release = Release.objects.create(
            release_id="test-release",
            title="Test release",
            is_latest=True,
            manifest={"eligibility": {"rejected_rows_by_reason": {"missing_smiles": 2}}},
        )
        self.sequence_wild = Sequence.objects.create(
            sequence_id="seq-wild",
            primary_uniprot_id="P00001",
            sequence="AAAA",
            length=4,
            wild_type=True,
        )
        self.sequence_mutant = Sequence.objects.create(
            sequence_id="seq-mutant",
            primary_uniprot_id="P00002",
            sequence="AAAT",
            length=4,
            wild_type=False,
        )
        self.substrate_one = Substrate.objects.create(
            substrate_id="substrate-one",
            name="Substrate One",
        )
        self.substrate_two = Substrate.objects.create(
            substrate_id="substrate-two",
            name="Substrate Two",
        )

        self._measurement(
            "record-1",
            enzyme_name="Enzyme A",
            ec_number="1.1.1.1",
            ec_class="1",
            organism="Organism A",
            sequence=self.sequence_wild,
            substrate=self.substrate_one,
            source_db="brenda",
            verification_status="verified",
            has_literature_id=True,
            evidence_confidence_tier="high",
            kcat=1.0,
        )
        self._measurement(
            "record-2",
            enzyme_name="Enzyme A",
            ec_number="1.1.1.1",
            ec_class="1",
            organism="Organism A",
            sequence=self.sequence_mutant,
            substrate=self.substrate_one,
            source_db="brenda",
            verification_status="corrected",
            has_literature_id=False,
            evidence_confidence_tier="medium",
            km=2.0,
        )
        self._measurement(
            "record-3",
            enzyme_name="Enzyme B",
            ec_number="2.2.2.2",
            ec_class="2",
            organism="Organism B",
            sequence=self.sequence_wild,
            substrate=self.substrate_two,
            source_db="sabio_rk",
            verification_status="manual_review_required",
            evidence_confidence_tier="medium",
            kcat=3.0,
            km=4.0,
        )
        self._measurement(
            "record-4",
            enzyme_name="Enzyme C",
            ec_number="2.2.2.2",
            ec_class="2",
            organism="Organism B",
            sequence=self.sequence_wild,
            substrate=self.substrate_one,
            source_db="sabio_rk",
            verification_status="unverified",
            evidence_confidence_tier="low",
            km=5.0,
        )
        ReleaseArtifact.objects.create(
            release=self.release,
            artifact_key="manifest",
            family="metadata",
            label="Manifest",
            relative_path="manifest.json",
            available=True,
        )

    def _measurement(self, record_key, **overrides):
        values = {
            "release": self.release,
            "record_key": record_key,
            "measurement_key": "measurement-%s" % record_key,
            "measurement_id": "id-%s" % record_key,
            "enzyme_name": "Enzyme",
            "sequence": self.sequence_wild,
            "substrate": self.substrate_one,
            "pair_id": "pair-%s" % record_key,
        }
        values.update(overrides)
        return Measurement.objects.create(**values)

    def test_command_populates_all_release_payloads(self):
        stdout = StringIO()

        call_command(
            "precompute_release_data",
            release_id=self.release.release_id,
            stdout=stdout,
        )

        self.release.refresh_from_db()
        self.assertEqual(self.release.precomputation_version, PRECOMPUTATION_VERSION)
        self.assertIsNotNone(self.release.precomputed_at)
        self.assertEqual(self.release.precomputed_stats["measurements"], 4)
        self.assertEqual(self.release.precomputed_stats["sequences"], 2)
        self.assertEqual(self.release.precomputed_stats["substrates"], 2)
        self.assertEqual(
            [row["ec_class"] for row in self.release.precomputed_facets["ec_classes"]],
            ["1", "2"],
        )
        self.assertEqual(
            self.release.precomputed_download_stats["review_status_counts"],
            {
                "accepted": 1,
                "accepted_identity_only": 1,
                "further_checks": 1,
                "unreviewed_or_excluded": 1,
            },
        )
        self.assertIn("Precomputed test-release", stdout.getvalue())

    def test_endpoints_read_precomputed_payloads_without_aggregate_queries(self):
        call_command("precompute_release_data", release_id=self.release.release_id, verbosity=0)

        with self.assertNumQueries(1):
            stats_response = self.client.get("/api/stats/")
        with self.assertNumQueries(1):
            facets_response = self.client.get("/api/facets/")
        with self.assertNumQueries(2):
            downloads_response = self.client.get("/api/downloads/")

        self.assertEqual(stats_response.json()["counts"]["measurements"], 4)
        self.assertEqual(len(facets_response.json()["facets"]["ec_classes"]), 2)
        self.assertEqual(downloads_response.json()["stats"]["counts"]["datapoints"], 4)
        self.assertEqual(len(downloads_response.json()["groups"]["metadata"]), 1)

    def test_precomputed_endpoint_payloads_match_live_fallbacks(self):
        live_stats = self.client.get("/api/stats/").json()
        live_facets = self.client.get("/api/facets/").json()
        live_downloads = self.client.get("/api/downloads/").json()

        call_command("precompute_release_data", release_id=self.release.release_id, verbosity=0)

        self.assertEqual(self.client.get("/api/stats/").json(), live_stats)
        self.assertEqual(self.client.get("/api/facets/").json(), live_facets)
        self.assertEqual(self.client.get("/api/downloads/").json(), live_downloads)

    def test_endpoints_fall_back_for_release_without_current_precomputation(self):
        self.release.precomputed_stats = {"measurements": 999}
        self.release.precomputation_version = 0
        self.release.save(update_fields=["precomputed_stats", "precomputation_version"])

        response = self.client.get("/api/stats/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["counts"]["measurements"], 4)

    def test_default_command_targets_latest_release_only(self):
        older = Release.objects.create(
            release_id="older-release",
            title="Older release",
            is_latest=False,
        )

        call_command("precompute_release_data", verbosity=0)

        self.release.refresh_from_db()
        older.refresh_from_db()
        self.assertEqual(self.release.precomputation_version, PRECOMPUTATION_VERSION)
        self.assertEqual(older.precomputation_version, 0)
