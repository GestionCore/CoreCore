"""
Rotación de TOKEN_ENCRYPTION_KEY: vuelve a cifrar todos los tokens guardados (meli_tokens) con la clave vigente.

Procedimiento (detalle en docs/RUNBOOK.md):
  1. Generar una clave nueva:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  2. Pasar la clave que estaba en uso a TOKEN_ENCRYPTION_KEY_ANTERIOR y poner la nueva en TOKEN_ENCRYPTION_KEY (fly secrets set ... -a corecore).
  3. python rotar_clave.py            -> vista previa: cuántos tokens están con una clave vieja (no modifica nada)
  4. python rotar_clave.py --aplicar  -> los vuelve a cifrar con la clave nueva
  5. Cuando no queden con clave vieja, borrar TOKEN_ENCRYPTION_KEY_ANTERIOR.

Usa conexion_admin porque meli_tokens no es accesible con el rol normal (una de las excepciones documentadas, junto con token_manager).
"""
import sys

import crypto_utils
import db


def main(aplicar=False):
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT cuenta_id, access_token_cifrado, refresh_token_cifrado FROM meli_tokens")
        filas = cursor.fetchall()
        pendientes, ya_al_dia, ilegibles = [], 0, []
        for cuenta_id, acceso, refresco in filas:
            try:
                if crypto_utils.usa_la_clave_vigente(acceso) and crypto_utils.usa_la_clave_vigente(refresco):
                    ya_al_dia += 1
                else:
                    pendientes.append((cuenta_id, crypto_utils.recifrar(acceso), crypto_utils.recifrar(refresco)))
            except RuntimeError:
                ilegibles.append(cuenta_id)
        print(f"Cuentas con tokens: {len(filas)} · ya con la clave vigente: {ya_al_dia} · con una clave anterior: {len(pendientes)} · ilegibles: {len(ilegibles)}")
        if ilegibles:
            print(f"⚠️ No se pudieron leer con ninguna clave configurada (hay que reconectarlas): {ilegibles}")
        if not pendientes:
            return
        if not aplicar:
            print("Vista previa: no se modificó nada. Para volver a cifrar, correr con --aplicar.")
            return
        for cuenta_id, acceso, refresco in pendientes:
            cursor.execute("UPDATE meli_tokens SET access_token_cifrado = %s, refresh_token_cifrado = %s WHERE cuenta_id = %s",
                           (acceso, refresco, cuenta_id))
        print(f"✅ {len(pendientes)} cuenta(s) vueltas a cifrar con la clave vigente.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(aplicar="--aplicar" in sys.argv)
