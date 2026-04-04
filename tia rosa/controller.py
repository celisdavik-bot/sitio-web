<<<<<<< HEAD
import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash
import uuid as _uuid

DB_DEFAULT_PATH = os.environ.get("SHOP_DB", "data/shop.db")

def get_connection(db_path: str = DB_DEFAULT_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def _ensure_data_dir(db_path: str):
    folder = os.path.dirname(db_path) or "."
    if not os.path.exists(folder):
        os.makedirs(folder)

def _get_conn(db_path: str):
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return dict(row) if row is not None else None

def _ensure_users_role_column(db_path: str = DB_DEFAULT_PATH):
    conn = _get_conn(db_path)
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA table_info(users);")
        cols = [r["name"] for r in cur.fetchall()]
        if "role" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user';")
            conn.commit()
            print("Migración: columna 'role' añadida a users (default 'user').")
    except sqlite3.OperationalError:
        pass
    except Exception as e:
        print(f"[warning] No se pudo verificar/añadir la columna 'role' a users: {e}")
    finally:
        conn.close()

def init_db(db_path: str = DB_DEFAULT_PATH):
    _ensure_data_dir(db_path)
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS carts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            session_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cart_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cart_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            title TEXT,
            qty INTEGER NOT NULL DEFAULT 1,
            price REAL,
            FOREIGN KEY(cart_id) REFERENCES carts(id) ON DELETE CASCADE
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            total REAL,
            status TEXT DEFAULT 'pending',
            shipping_address TEXT,
            distributor_contact TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            title TEXT,
            qty INTEGER,
            price REAL,
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
        );
        """
    )
    conn.commit()
    conn.close()
    _ensure_users_role_column(db_path)
    _ensure_orders_webpay_column(db_path)
    print(f"Inicializada la DB en {db_path} (tablas users, carts, cart_items, orders, order_items).")

def _sanitize_col(name: str) -> str:
    n = name.strip().lower().replace(" ", "_")
    import re
    n = re.sub(r"[^\w_]", "", n)
    if n == "":
        n = "col"
    return n

def import_books_from_excel(
    excel_path: str,
    db_path: str = DB_DEFAULT_PATH,
    sheet_name=0,
    table_name: str = "books",
    replace: bool = True,
):
    import re
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"No existe el archivo {excel_path}")
    _ensure_data_dir(db_path)
    df = pd.read_excel(excel_path, sheet_name=sheet_name, engine="openpyxl")
    raw_cols = list(df.columns)
    normalized = [_sanitize_col(str(c)) for c in raw_cols]
    df.columns = normalized
    col_map = {}
    lower_map = {c: c for c in normalized}
    for c in normalized:
        if c in ("vendedor", "seller", "vendor"):
            col_map["seller"] = c
        elif "url" in c:
            col_map["url"] = c
        elif c in ("titulo", "title", "name"):
            col_map["title"] = c
        elif c in ("imagen", "image", "img"):
            col_map["image"] = c
        elif c in ("autor", "author"):
            col_map["author"] = c
        elif c in ("editorial", "publisher"):
            col_map["publisher"] = c
        elif c in ("año", "ano", "anio", "year"):
            col_map["year"] = c
        elif c in ("tapa", "cover"):
            col_map["cover"] = c
        elif c in ("idioma", "language", "lang"):
            col_map["language"] = c
        elif c in ("tipo", "type"):
            col_map["type"] = c
        elif c in ("genero", "género", "genero_1", "genre"):
            col_map["genre"] = c
        elif "isbn" in c:
            col_map["isbn"] = c
        elif re.search(r"ro|chile|us\$|\$|us|\bus\b", c):
            col_map["price"] = c
    possible_price_names = [
        _sanitize_col("Ro, CHILE U$$"),
        _sanitize_col("Ro CHILE U$$"),
        _sanitize_col("ro_chile_us"),
        "price",
        "precio",
    ]
    if "price" not in col_map:
        for cand in possible_price_names:
            if cand in normalized:
                col_map["price"] = cand
                break
    col_types = {}
    for col in df.columns:
        if col == col_map.get("price"):
            col_types[col] = "REAL"
        elif col == col_map.get("year"):
            if pd.api.types.is_integer_dtype(df[col]) or pd.api.types.is_numeric_dtype(df[col]):
                col_types[col] = "INTEGER"
            else:
                col_types[col] = "TEXT"
        elif pd.api.types.is_numeric_dtype(df[col]):
            col_types[col] = "REAL"
        else:
            col_types[col] = "TEXT"
    conn = _get_conn(db_path)
    cur = conn.cursor()
    if replace:
        cur.execute(f"DROP TABLE IF EXISTS {table_name};")
        conn.commit()
    cols_sql = ",\n".join([f"{col} {col_types[col]}" for col in df.columns])
    create_sql = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {cols_sql}
        );
    """
    cur.execute(create_sql)
    conn.commit()
    if "price" in col_map:
        price_col = col_map["price"]
        def clean_price(val):
            if pd.isna(val):
                return None
            s = str(val).strip()
            s = re.sub(r"[^\d\.,\-]", "", s)
            if s.count(",") > 0 and s.count(".") == 0:
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
            try:
                return float(s) if s not in ("", None) else None
            except Exception:
                return None
        df[price_col] = df[price_col].apply(clean_price)
    placeholders = ",".join(["?"] * len(df.columns))
    insert_sql = f"INSERT INTO {table_name} ({', '.join(df.columns)}) VALUES ({placeholders})"
    rows = []
    for _, r in df.iterrows():
        values = []
        for c in df.columns:
            v = r[c]
            if pd.isna(v):
                v = None
            values.append(v)
        rows.append(tuple(values))
    if rows:
        cur.executemany(insert_sql, rows)
        conn.commit()
    conn.close()
    print(f"Importación completada: {len(rows)} filas insertadas en '{table_name}' de {db_path}.")
    print("Columnas mapeadas:", col_map)

def get_book(book_id: int, db_path: str = DB_DEFAULT_PATH) -> Optional[Dict[str, Any]]:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM books WHERE id = ? LIMIT 1", (book_id,))
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row)

