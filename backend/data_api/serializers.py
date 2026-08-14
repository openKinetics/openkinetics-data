"""JSON serializers for the public API."""


def metric_payload(value, unit):
    return {
        "value": value,
        "unit": unit or None,
        "available": value is not None,
    }


def sequence_payload(sequence, include_sequence=False):
    payload = {
        "sequence_id": sequence.sequence_id,
        "primary_uniprot_id": sequence.primary_uniprot_id,
        "length": sequence.length,
        "source": sequence.source,
        "source_url": sequence.source_url,
        "sequence_variant_status": sequence.sequence_variant_status,
        "mutation_signature": sequence.mutation_signature,
        "wild_type": sequence.wild_type,
    }
    if include_sequence:
        payload["sequence"] = sequence.sequence
        payload["fasta_header"] = sequence.fasta_header
    return payload


def substrate_payload(substrate):
    return {
        "substrate_id": substrate.substrate_id,
        "name": substrate.name,
        "pubchem_query": substrate.pubchem_query,
        "pubchem_cid": substrate.pubchem_cid,
        "smiles": substrate.smiles,
        "canonical_smiles": substrate.canonical_smiles,
        "isomeric_smiles": substrate.isomeric_smiles,
        "inchi_key": substrate.inchi_key,
        "iupac_name": substrate.iupac_name,
        "molecular_formula": substrate.molecular_formula,
        "source": substrate.source,
        "source_url": substrate.source_url,
    }


def split_payload(measurement):
    return {
        row.split_family: row.split
        for row in measurement.split_assignments.all()
    }


def measurement_summary(measurement):
    return {
        "record_key": measurement.record_key,
        "measurement_key": measurement.measurement_key,
        "measurement_id": measurement.measurement_id,
        "enzyme_name": measurement.enzyme_name,
        "ec_number": measurement.ec_number,
        "ec_class": measurement.ec_class,
        "organism": measurement.organism,
        "primary_uniprot_id": measurement.primary_uniprot_id,
        "sequence_id": measurement.sequence.sequence_id,
        "substrate_id": measurement.substrate.substrate_id,
        "substrate_name": measurement.substrate.name,
        "kcat": metric_payload(measurement.kcat, measurement.kcat_unit),
        "km": metric_payload(measurement.km, measurement.km_unit),
        "ki": metric_payload(measurement.ki, measurement.ki_unit),
        "kcat_over_km": metric_payload(measurement.kcat_over_km, measurement.kcat_over_km_unit),
        "ph": measurement.ph,
        "temperature_c": measurement.temperature_c,
        "source_db": measurement.source_db,
        "verification_status": measurement.verification_status,
        "evidence_confidence_tier": measurement.evidence_confidence_tier,
        "paper_grounding_status": measurement.paper_grounding_status,
        "has_proof_excerpt": measurement.has_proof_excerpt,
        "wild_type": measurement.sequence.wild_type,
        "sequence_variant_status": measurement.sequence.sequence_variant_status,
    }


def measurement_detail(measurement):
    payload = measurement_summary(measurement)
    payload.update(
        {
            "release_id": measurement.release.release_id,
            "review_key": measurement.review_key,
            "enzyme": {
                "name": measurement.enzyme_name,
                "ec_number": measurement.ec_number,
                "organism": measurement.organism,
                "primary_uniprot_id": measurement.primary_uniprot_id,
                "identity_resolution_state": measurement.identity_resolution_state,
                "uniprot_candidate_ids": measurement.uniprot_candidate_ids,
            },
            "sequence": sequence_payload(measurement.sequence, include_sequence=True),
            "substrate": substrate_payload(measurement.substrate),
            "assay_conditions": {
                "ph": measurement.ph,
                "temperature_c": measurement.temperature_c,
                "temperature_k": measurement.temperature_k,
                "temperature_display": measurement.temperature_display,
            },
            "provenance": {
                "source_db": measurement.source_db,
                "source_record_count": measurement.source_record_count,
                "has_literature_id": measurement.has_literature_id,
                "pmid_count": measurement.pmid_count,
                "doi_count": measurement.doi_count,
                "literature_id_count": measurement.literature_id_count,
                "literature_linkage": measurement.literature_linkage,
            },
            "evidence": {
                "verification_status": measurement.verification_status,
                "evidence_confidence_tier": measurement.evidence_confidence_tier,
                "paper_grounding_status": measurement.paper_grounding_status,
                "has_proof_excerpt": measurement.has_proof_excerpt,
                "compact_evidence_summary": measurement.compact_evidence_summary,
            },
            "splits": split_payload(measurement),
            "artifact_keys": {
                "embedding_key": measurement.sequence.sequence_id,
                "binding_site_prediction_key": measurement.sequence.sequence_id,
            },
        }
    )
    return payload


def release_payload(release, include_manifest=False):
    payload = {
        "release_id": release.release_id,
        "title": release.title,
        "generated_at": release.generated_at.isoformat() if release.generated_at else None,
        "record_count": release.record_count,
        "is_latest": release.is_latest,
        "source_sha256": release.source_sha256,
        "attribution": release.attribution,
    }
    if include_manifest:
        payload["manifest"] = release.manifest
        payload["schema"] = release.schema
    return payload


def artifact_payload(artifact):
    return {
        "artifact_key": artifact.artifact_key,
        "family": artifact.family,
        "label": artifact.label,
        "description": artifact.description,
        "relative_path": artifact.relative_path,
        "url": artifact.url,
        "content_type": artifact.content_type,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
        "available": artifact.available,
        "metadata": artifact.metadata,
    }

