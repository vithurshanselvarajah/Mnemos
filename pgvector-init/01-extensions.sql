-- Enable pgvector and create the Mnemos embeddings table on first boot.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS face_embeddings (
    id           UUID PRIMARY KEY,
    crop_id      UUID NOT NULL,
    person_id    UUID NOT NULL,
    embedding    vector(512) NOT NULL,
    model_name   TEXT NOT NULL,
    is_averaged  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- HNSW index on cosine distance (the spec calls for vector_cosine_ops).
-- Lists/ef_construction chosen for a small-to-medium home deployment.
CREATE INDEX IF NOT EXISTS face_embeddings_embedding_hnsw
    ON face_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Person lookup index (for averaged-vector dedup per person/model).
CREATE INDEX IF NOT EXISTS face_embeddings_person_model_idx
    ON face_embeddings (person_id, model_name);

-- Crop lookup index.
CREATE INDEX IF NOT EXISTS face_embeddings_crop_idx
    ON face_embeddings (crop_id);