def search_books(q: Optional[str] = None, limit: int = 50, db_path: str = DB_DEFAULT_PATH) -> List[Dict[str, Any]]:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(books);")
    cols = [r["name"] for r in cur.fetchall()]
    possible_fields = [c for c in ["title", "author", "name"] if c in cols]
    if q and possible_fields:
        like_clauses = " OR ".join([f"{f} LIKE ?" for f in possible_fields])
        params = [f"%{q}%"] * len(possible_fields) + [limit]
        sql = f"SELECT * FROM books WHERE ({like_clauses}) LIMIT ?"
        cur.execute(sql, params)
    elif q:
        text_cols = []
        for c in cols:
            text_cols.append(f"{c} LIKE ?")
        if text_cols:
            sql = f"SELECT * FROM books WHERE ({' OR '.join(text_cols)}) LIMIT ?"
            params = [f"%{q}%"] * len(text_cols) + [limit]
            cur.execute(sql, params)
        else:
            cur.execute("SELECT * FROM books LIMIT ?", (limit,))
    else:
        cur.execute("SELECT * FROM books LIMIT ?", (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def create_user(email: str, password: str, name: Optional[str] = None, role: str = "user", db_path: str = DB_DEFAULT_PATH) -> Dict[str, Any]:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    password_hash = generate_password_hash(password)
    try:
        cur.execute(
            "INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, ?)",
            (email, password_hash, name, role),
        )
        conn.commit()
        user_id = cur.lastrowid
    except sqlite3.IntegrityError as e:
        conn.close()
        raise ValueError("Usuario ya existe") from e
    conn.close()
    return {"id": user_id, "email": email, "name": name, "role": role}

def authenticate_user(email: str, password: str, db_path: str = DB_DEFAULT_PATH) -> Optional[Dict[str, Any]]:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ? LIMIT 1", (email,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    rowd = dict(row)
    if check_password_hash(rowd["password_hash"], password):
        rowd.pop("password_hash", None)
        rowd.setdefault("role", "user")
        return rowd
    return None

def _get_cart_by_user_or_session(user_id: Optional[int], session_id: Optional[str], db_path: str = DB_DEFAULT_PATH) -> Optional[Dict[str, Any]]:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    if user_id:
        cur.execute("SELECT * FROM carts WHERE user_id = ? LIMIT 1", (user_id,))
    elif session_id:
        cur.execute("SELECT * FROM carts WHERE session_id = ? LIMIT 1", (session_id,))
    else:
        conn.close()
        return None
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row)

def create_cart(user_id: Optional[int] = None, session_id: Optional[str] = None, db_path: str = DB_DEFAULT_PATH) -> Dict[str, Any]:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("INSERT INTO carts (user_id, session_id) VALUES (?, ?)", (user_id, session_id))
    conn.commit()
    cart_id = cur.lastrowid
    conn.close()
    return {"id": cart_id, "user_id": user_id, "session_id": session_id}

def get_or_create_cart(user_id: Optional[int] = None, session_id: Optional[str] = None, db_path: str = DB_DEFAULT_PATH) -> Dict[str, Any]:
    existing = _get_cart_by_user_or_session(user_id, session_id, db_path)
    if existing:
        return existing
    return create_cart(user_id=user_id, session_id=session_id, db_path=db_path)

def add_to_cart(user_id: Optional[int], session_id: Optional[str], book_id: int, qty: int = 1, db_path: str = DB_DEFAULT_PATH) -> Dict[str, Any]:
    cart = get_or_create_cart(user_id=user_id, session_id=session_id, db_path=db_path)
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM books WHERE id = ? LIMIT 1", (book_id,))
    book = cur.fetchone()
    if not book:
        conn.close()
        raise ValueError("Libro no encontrado")
    book = dict(book)
    title = book.get("title") or book.get("name") or ""
    price = None
    if "price" in book and book["price"] is not None:
        try:
            price = float(book["price"])
        except Exception:
            price = None
    cur.execute("SELECT * FROM cart_items WHERE cart_id = ? AND book_id = ? LIMIT 1", (cart["id"], book_id))
    existing = cur.fetchone()
    if existing:
        new_qty = existing["qty"] + qty
        cur.execute("UPDATE cart_items SET qty = ? WHERE id = ?", (new_qty, existing["id"]))
        conn.commit()
        item_id = existing["id"]
    else:
        cur.execute(
            "INSERT INTO cart_items (cart_id, book_id, title, qty, price) VALUES (?, ?, ?, ?, ?)",
            (cart["id"], book_id, title, qty, price),
        )
        conn.commit()
        item_id = cur.lastrowid
    cur.execute("SELECT * FROM cart_items WHERE id = ?", (item_id,))
    item = cur.fetchone()
    conn.close()
    return dict(item)

def get_cart(user_id: Optional[int] = None, session_id: Optional[str] = None, db_path: str = DB_DEFAULT_PATH) -> Dict[str, Any]:
    cart = get_or_create_cart(user_id=user_id, session_id=session_id, db_path=db_path)
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM cart_items WHERE cart_id = ?", (cart["id"],))
    raw_items = [dict(r) for r in cur.fetchall()]
    enriched = []
    for it in raw_items:
        item = dict(it)
        book_id = it.get("book_id")
        if book_id:
            try:
                cur.execute("SELECT * FROM books WHERE id = ? LIMIT 1", (book_id,))
                b = cur.fetchone()
                if b:
                    b = dict(b)
                    if not item.get("title"):
                        item["title"] = b.get("title") or b.get("titulo") or b.get("name") or b.get("nombre")
                    item["image"] = item.get("image") or b.get("image") or b.get("imagen") or b.get("url")
                    if item.get("price") in (None, "", 0):
                        possible_price = None
                        for k in ("price", "precio", "ro_chile_us", "ro_chile_usd", "valor", "ro_chile_u"):
                            if k in b and b.get(k) not in (None, ""):
                                possible_price = b.get(k)
                                break
                        if possible_price is not None:
                            try:
                                item["price"] = float(str(possible_price).replace(",", "."))
                            except Exception:
                                item["price"] = possible_price
                    item.setdefault("book_title_from_books_table", b.get("title") or b.get("titulo"))
                    item.setdefault("book_raw", b)
            except Exception:
                pass
        enriched.append(item)
    conn.close()
    return {"cart": cart, "items": enriched}

def remove_cart_item(item_id: int, db_path: str = DB_DEFAULT_PATH) -> bool:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM cart_items WHERE id = ?", (item_id,))
    changed = cur.rowcount
    conn.commit()
    conn.close()
    return changed > 0

def _send_order_to_distributor_stub(order_payload: Dict[str, Any]) -> bool:
    print("=== Enviando pedido al distribuidor (STUB) ===")
    print(order_payload)
    return True

def checkout(user_id: int, shipping_address: str, distributor_contact: Optional[str] = None, db_path: str = DB_DEFAULT_PATH) -> Dict[str, Any]:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM carts WHERE user_id = ? LIMIT 1", (user_id,))
    cart = cur.fetchone()
    if not cart:
        conn.close()
        raise ValueError("Carrito no encontrado para el usuario")
    cart_id = cart["id"]
    cur.execute("SELECT * FROM cart_items WHERE cart_id = ?", (cart_id,))
    items = [dict(r) for r in cur.fetchall()]
    if not items:
        conn.close()
        raise ValueError("Carrito vacío")
    total = 0.0
    for it in items:
        price = it.get("price") or 0.0
        try:
            total += float(price) * int(it.get("qty", 1))
        except Exception:
            total += 0.0
    cur.execute(
        "INSERT INTO orders (user_id, total, status, shipping_address, distributor_contact, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, total, "pending", shipping_address, distributor_contact, datetime.utcnow()),
    )
    conn.commit()
    order_id = cur.lastrowid
    for it in items:
        cur.execute(
            "INSERT INTO order_items (order_id, book_id, title, qty, price) VALUES (?, ?, ?, ?, ?)",
            (order_id, it["book_id"], it.get("title"), it.get("qty"), it.get("price")),
        )
    conn.commit()
    order_payload = {
        "order_id": order_id,
        "user_id": user_id,
        "shipping_address": shipping_address,
        "distributor_contact": distributor_contact,
        "items": [{"book_id": it["book_id"], "title": it.get("title"), "qty": it.get("qty")} for it in items],
        "total": total,
    }
    ok = _send_order_to_distributor_stub(order_payload)
    if ok:
        cur.execute("UPDATE orders SET status = ? WHERE id = ?", ("sent_to_supplier", order_id))
        cur.execute("DELETE FROM cart_items WHERE cart_id = ?", (cart_id,))
        conn.commit()
        conn.close()
        return {"order_id": order_id, "status": "sent_to_supplier"}
    else:
        cur.execute("UPDATE orders SET status = ? WHERE id = ?", ("error_sending", order_id))
        conn.commit()
        conn.close()
        return {"order_id": order_id, "status": "error_sending"}

def list_orders_for_user(user_id: int, db_path: str = DB_DEFAULT_PATH) -> List[Dict[str, Any]]:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def get_order(order_id: int, db_path: str = DB_DEFAULT_PATH) -> Optional[Dict[str, Any]]:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM orders WHERE id = ? LIMIT 1", (order_id,))
        order_row = cur.fetchone()
        if not order_row:
            return None
        order = dict(order_row)
        cur.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,))
        items = [dict(r) for r in cur.fetchall()]
        enriched_items = []
        for it in items:
            item = dict(it)
            img_val = item.get("imagen") or item.get("image") or item.get("url")
            book_id = item.get("book_id")
            if not img_val and book_id:
                try:
                    cur.execute("SELECT  imagen, url, titulo, ro_chile_u FROM books WHERE id = ? LIMIT 1", (book_id,))
                    b = cur.fetchone()
                    if b:
                        b = dict(b)
                        img_val = b.get("image") or b.get("imagen") or b.get("url")
                        if not item.get("titulo"):
                            item["title"] = b.get("title") or b.get("titulo")
                        if item.get("ro_chile_u") in (None, "") and b.get("ro_chile_u") not in (None, ""):
                            try:
                                item["ro_chile_u"] = float(b.get("ro_chile_u"))
                            except Exception:
                                item["ro_chile_u"] = b.get("ro_chile_u")
                except Exception as e:
                    print("Warning get_order -> error consultando books:", e)
            resolved_img = None
            if img_val:
                img_val = str(img_val).strip()
                if img_val.lower().startswith("http://") or img_val.lower().startswith("https://"):
                    resolved_img = img_val
                elif img_val.startswith("/"):
                    resolved_img = img_val
                else:
                    resolved_img = "/static/img/" + img_val.lstrip("/")
            item["imagen"] = resolved_img or "/static/img/placeholder.png"
            enriched_items.append(item)
        order["items"] = enriched_items
        try:
            print(f"DEBUG get_order {order_id} -> images:", [it.get("imagen") for it in enriched_items])
        except Exception:
            pass
        return order
    finally:
        conn.close()

