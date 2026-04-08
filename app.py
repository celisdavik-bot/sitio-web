from flask import Flask, render_template, redirect, request, session, url_for, flash, jsonify, g
import controller as db
import os
import sqlite3
import uuid
from transbank.webpay.webpay_plus.transaction import Transaction
from transbank.common.options import WebpayOptions
from transbank.common.integration_type import IntegrationType

DB_PATH = os.path.join("data", "shop.db")
app = Flask(__name__)
app.secret_key = "super_secret_key"

WEBPAY_COMMERCE_CODE = "597055555532"
WEBPAY_API_KEY = "579B532A7440BB0C9079DED94D31EA1615BACEB56610332264630D42D0A36B1C"
WEBPAY_ENV = IntegrationType.TEST

print("Inicializando base de datos...")
db.create_tables()
print("Base de datos lista.")

@app.route("/books/<int:book_id>", methods=["GET"])
def book_page(book_id):
    get_fn = getattr(db, "get_book", None) or getattr(db, "get_book_by_id", None)
    if not callable(get_fn):
        return "Función get_book no encontrada en controller.py", 500
    try:
        book = get_fn(book_id=book_id, db_path=DB_PATH) if "db_path" in get_fn.__code__.co_varnames else get_fn(book_id)
    except TypeError:
        book = get_fn(book_id)
    except Exception as e:
        print("Error obteniendo libro:", e)
        book = None
    if not book:
        return render_template("404.html"), 404
    return render_template("book_detail.html", book=book)

def get_cart_count():
    cart = session.get("cart", {})
    if not cart:
        return 0
    return sum(item.get("qty", 1) for item in cart.values())

DATABASE = os.path.join("data", "shop.db")

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON;")
    return g.db

@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

