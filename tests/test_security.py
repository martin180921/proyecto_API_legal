"""`app/core/security.py`: hash y verificación de contraseña con `bcrypt`
directo (A5.2, R.7 — salida de `passlib`, abandonado desde 2020)."""
from app.core.security import hash_contrasena, verificar_contrasena

# Generado con el código de `passlib[bcrypt]` anterior a A5.2, contra la
# contraseña "clave-larga-1". Fijado como literal para probar que el cambio de
# librería no invalida los hashes que ya existen en la base — sin esto, el
# despliegue deja fuera al único usuario real del piloto.
_HASH_GENERADO_POR_PASSLIB = "$2b$12$hJnzytHatjbcx/HyB6VTeeEFzYoqz22TqIew4DWsUpaFyVyY5WJwi"


def test_hash_y_verificar_contrasena_correcta():
    contrasena_hash = hash_contrasena("una-contrasena-cualquiera")
    assert verificar_contrasena("una-contrasena-cualquiera", contrasena_hash) is True


def test_verificar_contrasena_incorrecta_devuelve_false():
    contrasena_hash = hash_contrasena("una-contrasena-cualquiera")
    assert verificar_contrasena("otra-distinta", contrasena_hash) is False


def test_hash_generado_por_passlib_sigue_verificando():
    assert verificar_contrasena("clave-larga-1", _HASH_GENERADO_POR_PASSLIB) is True
    assert verificar_contrasena("otra-cosa", _HASH_GENERADO_POR_PASSLIB) is False
