-- Migración: agregar columna dimension a factor
ALTER TABLE factor
    ADD COLUMN dimension TINYINT NOT NULL DEFAULT 1 AFTER color,
    ADD CONSTRAINT chk_factor_dimension CHECK (dimension IN (1,2));

-- (Opcional) Actualizar dimensiones por lote si se desea separar las primeras 5 = 1 y las siguientes 5 = 2
-- UPDATE factor SET dimension = 1 WHERE id BETWEEN 1 AND 5;
-- UPDATE factor SET dimension = 2 WHERE id BETWEEN 6 AND 10;

-- Verificación rápida
-- SELECT id, nombre, dimension FROM factor ORDER BY id;