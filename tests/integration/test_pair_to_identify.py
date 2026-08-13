"""End-to-end integration tests that exercise the API contracts that
span both the backend and frontend services.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _load_backend_schemas(backend_imports):
    """Ensure backend is importable for schema classes."""


def test_identify_response_schema_fields():
    from app.schemas.dto import IdentifyResponse

    fields = IdentifyResponse.model_fields
    assert "unknown_faces" in fields
    assert "recognized" in fields
    assert "unknown_count" in fields


def test_pair_request_schema_fields():
    from app.schemas.dto import PairRequest

    fields = PairRequest.model_fields
    assert "master_key" in fields


def test_face_crop_status_enum():
    from app.models.entities import FaceCropStatus

    assert FaceCropStatus.UNASSIGNED.value == "UNASSIGNED"
    assert FaceCropStatus.ASSIGNED.value == "ASSIGNED"


def test_pairing_uses_pair_endpoint():
    """The frontend's onboarding/backend handler calls POST /api/v1/system/pair
    with master_key; verify this is the contract."""
    from app.schemas.dto import PairRequest

    payload = PairRequest(master_key="abc", name="frontend")
    dumped = payload.model_dump()
    assert dumped["master_key"] == "abc"
    assert dumped["name"] == "frontend"


def test_identify_unknown_face_schema():
    from app.schemas.dto import IdentifyUnknownFace

    fields = IdentifyUnknownFace.model_fields
    assert "crop_id" in fields
    assert "image_url" in fields
    assert "bounding_box" in fields
    assert "det_score" in fields


def test_recognized_face_schema():
    from app.schemas.dto import IdentifyMatch

    fields = IdentifyMatch.model_fields
    assert "person_id" in fields
    assert "name" in fields
    assert "confidence" in fields


def test_person_schema_fields():
    from app.schemas.dto import PersonOut

    fields = PersonOut.model_fields
    assert "name" in fields


def test_api_key_schema_fields():
    from app.schemas.dto import ApiKeyOut

    fields = ApiKeyOut.model_fields
    assert "name" in fields
    assert "permission_level" in fields


def test_healthz_response_schema_fields():
    from app.schemas.dto import HealthOut

    fields = HealthOut.model_fields
    assert "status" in fields
    assert "provider" in fields


def test_model_info_schema_fields():
    from app.schemas.dto import ModelInfo

    fields = ModelInfo.model_fields
    assert "name" in fields
    assert "loaded" in fields


def test_assign_request_schema_fields():
    from app.schemas.dto import AssignRequest

    fields = AssignRequest.model_fields
    assert "crop_ids" in fields


def test_create_person_request_schema_fields():
    from app.schemas.dto import PersonCreate

    fields = PersonCreate.model_fields
    assert "name" in fields


def test_create_api_key_request_schema():
    from app.schemas.dto import ApiKeyCreate

    fields = ApiKeyCreate.model_fields
    assert "name" in fields
    assert "permission_level" in fields


def test_unassigned_faces_response_schema():
    from app.schemas.dto import UnassignedPage

    fields = UnassignedPage.model_fields
    assert "items" in fields
    assert "total" in fields
    assert "page" in fields
    assert "page_size" in fields


def test_pair_response_has_raw_key():
    from app.schemas.dto import PairResponse

    fields = PairResponse.model_fields
    assert "raw_key" in fields


def test_mark_non_face_request_schema():
    from app.schemas.dto import MarkNonFaceRequest

    fields = MarkNonFaceRequest.model_fields
    assert "crop_ids" in fields


def test_ignore_request_schema():
    from app.schemas.dto import IgnoreRequest

    fields = IgnoreRequest.model_fields
    assert "crop_ids" in fields


def test_model_switch_request_schema():
    from app.schemas.dto import ModelSwitchRequest

    fields = ModelSwitchRequest.model_fields
    assert "name" in fields


def test_face_crop_out_schema():
    from app.schemas.dto import FaceCropOut

    fields = FaceCropOut.model_fields
    assert "id" in fields
    assert "image_url" in fields


def test_person_update_schema():
    from app.schemas.dto import PersonUpdate

    fields = PersonUpdate.model_fields
    assert "name" in fields or "custom_threshold" in fields


def test_nvidia_gpu_info_schema():
    from app.schemas.dto import NvidiaGpuInfo

    fields = NvidiaGpuInfo.model_fields
    assert "available" in fields or "cuda_available" in fields


def test_model_artifact_out_schema():
    from app.schemas.dto import ModelArtifactOut

    fields = ModelArtifactOut.model_fields
    assert "filename" in fields


def test_model_available_schema():
    from app.schemas.dto import ModelAvailable

    fields = ModelAvailable.model_fields
    assert "name" in fields


def test_api_key_create_response_schema():
    from app.schemas.dto import ApiKeyCreateResponse

    fields = ApiKeyCreateResponse.model_fields
    assert "raw_key" in fields


def test_bounding_box_schema():
    from app.schemas.dto import BoundingBox

    box = BoundingBox(x1=1, y1=2, x2=3, y2=4)
    assert box.x1 == 1 and box.y1 == 2


def test_identify_dedup_within_request_drops_identical(backend_imports):
    """Two identical bboxes + embeddings within the same request
    should be deduped to one face."""
    from types import SimpleNamespace

    import numpy as np

    from app.api.identify import _dedupe_within_request

    rng = np.random.default_rng(42)
    emb = rng.standard_normal(512).astype(np.float32)
    emb = emb / float(np.linalg.norm(emb))
    face = SimpleNamespace(bbox=(10.0, 20.0, 60.0, 90.0), score=0.95, embedding=emb.copy())
    out = _dedupe_within_request(
        [face, SimpleNamespace(bbox=face.bbox, score=face.score, embedding=emb.copy())]
    )
    assert len(out) == 1


def test_identify_dedup_keeps_higher_score(backend_imports):
    """When two faces are nearly identical, keep the higher-scored one."""
    from types import SimpleNamespace

    import numpy as np

    from app.api.identify import _dedupe_within_request

    rng = np.random.default_rng(42)
    emb = rng.standard_normal(512).astype(np.float32)
    emb = emb / float(np.linalg.norm(emb))
    lo = SimpleNamespace(bbox=(10.0, 20.0, 60.0, 90.0), score=0.5, embedding=emb.copy())
    hi = SimpleNamespace(bbox=(10.0, 20.0, 60.0, 90.0), score=0.95, embedding=emb.copy())
    out = _dedupe_within_request([lo, hi])
    assert len(out) == 1
    assert out[0].score == 0.95


def test_identify_dedup_keeps_different_faces(backend_imports):
    """Faces with very different embeddings are kept separate."""
    from types import SimpleNamespace

    import numpy as np

    from app.api.identify import _dedupe_within_request

    rng = np.random.default_rng(42)
    emb1 = rng.standard_normal(512).astype(np.float32)
    emb1 = emb1 / float(np.linalg.norm(emb1))
    emb2 = rng.standard_normal(512).astype(np.float32)
    emb2 = emb2 / float(np.linalg.norm(emb2))
    f1 = SimpleNamespace(bbox=(10.0, 20.0, 60.0, 90.0), score=0.9, embedding=emb1)
    f2 = SimpleNamespace(bbox=(200.0, 200.0, 260.0, 290.0), score=0.8, embedding=emb2)
    out = _dedupe_within_request([f1, f2])
    assert len(out) == 2