@app.route("/")
def index():
    q = request.args.get("q", "")
    try:
        page = int(request.args.get("page", 1))
    except Exception:
        page = 1
    per_page = 20
    offset = (page - 1) * per_page
    conn = get_db()
    cur = conn.cursor()
    if q:
        cur.execute("""
            SELECT * FROM books
            WHERE titulo LIKE ? OR autor LIKE ? OR editorial LIKE ?
            LIMIT ? OFFSET ?
        """, (f"%{q}%", f"%{q}%", f"%{q}%", per_page, offset))
        books_rows = cur.fetchall()
        books = [dict(r) for r in books_rows]
        cur.execute("""
            SELECT COUNT(*) FROM books
            WHERE titulo LIKE ? OR autor LIKE ? OR editorial LIKE ?
        """, (f"%{q}%", f"%{q}%", f"%{q}%"))
        total = cur.fetchone()[0]
    else:
        cur.execute("SELECT * FROM books LIMIT ? OFFSET ?", (per_page, offset))
        books_rows = cur.fetchall()
        books = [dict(r) for r in books_rows]
        cur.execute("SELECT COUNT(*) FROM books")
        total = cur.fetchone()[0]
    total_pages = (total // per_page) + (1 if total % per_page else 0)
    cart_count = 0
    get_cart_fn = getattr(db, "get_cart", None)
    if callable(get_cart_fn):
        user_id = session.get("user_id")
        if not user_id:
            if "cart_session_id" not in session:
                session["cart_session_id"] = str(uuid.uuid4())
            sid = session["cart_session_id"]
            try:
                cart = get_cart_fn(user_id=None, session_id=sid, db_path=DB_PATH)
            except TypeError:
                cart = get_cart_fn(None, sid)
        else:
            try:
                cart = get_cart_fn(user_id=user_id, session_id=None, db_path=DB_PATH)
            except TypeError:
                cart = get_cart_fn(user_id, None)
        cart_count = len(cart.get("items", [])) if cart else 0
    return render_template(
        "index.html",
        books=books,
        q=q,
        page=page,
        total_pages=total_pages,
        cart_count=cart_count
    )

    q = request.args.get("q", "").strip() or None
    try:
        limit = int(request.args.get("limit", 24))
    except Exception:
        limit = 24
    search_fn = getattr(db, "search_books", None)
    if callable(search_fn):
        try:
            books = search_fn(q=q, limit=limit, db_path=DB_PATH)
        except TypeError:
            books = search_fn(q=q, limit=limit)
    else:
        books = []
    cart_count = 0
    get_cart_fn = getattr(db, "get_cart", None)
    if callable(get_cart_fn):
        user_id = session.get("user_id")
        if not user_id:
            if "cart_session_id" not in session:
                session["cart_session_id"] = str(uuid.uuid4())
            sid = session["cart_session_id"]
            try:
                cart = get_cart_fn(user_id=None, session_id=sid, db_path=DB_PATH)
            except TypeError:
                cart = get_cart_fn(None, sid)
        else:
            try:
                cart = get_cart_fn(user_id=user_id, session_id=None, db_path=DB_PATH)
            except TypeError:
                cart = get_cart_fn(user_id, None)
        cart_count = len(cart.get("items", [])) if cart else 0
    return render_template("index.html", books=books, cart_count=cart_count, q=(q or ""))

@app.route("/registrar")
def registrar():
    return render_template("registrar.html")

@app.route("/register", methods=["POST"])
def register():
    data = request.json if request.is_json else request.form
    email = data.get("email")
    password = data.get("password")
    name = data.get("name", "")
    if not email or not password:
        return jsonify({"error": "email y password requeridos"}), 400
    create_fn = getattr(db, "create_user", None)
    if not callable(create_fn):
        return jsonify({"error": "create_user no definida en controller.py"}), 500
    try:
        if "db_path" in create_fn.__code__.co_varnames:
            user = create_fn(email=email, password=password, name=name, db_path=DB_PATH)
        else:
            user = create_fn(email, password, name)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print("ERROR register:", tb)
        return jsonify({"error": "Error al registrarse", "detail": str(e)}), 400
    session["user_id"] = user["id"]
    session["is_admin"] = (user.get("role") == "admin")
    return jsonify({"msg": "usuario creado", "user": user})

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        auth_fn = getattr(db, "authenticate_user", None) or getattr(db, "validate_user", None) or getattr(db, "login_user", None)
        if not callable(auth_fn):
            return jsonify({"error": "función de autenticación no encontrada en controller.py"}), 500
        try:
            if "db_path" in auth_fn.__code__.co_varnames:
                user = auth_fn(email=email, password=password, db_path=DB_PATH)
            else:
                user = auth_fn(email, password)
        except Exception as e:
            print("ERROR auth:", e)
            user = None
        if user:
            session["user_id"] = user["id"]
            session["user_name"] = user.get("name")
            session["is_admin"] = (user.get("role") == "admin")
            flash("Inicio de sesión correcto.", "success")
            return redirect(url_for("index"))
        else:
            flash("Credenciales inválidas.", "danger")
    try:
        return render_template("login.html")
    except Exception:
        return """
            <form method="post">
                Email: <input name="email"/><br/>
                Password: <input name="password" type="password"/><br/>
                <button type="submit">Login</button>
            </form>
        """
        
@app.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada correctamente.", "info")
    return redirect(url_for("index"))

@app.route("/cart/add", methods=["POST"])
def route_add_to_cart():
    data = request.get_json(silent=True) or request.form
    book_id = data.get("book_id") or data.get("id") or data.get("bookId")
    qty = data.get("qty") or data.get("quantity") or 1
    print("DEBUG /cart/add - headers:", dict(request.headers))
    print("DEBUG /cart/add - payload:", data)
    if not book_id:
        return jsonify({"error": "book_id requerido"}), 400
    try:
        book_id = int(book_id)
    except Exception:
        return jsonify({"error": "book_id debe ser entero"}), 400
    try:
        qty = int(qty)
    except Exception:
        qty = 1
    user_id = session.get("user_id")
    session_id = None if user_id else session.get("cart_session_id")
    if not user_id and not session_id:
        import uuid
        session_id = str(uuid.uuid4())
        session["cart_session_id"] = session_id
    add_fn = getattr(db, "add_to_cart", None)
    if not callable(add_fn):
        return jsonify({"error": "add_to_cart no definida en controller.py"}), 500
    try:
        if "db_path" in add_fn.__code__.co_varnames:
            item = add_fn(user_id=user_id, session_id=session_id, book_id=book_id, qty=qty, db_path=DB_PATH)
        else:
            item = add_fn(user_id, session_id, book_id, qty)
    except Exception as e:
        import traceback
        print("ERROR en add_to_cart:", traceback.format_exc())
        return jsonify({"error": str(e)}), 500
    return jsonify({"msg": "agregado", "item": item})

@app.route("/webpay/pagar", methods=["POST"])
def webpay_pagar():
    shipping_address = request.form.get("shipping_address") or (request.get_json(silent=True) or {}).get("shipping_address")
    distributor_contact = request.form.get("distributor_contact") or (request.get_json(silent=True) or {}).get("distributor_contact")
    user_id = session.get("user_id")
    if not user_id:
        return "Debes iniciar sesión para pagar.", 401
    create_order_fn = getattr(db, "create_order_for_payment", None)
    order_info = None
    if callable(create_order_fn):
        try:
            if "db_path" in create_order_fn.__code__.co_varnames:
                order_info = create_order_fn(user_id=user_id, shipping_address=shipping_address or "", distributor_contact=distributor_contact, db_path=DB_PATH)
            else:
                order_info = create_order_fn(user_id, shipping_address or "", distributor_contact)
        except Exception as e:
            import traceback
            print("ERROR create_order_for_payment:", traceback.format_exc())
            return f"Error creando orden: {e}", 400
    else:
        try:
            data = db.get_cart(user_id=user_id, session_id=session.get("cart_session_id"), db_path=DB_PATH) if getattr(db, "get_cart", None) else {"items": []}
            items = data.get("items", [])
            total = 0
            for i in items:
                p = i.get("price") or i.get("precio") or 0
                try:
                    total += float(p) * 1000 * int(i.get("qty") or 1)
                except Exception:
                    pass
            order_info = {"total": total, "buy_order": str(uuid.uuid4())[:26], "order_id": None, "items": items}
        except Exception as e:
            print("ERROR fallback total calc:", e)
            return "Error accediendo al carrito", 500
    total_float = float(order_info.get("total") or 0.0)
    total_int = int(round(total_float))
    print("DEBUG total calculado (float):", total_float, "-> total_int:", total_int)
    if total_int <= 0:
        return "Carrito vacío o sin precios válidos.", 400
    buy_order = order_info.get("buy_order")
    session_id = session.get("cart_session_id") or str(uuid.uuid4())
    session["cart_session_id"] = session_id
    return_url = request.host_url.rstrip("/") + "/webpay/confirmacion"
    try:
        opts = WebpayOptions(WEBPAY_COMMERCE_CODE, WEBPAY_API_KEY, WEBPAY_ENV)
        tx = Transaction(opts)
        response = tx.create(buy_order, session_id, int(total_int), return_url)
        token = response.get("token")
        url = response.get("url")
        return redirect(f"{url}?token_ws={token}")
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print("ERROR Webpay create:", tb)
        return f"Error creando transacción Webpay: {e}", 500
    print("Webpay config:", {"commerce_code": WEBPAY_COMMERCE_CODE, "api_key": WEBPAY_API_KEY, "env": WEBPAY_ENV})
    user_id = session.get("user_id")
    if not user_id:
        flash("Debes iniciar sesión para pagar.", "warning")
        return redirect(url_for("login"))
    if "cart_session_id" not in session:
        session["cart_session_id"] = str(uuid.uuid4())
    sid = session["cart_session_id"]
    try:
        create_fn = getattr(db, "create_order_for_payment", None)
        if not callable(create_fn):
            return "Función create_order_for_payment no encontrada en controller", 500
        if "db_path" in create_fn.__code__.co_varnames:
            order_info = create_fn(user_id=user_id, shipping_address="", distributor_contact=None, db_path=DB_PATH)
        else:
            order_info = create_fn(user_id, "", None)
        print("DEBUG create_order_for_payment ->", order_info)
    except Exception as e:
        import traceback
        print("ERROR creando order antes de Webpay:", traceback.format_exc())
        return f"Error creando orden: {e}", 500
    buy_order = order_info.get("buy_order")
    total = order_info.get("total") or 0
    total_int = int(round(total))
    if total_int <= 0:
        return "Carrito vacío o sin precios válidos.", 400
    return_url = request.host_url.rstrip("/") + "/webpay/confirmacion"
    print("DEBUG return_url:", return_url, "buy_order:", buy_order, "total_int:", total_int)
    try:
        try:
            opts = WebpayOptions(WEBPAY_COMMERCE_CODE, WEBPAY_API_KEY, WEBPAY_ENV)
            tx = Transaction(opts)
        except Exception:
            tx = Transaction(commerce_code=WEBPAY_COMMERCE_CODE, api_key=WEBPAY_API_KEY, integration_type=WEBPAY_ENV)
        response = tx.create(buy_order, sid, int(total_int), return_url)
        print("Webpay create response:", response)
        token = response.get("token")
        url = response.get("url")
        return redirect(f"{url}?token_ws={token}")
    except Exception as e:
        import traceback
        print("ERROR Webpay create:", traceback.format_exc())
        return f"Error creando transacción Webpay: {e}", 500
    print("Webpay config:", {"commerce_code": WEBPAY_COMMERCE_CODE, "api_key": WEBPAY_API_KEY, "env": WEBPAY_ENV})
    user_id = session.get("user_id")
    if "cart_session_id" not in session:
        session["cart_session_id"] = str(uuid.uuid4())
    sid = session["cart_session_id"]
    try:
        data = db.get_cart(user_id=user_id, session_id=sid, db_path=DB_PATH) if getattr(db, "get_cart", None) else {"items": []}
    except Exception as e:
        print("ERROR obt. cart:", e)
        return "Error accediendo al carrito", 500
    items = data.get("items", [])
    total = 0.0
    for i in items:
        try:
            price = int((i.get("price")*1000) or 0)
            qty = int(i.get("qty") or 1)
            total += price * qty
        except Exception:
            pass
    total_int = int(round(total))
    print("DEBUG total calculado (float):", total, "-> total_int:", total_int)
    if total_int <= 0:
        return "Carrito vacío o sin precios válidos.", 400
    buy_order = str(uuid.uuid4())[:26]
    session_id = sid
    return_url = request.host_url.rstrip("/") + "/webpay/confirmacion"
    print("DEBUG return_url:", return_url)
    try:
        opts = WebpayOptions(WEBPAY_COMMERCE_CODE, WEBPAY_API_KEY, WEBPAY_ENV)
        tx = Transaction(opts)
        response = tx.create(buy_order, session_id, int(total_int), return_url)
        print("Webpay create response:", response)
        token = response.get("token")
        url = response.get("url")
        return redirect(f"{url}?token_ws={token}")
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print("ERROR Webpay create:", tb)
        try:
            err_msg = getattr(e, "args", [str(e)])[0]
        except:
            err_msg = str(e)
        return f"Error creando transacción Webpay: {err_msg}", 500

@app.route("/cart", methods=["GET"])
def cart_page():
    get_cart_fn = getattr(db, "get_cart", None)
    if not callable(get_cart_fn):
        return "get_cart no encontrado en controller.py", 500
    user_id = session.get("user_id")
    if not user_id:
        if "cart_session_id" not in session:
            session["cart_session_id"] = str(uuid.uuid4())
        sid = session["cart_session_id"]
        try:
            data = get_cart_fn(user_id=None, session_id=sid, db_path=DB_PATH)
        except TypeError:
            data = get_cart_fn(None, sid)
    else:
        try:
            data = get_cart_fn(user_id=user_id, session_id=None, db_path=DB_PATH)
        except TypeError:
            data = get_cart_fn(user_id, None)
    cart = data.get("cart", {}) if isinstance(data, dict) else {}
    items = data.get("items", []) if isinstance(data, dict) else []
    return render_template("cart.html", cart=cart, items=items)

    get_cart_fn = getattr(db, "get_cart", None)
    if not callable(get_cart_fn):
        return "get_cart no encontrado en controller.py", 500
    user_id = session.get("user_id")
    if not user_id:
        if "cart_session_id" not in session:
            session["cart_session_id"] = str(uuid.uuid4())
        sid = session["cart_session_id"]
        try:
            data = get_cart_fn(user_id=None, session_id=sid, db_path=DB_PATH)
        except TypeError:
            data = get_cart_fn(None, sid)
    else:
        try:
            data = get_cart_fn(user_id=user_id, session_id=None, db_path=DB_PATH)
        except TypeError:
            data = get_cart_fn(user_id, None)
    cart = data.get("cart", {}) if isinstance(data, dict) else {}
    items = data.get("items", []) if isinstance(data, dict) else []
    return render_template("cart.html", cart=cart, items=items)

@app.route("/cart/remove", methods=["POST"])
def route_remove_from_cart():
    data = request.get_json(silent=True) or request.form
    item_id = data.get("item_id")
    if not item_id:
        return jsonify({"error": "item_id requerido"}), 400
    try:
        ok = getattr(db, "remove_cart_item", None)(int(item_id), db_path=DB_PATH) if "db_path" in getattr(db, "remove_cart_item").__code__.co_varnames else getattr(db, "remove_cart_item")(int(item_id))
    except Exception as e:
        import traceback
        print("ERROR /cart/remove:", traceback.format_exc())
        return jsonify({"error": str(e)}), 500
    return jsonify({"removed": bool(ok)})

@app.route("/checkout", methods=["POST"])
def route_checkout():
    print("DEBUG route_checkout - session keys:", dict(session))
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "debes iniciar sesión antes de comprar"}), 401
    data = request.get_json(silent=True) or request.form
    shipping_address = data.get("shipping_address") or ""
    distributor_contact = data.get("distributor_contact")
    checkout_fn = getattr(db, "checkout", None)
    if not callable(checkout_fn):
        return jsonify({"error": "checkout no definido en controller.py"}), 500
    try:
        if "db_path" in checkout_fn.__code__.co_varnames:
            result = checkout_fn(user_id=user_id, shipping_address=shipping_address, distributor_contact=distributor_contact, db_path=DB_PATH)
        else:
            result = checkout_fn(user_id, shipping_address, distributor_contact)
    except Exception as e:
        import traceback
        print("ERROR /checkout:", traceback.format_exc())
        return jsonify({"error": str(e)}), 400
    return jsonify(result)