def create_tables(db_path: str = DB_DEFAULT_PATH):
    return init_db(db_path)

def initialize_database(db_path: str = DB_DEFAULT_PATH, excel_path: str = None):
    init_db(db_path)
    excel_candidate = excel_path or "data/Rosana_Chile_BASe_092025.xlsx"
    if os.path.exists(excel_candidate):
        try:
            import_books_from_excel(excel_candidate, db_path=db_path)
            print(f"Libros importados desde {excel_candidate}")
        except Exception as e:
            print(f"[warning] import_books_from_excel falló: {e}")
    else:
        print(f"[info] No se encontró {excel_candidate}; omitiendo importación de libros.")

def get_all_books(db_path: str = DB_DEFAULT_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, vendedor, url, titulo, imagen, autor, editorial, 
                   año, tapa, idioma, tipo, genero, isbn, ro_chile_u
            FROM books
            ORDER BY titulo ASC
        """)
        rows = cursor.fetchall()
    except Exception:
        cursor.execute("SELECT * FROM books")
        rows = cursor.fetchall()
    conn.close()
    books = []
    for r in rows:
        if isinstance(r, sqlite3.Row):
            books.append({k: r[k] if k in r.keys() else None for k in r.keys()})
        else:
            try:
                books.append({
                    "id": r[0],
                    "vendedor": r[1],
                    "url": r[2],
                    "titulo": r[3],
                    "imagen": r[4],
                    "autor": r[5],
                    "editorial": r[6],
                    "anio": r[7],
                    "tapa": r[8],
                    "idioma": r[9],
                    "tipo": r[10],
                    "genero": r[11],
                    "isbn": r[12],
                    "precio": r[13],
                })
            except Exception:
                books.append({"row": r})
    return books

def initialize(db_path: str = DB_DEFAULT_PATH):
    return init_db(db_path)

def _ensure_orders_webpay_column(db_path: str = DB_DEFAULT_PATH):
    conn = _get_conn(db_path)
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA table_info(orders);")
        cols = [r["name"] for r in cur.fetchall()]
        if "webpay_buy_order" not in cols:
            cur.execute("ALTER TABLE orders ADD COLUMN webpay_buy_order TEXT;")
            conn.commit()
            print("Migración: columna 'webpay_buy_order' añadida a orders.")
    except Exception as e:
        print("Migración webpay column falló:", e)
    finally:
        conn.close()

def create_order_for_payment(
    user_id: int, 
    shipping_address: str = "", 
    distributor_contact: Optional[str] = None, 
    db_path: str = DB_DEFAULT_PATH
) -> Dict[str, Any]:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM carts WHERE user_id = ? LIMIT 1", (user_id,))
    cart = cur.fetchone()
    if not cart:
        conn.close()
        raise ValueError("Carrito no encontrado para el usuario")
    cart_id = cart["id"]
    cur.execute("SELECT * FROM cart_items WHERE cart_id = ?", (cart_id,))
    items = [dict(r) for r in cur.fetchall()]
    if not items:
        conn.close()
        raise ValueError("Carrito vacío")
    total = 0.0
    for it in items:
        book_id = it["book_id"]
        cur.execute("SELECT ro_chile_u, titulo FROM books WHERE id = ?", (book_id,))
        book = cur.fetchone()
        if not book:
            raise ValueError(f"Libro {book_id} no encontrado")
        usd_price = float(book["ro_chile_u"])
        clp_price = usd_price * 1000
        qty = int(it.get("qty", 1))
        total += clp_price * qty
        it["resolved_price"] = clp_price
        it["title"] = book["titulo"]
    buy_order = str(_uuid.uuid4())[:26]
    now = datetime.utcnow()
    cur.execute("PRAGMA table_info(orders);")
    cols = [r["name"] for r in cur.fetchall()]
    if "webpay_buy_order" not in cols:
        try:
            cur.execute("ALTER TABLE orders ADD COLUMN webpay_buy_order TEXT;")
            conn.commit()
            print("Añadida columna webpay_buy_order a orders.")
        except:
            pass
    cur.execute(
        "INSERT INTO orders (user_id, total, status, shipping_address, distributor_contact, created_at, webpay_buy_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, total, "pending_payment", shipping_address, distributor_contact, now, buy_order)
    )
    conn.commit()
    order_id = cur.lastrowid
    for it in items:
        cur.execute(
            "INSERT INTO order_items (order_id, book_id, title, qty, price) VALUES (?, ?, ?, ?, ?)",
            (order_id, it["book_id"], it["title"], it.get("qty"), it["resolved_price"]),
        )
    conn.commit()
    print("DEBUG create_order_for_payment:",
          "user_id=", user_id,
          "order_id=", order_id,
          "buy_order=", buy_order,
          "total=", total)
    conn.close()
    return {
        "order_id": order_id,
        "buy_order": buy_order,
        "total": total,
        "items": items
    }

def create_order_for_payment(user_id: int, shipping_address: str = "", distributor_contact: Optional[str] = None, db_path: str = DB_DEFAULT_PATH) -> Dict[str, Any]:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM carts WHERE user_id = ? LIMIT 1", (user_id,))
    cart = cur.fetchone()
    if not cart:
        conn.close()
        raise ValueError("Carrito no encontrado para el usuario")
    cart_id = cart["id"]
    cur.execute("PRAGMA table_info(books);")
    book_cols = [r["name"] for r in cur.fetchall()]
    title_candidates = ["title", "titulo", "name", "nombre"]
    price_candidates = ["price", "precio", "ro_chile_u", "ro_chile_us", "valor", "ro_chile_usd"]
    image_candidates = ["imagen", "image", "url", "img", "imagen_url"]
    def choose(col_list):
        for c in col_list:
            if c in book_cols:
                return c
        return None
    book_title_col = choose(title_candidates)
    book_price_col = choose(price_candidates)
    book_image_col = choose(image_candidates)
    select_extra = []
    if book_title_col:
        select_extra.append(f"b.\"{book_title_col}\" AS book_title")
    else:
        select_extra.append("NULL AS book_title")
    if book_price_col:
        select_extra.append(f"b.\"{book_price_col}\" AS book_price_raw")
    else:
        select_extra.append("NULL AS book_price_raw")
    if book_image_col:
        select_extra.append(f"b.\"{book_image_col}\" AS book_image")
    else:
        select_extra.append("NULL AS book_image")
    select_extra_sql = ", " + ", ".join(select_extra)
    sql = f"""
        SELECT ci.id AS cart_item_id, ci.book_id, ci.title AS cart_title, ci.qty, ci.price AS cart_price
        {select_extra_sql}
        FROM cart_items ci
        LEFT JOIN books b ON b.id = ci.book_id
        WHERE ci.cart_id = ?
    """
    cur.execute(sql, (cart_id,))
    raw_items = [dict(r) for r in cur.fetchall()]
    if not raw_items:
        conn.close()
        raise ValueError("Carrito vacío")
    items_for_order = []
    total = 0.0
    for it in raw_items:
        qty = int(it.get("qty") or 1)
        resolved = None
        try:
            if it.get("cart_price") not in (None, ""):
                resolved = float(it.get("cart_price"))
        except Exception:
            resolved = None
        if resolved is None:
            bp = it.get("book_price_raw")
            try:
                if bp is not None:
                    resolved = float(bp) * 1000.0
            except Exception:
                resolved = 0.0
        if resolved is None:
            resolved = 0.0
        subtotal = resolved * qty
        total += subtotal
        items_for_order.append({
            "cart_item_id": it.get("cart_item_id"),
            "book_id": it.get("book_id"),
            "title": (it.get("cart_title") or it.get("book_title") or ""),
            "qty": qty,
            "price": resolved,
            "image": it.get("book_image") or None
        })
    buy_order = str(_uuid.uuid4())[:26]
    now = datetime.utcnow()
    try:
        cur.execute("PRAGMA table_info(orders);")
        existing_cols = [r["name"] for r in cur.fetchall()]
        if "webpay_buy_order" not in existing_cols:
            try:
                cur.execute("ALTER TABLE orders ADD COLUMN webpay_buy_order TEXT;")
                conn.commit()
                print("Migración: columna 'webpay_buy_order' añadida a orders.")
            except Exception as e:
                print("Warning: no pude crear columna webpay_buy_order automáticamente:", e)
    except Exception:
        pass
    cur.execute(
        "INSERT INTO orders (user_id, total, status, shipping_address, distributor_contact, created_at, webpay_buy_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, total, "pending_payment", shipping_address, distributor_contact, now, buy_order)
    )
    conn.commit()
    order_id = cur.lastrowid
    for it in items_for_order:
        cur.execute(
            "INSERT INTO order_items (order_id, book_id, title, qty, price) VALUES (?, ?, ?, ?, ?)",
            (order_id, it["book_id"], it.get("title"), it.get("qty"), it.get("price"))
        )
    conn.commit()
    conn.close()
    return {"order_id": order_id, "buy_order": buy_order, "total": total, "items": items_for_order}

if __name__ == "__main__":
    print("Inicializando DB...")
    init_db()
    sample_excel = "data/Rosana_Chile_BASe_092025.xlsx"
    if os.path.exists(sample_excel):
        print("Importando books desde", sample_excel)
        import_books_from_excel(sample_excel)
    else:
        print(f"No encontré {sample_excel}; si quieres importar tu Excel colócalo en esa ruta y vuelve a ejecutar.")
=======
import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash

DB_DEFAULT_PATH = os.environ.get("SHOP_DB", "data/shop.db")

def get_connection(db_path: str = DB_DEFAULT_PATH):
    """
    Abre una conexión SQLite y activa row_factory para obtener diccionarios.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # permite acceder por nombre de columna
    return conn
# ----------------------
# Utilidades
# ----------------------
def _ensure_data_dir(db_path: str):
    folder = os.path.dirname(db_path) or "."
    if not os.path.exists(folder):
        os.makedirs(folder)


def _get_conn(db_path: str):
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    # Habilitar foreign keys
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return dict(row) if row is not None else None


# ----------------------
# Inicialización de DB y esquema
# ----------------------
def init_db(db_path: str = DB_DEFAULT_PATH):
    """
    Crea las tablas necesarias si no existen (excepto books, que puede ser reemplazada por import).
    """
    _ensure_data_dir(db_path)
    conn = _get_conn(db_path)
    cur = conn.cursor()

    # users
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    # carts
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS carts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            session_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
        );
        """
    )

    # cart_items
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cart_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cart_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            title TEXT,
            qty INTEGER NOT NULL DEFAULT 1,
            price REAL,
            FOREIGN KEY(cart_id) REFERENCES carts(id) ON DELETE CASCADE
        );
        """
    )

    # orders
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            total REAL,
            status TEXT DEFAULT 'pending',
            shipping_address TEXT,
            distributor_contact TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )

    # order_items
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            title TEXT,
            qty INTEGER,
            price REAL,
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
        );
        """
    )

    conn.commit()
    conn.close()
    print(f"Inicializada la DB en {db_path} (tablas users, carts, cart_items, orders, order_items).")


# ----------------------
# Importación de Excel -> books (dynamic schema)
# ----------------------
def _sanitize_col(name: str) -> str:
    # Normaliza nombres de columnas para SQL
    n = name.strip().lower().replace(" ", "_")
    # remover caracteres no alfanuméricos excepto _
    import re

    n = re.sub(r"[^\w_]", "", n)
    if n == "":
        n = "col"
    return n

def import_books_from_excel(
    excel_path: str,
    db_path: str = DB_DEFAULT_PATH,
    sheet_name=0,
    table_name: str = "books",
    replace: bool = True,
):
    """
    Versión adaptada al Excel con columnas:
    Vendedor\tURL\tTitulo\tImagen\tAutor\tEditorial\tAño\tTapa\tIdioma\tTipo\tGenero\tISBN\tRo, CHILE U$$
    - Normaliza nombres de columnas.
    - Mapea columnas a un esquema estándar.
    - Limpia y convierte la columna de precio a REAL.
    """
    import re

    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"No existe el archivo {excel_path}")

    _ensure_data_dir(db_path)
    df = pd.read_excel(excel_path, sheet_name=sheet_name, engine="openpyxl")

    # Normalizar columnas crudas
    raw_cols = list(df.columns)
    normalized = [_sanitize_col(str(c)) for c in raw_cols]
    df.columns = normalized

    # Mapeo probable desde tus nombres a nombres estándar
    # generar diccionario de heurística entre columnas presentes y nombres esperados
    col_map = {}
    lower_map = {c: c for c in normalized}

    # Heurística para identificar columnas clave (pueden variar ligeramente)
    for c in normalized:
        if c in ("vendedor", "seller", "vendor"):
            col_map["seller"] = c
        elif "url" in c:
            col_map["url"] = c
        elif c in ("titulo", "title", "name"):
            col_map["title"] = c
        elif c in ("imagen", "image", "img"):
            col_map["image"] = c
        elif c in ("autor", "author"):
            col_map["author"] = c
        elif c in ("editorial", "publisher"):
            col_map["publisher"] = c
        elif c in ("año", "ano", "anio", "year"):
            col_map["year"] = c
        elif c in ("tapa", "cover"):
            col_map["cover"] = c
        elif c in ("idioma", "language", "lang"):
            col_map["language"] = c
        elif c in ("tipo", "type"):
            col_map["type"] = c
        elif c in ("genero", "género", "genero_1", "genre"):
            col_map["genre"] = c
        elif "isbn" in c:
            col_map["isbn"] = c
        # detectar columna precio (ejemplo: "ro_chile_us" o similar)
        elif re.search(r"ro|chile|us\$|\$|us|\bus\b", c):
            # si el nombre contiene ro, chile, us, $ asumimos es precio
            col_map["price"] = c

    # Si no encontramos price por heurística, intentar buscar la columna exacta derivada de tu header:
    possible_price_names = [
        _sanitize_col("Ro, CHILE U$$"),
        _sanitize_col("Ro CHILE U$$"),
        _sanitize_col("ro_chile_us"),
        "price",
        "precio",
    ]
    if "price" not in col_map:
        for cand in possible_price_names:
            if cand in normalized:
                col_map["price"] = cand
                break

    # Si faltan campos importantes, dejamos que la tabla incluya las columnas tal cual están
    # pero aseguramos que exista una columna 'price' (puede ser None)
    # Determinar tipos: preferimos REAL para price y year; TEXT para resto
    col_types = {}
    for col in df.columns:
        if col == col_map.get("price"):
            col_types[col] = "REAL"
        elif col == col_map.get("year"):
            # año como INTEGER si posible, sino TEXT
            if pd.api.types.is_integer_dtype(df[col]) or pd.api.types.is_numeric_dtype(df[col]):
                col_types[col] = "INTEGER"
            else:
                col_types[col] = "TEXT"
        elif pd.api.types.is_numeric_dtype(df[col]):
            col_types[col] = "REAL"
        else:
            col_types[col] = "TEXT"

    conn = _get_conn(db_path)
    cur = conn.cursor()

    if replace:
        cur.execute(f"DROP TABLE IF EXISTS {table_name};")
        conn.commit()

    # Crear tabla books con id autoincrement y columnas detectadas (con los tipos elegidos)
    cols_sql = ",\n".join([f"{col} {col_types[col]}" for col in df.columns])
    create_sql = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {cols_sql}
        );
    """
    cur.execute(create_sql)
    conn.commit()

    # Antes de insertar, procesar/limpiar la columna de precio si existe
    if "price" in col_map:
        price_col = col_map["price"]
        def clean_price(val):
            if pd.isna(val):
                return None
            s = str(val).strip()
            # eliminar símbolos como U$$, US$, $, U$, etc y texto 'Ro' o 'CHILE'
            s = re.sub(r"[^\d\.,\-]", "", s)  # dejar dígitos, comas, puntos y guiones
            # si contiene coma y punto, decidir separador decimal: asumimos que coma es decimal si no hay punto
            if s.count(",") > 0 and s.count(".") == 0:
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
            try:
                return float(s) if s not in ("", None) else None
            except Exception:
                return None
        df[price_col] = df[price_col].apply(clean_price)

    # Insertar filas
    placeholders = ",".join(["?"] * len(df.columns))
    insert_sql = f"INSERT INTO {table_name} ({', '.join(df.columns)}) VALUES ({placeholders})"

    rows = []
    for _, r in df.iterrows():
        values = []
        for c in df.columns:
            v = r[c]
            if pd.isna(v):
                v = None
            values.append(v)
        rows.append(tuple(values))

    if rows:
        cur.executemany(insert_sql, rows)
        conn.commit()

    conn.close()
    print(f"Importación completada: {len(rows)} filas insertadas en '{table_name}' de {db_path}.")
    print("Columnas mapeadas:", col_map)


