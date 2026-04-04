#!/usr/bin/env python3
"""
create_admin.py

Usa el módulo controller.py para crear (o promocionar) un usuario admin.

Ejemplos:
  python create_admin.py --email admin@example.com --name "Administrador"
  python create_admin.py --email admin@example.com --password Secret123
"""

import argparse
import getpass
import sqlite3
import sys
import os

# Ajusta la importación si tu módulo se llama distinto o está en otro paquete.
try:
    from controller import init_db, create_user
except Exception as e:
    print("No pude importar 'init_db' y 'create_user' desde controller.py:", e)
    sys.exit(1)


def promote_existing_user_to_admin(db_path: str, email: str) -> bool:
    """
    Si existe un usuario con este email, actualiza su role a 'admin'.
    Retorna True si actualizó (o ya era admin), False si no encontró el usuario.
    """
    if not os.path.exists(db_path):
        return False
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        # Intentamos actualizar el role
        cur.execute("UPDATE users SET role = ? WHERE email = ?", ("admin", email))
        conn.commit()
        updated = cur.rowcount
        return updated > 0
    except Exception as e:
        print("Error al promocionar usuario:", e)
        return False
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Crear o promocionar un usuario admin en la DB.")
    parser.add_argument("--email", "-e", required=True, help="Email del usuario admin")
    parser.add_argument("--name", "-n", default="Admin", help="Nombre del usuario")
    parser.add_argument("--password", "-p", help="Password (si no se entrega, se pedirá por stdin)")
    parser.add_argument("--db", default=os.environ.get("SHOP_DB", "data/shop.db"), help="Ruta a la base de datos (opcional)")
    args = parser.parse_args()

    email = args.email.strip()
    name = args.name.strip()
    password = args.password
    db_path = args.db

    if not password:
        # pedir password en forma segura
        password = getpass.getpass(f"Password para {email}: ")
        if not password:
            print("Password vacía. Abortando.")
            sys.exit(1)
        password_confirm = getpass.getpass("Confirmar password: ")
        if password != password_confirm:
            print("Las contraseñas no coinciden. Abortando.")
            sys.exit(1)

    # Asegurarnos que la DB y las tablas existen (aplica migraciones si hace falta)
    try:
        init_db(db_path)
    except Exception as e:
        print("Error ejecutando init_db():", e)
        # continuar; puede que la DB exista de todos modos

    # Intentar crear el usuario
    try:
        user = create_user(email=email, password=password, name=name, role="admin", db_path=db_path)
        print("Usuario admin creado correctamente:")
        print(user)
        sys.exit(0)
    except ValueError as ve:
        # Usuario ya existe. Intentamos promoverlo a admin.
        print(f"El usuario '{email}' ya existe. Intentando promocionarlo a admin...")
        promoted = promote_existing_user_to_admin(db_path, email)
        if promoted:
            print(f"Usuario '{email}' promovido a admin correctamente.")
            sys.exit(0)
        else:
            print(f"No fue posible promocionar al usuario '{email}'. Revisa la DB en {db_path}.")
            sys.exit(2)
    except Exception as exc:
        print("Error creando usuario:", exc)
        sys.exit(3)


if __name__ == "__main__":
    main()