@app.route("/orders", methods=["GET"])
def orders_list():
    print("DEBUG session:", dict(session))
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))
    list_fn = getattr(db, "list_orders_for_user", None)
    if not callable(list_fn):
        return "list_orders_for_user no definida", 500
    try:
        orders = list_fn(user_id=user_id, db_path=DB_PATH) if "db_path" in list_fn.__code__.co_varnames else list_fn(user_id)
    except Exception as e:
        print("ERROR /orders:", e)
        orders = []
    return render_template("orders.html", orders=orders)

@app.route("/orders/<int:order_id>", methods=["GET"])
def order_detail_page(order_id):
    user_id = session.get("user_id")
    is_admin = bool(session.get("is_admin"))
    print("DEBUG /orders/<id> - session:", {"user_id": user_id, "is_admin": is_admin})
    if not user_id and not is_admin:
        return redirect(url_for("login"))
    get_fn = getattr(db, "get_order", None)
    order = None
    if callable(get_fn):
        try:
            order = get_fn(order_id=order_id, db_path=DB_PATH) if "db_path" in get_fn.__code__.co_varnames else get_fn(order_id)
        except Exception as e:
            print("ERROR get_order:", e)
            order = None
    else:
        try:
            import sqlite3
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM orders WHERE id = ? LIMIT 1", (order_id,))
            o = cur.fetchone()
            order = dict(o) if o else None
            conn.close()
        except Exception as e:
            print("ERROR fallback get_order:", e)
            order = None
    if not order:
        return "Pedido no encontrado", 404
    try:
        order_user_id = int(order.get("user_id")) if order.get("user_id") is not None else None
    except Exception:
        order_user_id = None
    try:
        session_user_id = int(user_id) if user_id is not None else None
    except Exception:
        session_user_id = None
    if not is_admin and (session_user_id is None or order_user_id is None or session_user_id != order_user_id):
        print("DEBUG permiso denegado: session_user_id=", session_user_id, "order_user_id=", order_user_id)
        return "Pedido no encontrado o sin permisos", 404
    return render_template("order_detail.html", order=order)