# ----------------------
# Consultas de libros
# ----------------------
def get_book(book_id: int, db_path: str = DB_DEFAULT_PATH) -> Optional[Dict[str, Any]]:
    """
    Obtiene libro por id (columna id en tabla books).
    """
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM books WHERE id = ? LIMIT 1", (book_id,))
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row)


def search_books(q: Optional[str] = None, limit: int = 50, db_path: str = DB_DEFAULT_PATH) -> List[Dict[str, Any]]:
    """
    Busca por title o author (si existen esas columnas) o devuelve primeras filas.
    """
    conn = _get_conn(db_path)
    cur = conn.cursor()

    # Determinar columnas existentes para consulta flexible
    cur.execute("PRAGMA table_info(books);")
    cols = [r["name"] for r in cur.fetchall()]
    # campos para búsqueda
    possible_fields = [c for c in ["title", "author", "name"] if c in cols]
    if q and possible_fields:
        # construir cláusula LIKE sobre campos disponibles
        like_clauses = " OR ".join([f"{f} LIKE ?" for f in possible_fields])
        params = [f"%{q}%"] * len(possible_fields) + [limit]
        sql = f"SELECT * FROM books WHERE ({like_clauses}) LIMIT ?"
        cur.execute(sql, params)
    elif q:
        # si no hay campos esperados busca en todas columnas TEXT
        text_cols = []
        for c in cols:
            # intentar tipo: pero PRAGMA no da tipo exacto siempre; igual probamos
            text_cols.append(f"{c} LIKE ?")
        if text_cols:
            sql = f"SELECT * FROM books WHERE ({' OR '.join(text_cols)}) LIMIT ?"
            params = [f"%{q}%"] * len(text_cols) + [limit]
            cur.execute(sql, params)
        else:
            cur.execute("SELECT * FROM books LIMIT ?", (limit,))
    else:
        cur.execute("SELECT * FROM books LIMIT ?", (limit,))

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ----------------------
# Usuarios
# ----------------------
def create_user(email: str, password: str, name: Optional[str] = None, db_path: str = DB_DEFAULT_PATH) -> Dict[str, Any]:
    """
    Crea un usuario; devuelve dict con datos básicos.
    """
    conn = _get_conn(db_path)
    cur = conn.cursor()
    password_hash = generate_password_hash(password)
    try:
        cur.execute("INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)", (email, password_hash, name))
        conn.commit()
        user_id = cur.lastrowid
    except sqlite3.IntegrityError as e:
        conn.close()
        raise ValueError("Usuario ya existe") from e
    conn.close()
    return {"id": user_id, "email": email, "name": name}


