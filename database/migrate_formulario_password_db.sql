-- Migration: replace password env key with password hash on formulario
ALTER TABLE formulario
    DROP COLUMN password_env_key,
    ADD COLUMN password_hash VARCHAR(255) DEFAULT NULL AFTER requiere_password;
