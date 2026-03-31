-- Gateway database initialization
-- This script runs once on first container creation.

CREATE TABLE IF NOT EXISTS users (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(100)  UNIQUE NOT NULL,
    hashed_password VARCHAR(255)  NOT NULL,
    created_at      TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
);