def authenticate_user(email: str, password: str, db_path: str = DB_DEFAULT_PATH) -> Optional[Dict[str, Any]]:
    """
    Verifica credenciales; devuelve usuario si ok, None si fallan.
    """
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ? LIMIT 1", (email,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    rowd = dict(row)
    if check_password_hash(rowd["password_hash"], password):
        # no devolver password_hash
        rowd.pop("password_hash", None)
        return rowd
    return None


# ----------------------
# Carrito
# ----------------------
def _get_cart_by_user_or_session(user_id: Optional[int], session_id: Optional[str], db_path: str = DB_DEFAULT_PATH) -> Optional[Dict[str, Any]]:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    if user_id:
        cur.execute("SELECT * FROM carts WHERE user_id = ? LIMIT 1", (user_id,))
    elif session_id:
        cur.execute("SELECT * FROM carts WHERE session_id = ? LIMIT 1", (session_id,))
    else:
        conn.close()
        return None
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row)


def create_cart(user_id: Optional[int] = None, session_id: Optional[str] = None, db_path: str = DB_DEFAULT_PATH) -> Dict[str, Any]:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("INSERT INTO carts (user_id, session_id) VALUES (?, ?)", (user_id, session_id))
    conn.commit()
    cart_id = cur.lastrowid
    conn.close()
    return {"id": cart_id, "user_id": user_id, "session_id": session_id}


