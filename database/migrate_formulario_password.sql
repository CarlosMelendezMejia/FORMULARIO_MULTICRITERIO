-- Migration: add password columns to formulario
ALTER TABLE formulario
    ADD COLUMN requiere_password TINYINT(1) DEFAULT NULL AFTER nombre,
    ADD COLUMN password_env_key VARCHAR(50) DEFAULT NULL AFTER requiere_password;