def _ensure_books_columns(conn, required_cols):
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(books);")
    existing = {r[1] for r in cur.fetchall()}
    for col, coltype in required_cols.items():
        if col not in existing:
            try:
                cur.execute(f"ALTER TABLE books ADD COLUMN {col} {coltype};")
                conn.commit()
            except Exception as e:
                print("No se pudo crear columna", col, e)

@app.route("/admin/books/add", methods=["GET", "POST"])
def admin_add_book():
    if not session.get("user_id") or not session.get("is_admin"):
        flash("Acceso restringido: Administradores solamente.", "warning")
        return redirect(url_for("login"))
    if request.method == "POST":
        title = request.form.get("title")
        author = request.form.get("author")
        price = request.form.get("price")
        image = request.form.get("image")
        publisher = request.form.get("publisher")
        year = request.form.get("year")
        if not title:
            flash("El título es requerido.", "danger")
            return redirect(url_for("admin_add_book"))
        try:
            import sqlite3
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            _ensure_books_columns(conn, {
                "title": "TEXT",
                "author": "TEXT",
                "price": "REAL",
                "image": "TEXT",
                "publisher": "TEXT",
                "year": "TEXT"
            })
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO books (title, author, price, image, publisher, year) VALUES (?, ?, ?, ?, ?, ?)",
                (title, author, float(price) if price else None, image, publisher, year)
            )
            conn.commit()
            conn.close()
            flash("Libro agregado correctamente.", "success")
            return redirect(url_for("index"))
        except Exception as e:
            import traceback
            print("ERROR admin add book:", traceback.format_exc())
            flash("Error al agregar libro: " + str(e), "danger")
            return redirect(url_for("admin_add_book"))
    return render_template("admin_add_book.html")