def get_or_create_cart(user_id: Optional[int] = None, session_id: Optional[str] = None, db_path: str = DB_DEFAULT_PATH) -> Dict[str, Any]:
    existing = _get_cart_by_user_or_session(user_id, session_id, db_path)
    if existing:
        return existing
    return create_cart(user_id=user_id, session_id=session_id, db_path=db_path)


def add_to_cart(user_id: Optional[int], session_id: Optional[str], book_id: int, qty: int = 1, db_path: str = DB_DEFAULT_PATH) -> Dict[str, Any]:
    """
    Añade un item al carrito (si existe suma qty). book_id debe corresponder a books.id
    """
    cart = get_or_create_cart(user_id=user_id, session_id=session_id, db_path=db_path)
    conn = _get_conn(db_path)
    cur = conn.cursor()

    # obtener info libro
    cur.execute("SELECT * FROM books WHERE id = ? LIMIT 1", (book_id,))
    book = cur.fetchone()
    if not book:
        conn.close()
        raise ValueError("Libro no encontrado")

    book = dict(book)
    title = book.get("title") or book.get("name") or ""
    # intentar obtener price, si no existe usar 0
    price = None
    if "price" in book and book["price"] is not None:
        try:
            price = float(book["price"])
        except Exception:
            price = None

    # Ver si ya existe item en este carrito
    cur.execute("SELECT * FROM cart_items WHERE cart_id = ? AND book_id = ? LIMIT 1", (cart["id"], book_id))
    existing = cur.fetchone()
    if existing:
        new_qty = existing["qty"] + qty
        cur.execute("UPDATE cart_items SET qty = ? WHERE id = ?", (new_qty, existing["id"]))
        conn.commit()
        item_id = existing["id"]
    else:
        cur.execute(
            "INSERT INTO cart_items (cart_id, book_id, title, qty, price) VALUES (?, ?, ?, ?, ?)",
            (cart["id"], book_id, title, qty, price),
        )
        conn.commit()
        item_id = cur.lastrowid

    cur.execute("SELECT * FROM cart_items WHERE id = ?", (item_id,))
    item = cur.fetchone()
    conn.close()
    return dict(item)


