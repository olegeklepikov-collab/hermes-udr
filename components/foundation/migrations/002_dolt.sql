CREATE TABLE IF NOT EXISTS objects (
    project_id VARCHAR(128) NOT NULL,
    object_id VARCHAR(128) NOT NULL,
    revision BIGINT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    schema_id VARCHAR(128) NOT NULL,
    object_json JSON NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (project_id, object_id)
);