@app.route("/admin/orders", methods=["GET"])
def admin_orders():
    if not session.get("user_id") or not session.get("is_admin"):
        flash("Acceso restringido: Administradores solamente.", "warning")
        return redirect(url_for("login"))
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM orders ORDER BY created_at DESC")
        rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print("ERROR al obtener órdenes admin:", e)
        rows = []
    finally:
        conn.close()
    return render_template("admin_orders.html", orders=rows)

@app.route("/webpay/confirmacion", methods=["GET", "POST"])
def webpay_confirmacion():
    token = request.args.get("token_ws") or request.form.get("token_ws")
    if not token:
        return "Token no recibido (token_ws).", 400
    try:
        opts = WebpayOptions(WEBPAY_COMMERCE_CODE, WEBPAY_API_KEY, WEBPAY_ENV)
        tx = Transaction(opts)
    except Exception:
        try:
            tx = Transaction(
                commerce_code=WEBPAY_COMMERCE_CODE,
                api_key=WEBPAY_API_KEY,
                integration_type=WEBPAY_ENV
            )
        except Exception as e:
            print("ERROR creando Transaction:", e)
            return "Error interno creando Transaction (revisa logs).", 500
    try:
        commit_resp = tx.commit(token)
        print("Webpay commit response:", commit_resp)
    except Exception as e:
        import traceback
        print("ERROR en Webpay commit:", traceback.format_exc())
        return render_template("webpay_result.html", success=False, detail=str(e), token=token), 500
    try:
        buy_order = commit_resp.get("buy_order") or commit_resp.get("buyOrder") or None
        session_id = commit_resp.get("session_id") or commit_resp.get("sessionId") or None
        amount = commit_resp.get("amount") or commit_resp.get("total") or None
        if buy_order:
            conn = db._get_conn(DB_PATH)
            cur = conn.cursor()
            try:
                cur.execute("UPDATE orders SET status = ?, distributor_contact = ? WHERE webpay_buy_order = ?",
                            ("paid", str(commit_resp), buy_order))
                conn.commit()
                print("Order actualizado por buy_order:", buy_order, "filas afectadas:", cur.rowcount)
            except Exception as e:
                print("Warning: no se pudo actualizar orders automáticamente (revisa lógica).", e)
            finally:
                conn.close()
        else:
            if session_id:
                conn = db._get_conn(DB_PATH)
                cur = conn.cursor()
                try:
                    cur.execute("UPDATE orders SET status = ? WHERE id = (SELECT id FROM orders WHERE session_id = ? LIMIT 1)",
                                ("paid", session_id))
                    conn.commit()
                    print("Order actualizado por session_id:", session_id, "filas afectadas:", cur.rowcount)
                except Exception as e:
                    print("Warning: no se pudo actualizar orders por session_id.", e)
                finally:
                    conn.close()
    except Exception as e:
        print("Warning: error al intentar actualizar pedido:", e)
    return render_template("webpay_result.html", success=True, detail=commit_resp, token=token)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)