# controller.py
def get_cart(user_id: Optional[int] = None, session_id: Optional[str] = None, db_path: str = DB_DEFAULT_PATH) -> Dict[str, Any]:
    """
    Recupera el carrito y enriquece cada item con datos actuales de la tabla books
    (title, image, price) si faltan en cart_items.
    Devuelve {"cart": {...}, "items": [ {...}, ... ]}.
    """
    cart = get_or_create_cart(user_id=user_id, session_id=session_id, db_path=db_path)
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM cart_items WHERE cart_id = ?", (cart["id"],))
    raw_items = [dict(r) for r in cur.fetchall()]

    enriched = []
    for it in raw_items:
        item = dict(it)  # copia para no mutar la fila original
        book_id = it.get("book_id")
        if book_id:
            try:
                cur.execute("SELECT * FROM books WHERE id = ? LIMIT 1", (book_id,))
                b = cur.fetchone()
                if b:
                    b = dict(b)
                    # Título: priorizar título en cart_items, sino buscar en books (varios nombres)
                    if not item.get("title"):
                        item["title"] = b.get("title") or b.get("titulo") or b.get("name") or b.get("nombre")
                    # Imagen
                    item["image"] = item.get("image") or b.get("image") or b.get("imagen") or b.get("url")
                    # Precio: priorizar price en cart_items (precio al añadir), si no tomar posible precio en books
                    if item.get("price") in (None, "", 0):
                        possible_price = None
                        for k in ("price", "precio", "ro_chile_us", "ro_chile_usd", "valor", "ro_chile_u"):
                            if k in b and b.get(k) not in (None, ""):
                                possible_price = b.get(k)
                                break
                        # intentar convertir a float si viene como string
                        if possible_price is not None:
                            try:
                                item["price"] = float(str(possible_price).replace(",", "."))
                            except Exception:
                                item["price"] = possible_price
                    # guardar algunos campos extra por si los quieres mostrar
                    item.setdefault("book_title_from_books_table", b.get("title") or b.get("titulo"))
                    item.setdefault("book_raw", b)
            except Exception:
                # si falla, no rompemos la operación: conservar lo que haya
                pass
        enriched.append(item)

    conn.close()
    return {"cart": cart, "items": enriched}


def remove_cart_item(item_id: int, db_path: str = DB_DEFAULT_PATH) -> bool:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM cart_items WHERE id = ?", (item_id,))
    changed = cur.rowcount
    conn.commit()
    conn.close()
    return changed > 0


