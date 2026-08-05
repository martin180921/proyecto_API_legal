-- Roles y bases de datos de desarrollo. Lo usan docker-compose.yml (al crear
-- el volumen) y el workflow de CI.
--
-- `api_legal_app` es NOSUPERUSER a propósito, y no es un detalle cosmético:
-- un superusuario de Postgres se salta todos los GRANT/REVOKE sin avisar, así
-- que con un superusuario el `REVOKE UPDATE, DELETE` que protege el audit log
-- no haría absolutamente nada — y la prueba que lo verifica pasaría en verde
-- sin comprobar nada. Verificado contra Postgres 16 el 2026-08-05.
--
-- OJO en producción: Railway entrega por defecto un `DATABASE_URL` con rol
-- superusuario. Mientras eso siga así, el REVOKE es inerte allí. Ver
-- «Multi-tenancy y audit log desde el día 1» en la bóveda: el arreglo (rol de
-- migración ≠ rol de aplicación, ninguno superusuario) está planificado para F3.

CREATE ROLE api_legal_app WITH LOGIN PASSWORD 'api_legal_app' NOSUPERUSER CREATEDB;

-- El rol es owner: necesita crear el esquema al correr las migraciones.
CREATE DATABASE api_legal OWNER api_legal_app;
CREATE DATABASE api_legal_test OWNER api_legal_app;
