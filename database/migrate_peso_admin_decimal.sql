-- Migration to change peso_admin from FLOAT to DECIMAL(4,1)
ALTER TABLE ponderacion_admin
    ADD COLUMN peso_admin_tmp DECIMAL(4,1);

UPDATE ponderacion_admin
    SET peso_admin_tmp = peso_admin;

ALTER TABLE ponderacion_admin
    DROP COLUMN peso_admin;

ALTER TABLE ponderacion_admin
    CHANGE COLUMN peso_admin_tmp peso_admin DECIMAL(4,1) NOT NULL;