# ----------------------
# Checkout / Orders
# ----------------------
def _send_order_to_distributor_stub(order_payload: Dict[str, Any]) -> bool:
    """
    Stub que simula enviar el pedido al distribuidor.
    Reemplaza esta función por integración real (requests.post / SMTP / API).
    """
    print("=== Enviando pedido al distribuidor (STUB) ===")
    print(order_payload)
    # Simular éxito
    return True


def checkout(user_id: int, shipping_address: str, distributor_contact: Optional[str] = None, db_path: str = DB_DEFAULT_PATH) -> Dict[str, Any]:
    """
    Genera un order a partir del carrito del usuario, crea order_items, notifica al distribuidor
    y vacía el carrito en caso de éxito.
    """
    # obtener carrito del user
    conn = _get_conn(db_path)
    cur = conn.cursor()
    # busca carrito del usuario
    cur.execute("SELECT * FROM carts WHERE user_id = ? LIMIT 1", (user_id,))
    cart = cur.fetchone()
    if not cart:
        conn.close()
        raise ValueError("Carrito no encontrado para el usuario")

    cart_id = cart["id"]
    cur.execute("SELECT * FROM cart_items WHERE cart_id = ?", (cart_id,))
    items = [dict(r) for r in cur.fetchall()]
    if not items:
        conn.close()
        raise ValueError("Carrito vacío")

    # calcular total
    total = 0.0
    for it in items:
        price = it.get("price") or 0.0
        try:
            total += float(price) * int(it.get("qty", 1))
        except Exception:
            total += 0.0

    # crear order
    cur.execute(
        "INSERT INTO orders (user_id, total, status, shipping_address, distributor_contact, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, total, "pending", shipping_address, distributor_contact, datetime.utcnow()),
    )
    conn.commit()
    order_id = cur.lastrowid

    # crear order_items
    for it in items:
        cur.execute(
            "INSERT INTO order_items (order_id, book_id, title, qty, price) VALUES (?, ?, ?, ?, ?)",
            (order_id, it["book_id"], it.get("title"), it.get("qty"), it.get("price")),
        )
    conn.commit()

    # preparar payload para distribuidor
    order_payload = {
        "order_id": order_id,
        "user_id": user_id,
        "shipping_address": shipping_address,
        "distributor_contact": distributor_contact,
        "items": [{"book_id": it["book_id"], "title": it.get("title"), "qty": it.get("qty")} for it in items],
        "total": total,
    }

    ok = _send_order_to_distributor_stub(order_payload)
    if ok:
        # actualizar estado
        cur.execute("UPDATE orders SET status = ? WHERE id = ?", ("sent_to_supplier", order_id))
        # vaciar carrito
        cur.execute("DELETE FROM cart_items WHERE cart_id = ?", (cart_id,))
        conn.commit()
        conn.close()
        return {"order_id": order_id, "status": "sent_to_supplier"}
    else:
        cur.execute("UPDATE orders SET status = ? WHERE id = ?", ("error_sending", order_id))
        conn.commit()
        conn.close()
        return {"order_id": order_id, "status": "error_sending"}

def list_orders_for_user(user_id: int, db_path: str = DB_DEFAULT_PATH) -> List[Dict[str, Any]]:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def get_order(order_id: int, db_path: str = DB_DEFAULT_PATH) -> Optional[Dict[str, Any]]:
    conn = _get_conn(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE id = ? LIMIT 1", (order_id,))
    order = cur.fetchone()
    if not order:
        conn.close()
        return None
    order = dict(order)
    cur.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,))
    items = [dict(r) for r in cur.fetchall()]
    conn.close()
    order["items"] = items
    return order
# --- Compatibilidad: aliases / inicializadores buscados por app.py ----------------

def create_tables(db_path: str = DB_DEFAULT_PATH):
    """
    Alias a init_db para compatibilidad con app.py que puede llamar create_tables().
    """
    return init_db(db_path)


def initialize_database(db_path: str = DB_DEFAULT_PATH, excel_path: str = None):
    """
    Inicializa la DB (alias más descriptivo). Si excel_path es provisto (o si existe
    la ruta por defecto), intenta importar libros usando import_books_from_excel.
    """
    init_db(db_path)

    # decidir ruta de excel: argumento > variable por defecto
    excel_candidate = excel_path or "data/Rosana_Chile_BASe_092025.xlsx"
    if os.path.exists(excel_candidate):
        try:
            import_books_from_excel(excel_candidate, db_path=db_path)
            print(f"Libros importados desde {excel_candidate}")
        except Exception as e:
            print(f"[warning] import_books_from_excel falló: {e}")
    else:
        print(f"[info] No se encontró {excel_candidate}; omitiendo importación de libros.")

def get_all_books(db_path: str = DB_DEFAULT_PATH):
    """
    Devuelve todos los libros de la tabla 'books'.
    Retorna una lista de diccionarios.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, vendedor, url, titulo, imagen, autor, editorial, 
               año, tapa, idioma, tipo, genero, isbn, ro_chile_u
        FROM books
        ORDER BY titulo ASC
    """)

    rows = cursor.fetchall()
    conn.close()

    # Convertir a dicts para facilidad de uso
    books = []
    for r in rows:
        books.append({
            "id": r[0],
            "vendedor": r[1],
            "url": r[2],
            "titulo": r[3],
            "imagen": r[4],
            "autor": r[5],
            "editorial": r[6],
            "anio": r[7],
            "tapa": r[8],
            "idioma": r[9],
            "tipo": r[10],
            "genero": r[11],
            "isbn": r[12],
            "precio": r[13],
        })

    return books

# También alias más cortos por si app.py usa init_db directamente
def initialize(db_path: str = DB_DEFAULT_PATH):
    return init_db(db_path)

if __name__ == "__main__":
    print("Inicializando DB...")
    init_db()
    sample_excel = "data/Rosana_Chile_BASe_092025.xlsx"
    if os.path.exists(sample_excel):
        print("Importando books desde", sample_excel)
        import_books_from_excel(sample_excel)
    else:
        print(f"No encontré {sample_excel}; si quieres importar tu Excel colócalo en esa ruta y vuelve a ejecutar.")
>>>>>>> c8868379068986da1fb6f5e979199c1dd2f6b8fc
    print("Hecho. Usa las funciones del módulo desde tu app Flask.")