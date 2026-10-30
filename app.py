import os
import secrets
from datetime import datetime, timezone
from functools import wraps

from bson import ObjectId
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_bcrypt import Bcrypt
from pymongo import MongoClient, DESCENDING
from pymongo.errors import DuplicateKeyError, PyMongoError

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-this-development-secret")
bcrypt = Bcrypt(app)

MONGO_URI = os.getenv("MONGO_URI", "")
DB_NAME = os.getenv("DB_NAME", "bankx")
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000) if MONGO_URI else None
db = client[DB_NAME] if client is not None else None

if db is not None:
    # Unique indexes protect account numbers, emails and usernames.
    db.users.create_index("email", unique=True)
    db.users.create_index("username", unique=True)
    db.accounts.create_index("account_number", unique=True)
    db.transactions.create_index([("created_at", DESCENDING)])


def database_ready():
    if db is None:
        return False
    try:
        client.admin.command("ping")
        return True
    except PyMongoError:
        return False


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Administrator access is required.", "danger")
            return redirect(url_for("dashboard"))
        return fn(*args, **kwargs)
    return wrapper


def current_user():
    if db is None or "user_id" not in session:
        return None
    return db.users.find_one({"_id": ObjectId(session["user_id"])})


def make_account_number():
    # Random 12-digit demo account number; unique index handles collisions.
    return "BX" + "".join(secrets.choice("0123456789") for _ in range(10))


def money(value):
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


@app.context_processor
def inject_globals():
    return {"logged_in_user": current_user(), "db_connected": database_ready()}


@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        if db is None:
            flash("Add your MongoDB Atlas connection string in .env first.", "danger")
            return render_template("register.html")
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not all([name, username, email, password]):
            flash("Please complete every field.", "warning")
        elif len(password) < 8:
            flash("Password must contain at least 8 characters.", "warning")
        else:
            try:
                user_id = db.users.insert_one({
                    "name": name, "username": username, "email": email,
                    "password_hash": bcrypt.generate_password_hash(password).decode("utf-8"),
                    "role": "customer", "created_at": datetime.now(timezone.utc)
                }).inserted_id
                account_no = make_account_number()
                db.accounts.insert_one({
                    "user_id": user_id, "account_number": account_no,
                    "account_type": "Savings", "balance": 0.0,
                    "status": "Active", "created_at": datetime.now(timezone.utc)
                })
                flash(f"Registration successful. Your account number is {account_no}. Please sign in.", "success")
                return redirect(url_for("login"))
            except DuplicateKeyError:
                flash("That username or email is already registered.", "danger")
            except PyMongoError:
                flash("Could not create your account. Check your MongoDB connection.", "danger")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if db is None:
            flash("Configure MongoDB Atlas in .env before signing in.", "danger")
            return render_template("login.html")
        identity = request.form.get("identity", "").strip().lower()
        password = request.form.get("password", "")
        user = db.users.find_one({"$or": [{"email": identity}, {"username": identity}]})
        if user and bcrypt.check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = str(user["_id"])
            session["role"] = user.get("role", "customer")
            session["name"] = user["name"]
            return redirect(url_for("dashboard"))
        flash("Invalid username/email or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    user_id = ObjectId(session["user_id"])
    if session.get("role") == "admin":
        accounts = list(db.accounts.find().sort("created_at", DESCENDING).limit(8))
        total_customers = db.users.count_documents({"role": "customer"})
        total_accounts = db.accounts.count_documents({})
        total_transactions = db.transactions.count_documents({})
        total_balance = sum(a.get("balance", 0) for a in db.accounts.find({}, {"balance": 1}))
        recent = list(db.transactions.find().sort("created_at", DESCENDING).limit(7))
        return render_template("dashboard.html", admin=True, accounts=accounts,
            total_customers=total_customers, total_accounts=total_accounts,
            total_transactions=total_transactions, total_balance=total_balance, recent=recent)
    account = db.accounts.find_one({"user_id": user_id})
    recent = list(db.transactions.find({"$or": [
        {"from_account": account["account_number"] if account else ""},
        {"to_account": account["account_number"] if account else ""}
    ]}).sort("created_at", DESCENDING).limit(7))
    return render_template("dashboard.html", admin=False, account=account, recent=recent)


@app.route("/customers")
@admin_required
def customers():
    query = request.args.get("q", "").strip()
    filter_query = {"role": "customer"}
    if query:
        filter_query["$or"] = [
            {"name": {"$regex": query, "$options": "i"}},
            {"email": {"$regex": query, "$options": "i"}},
            {"username": {"$regex": query, "$options": "i"}}
        ]
    users = list(db.users.find(filter_query).sort("created_at", DESCENDING))
    for user in users:
        user["account"] = db.accounts.find_one({"user_id": user["_id"]})
    return render_template("customers.html", users=users, q=query)


@app.route("/accounts")
@login_required
def accounts():
    if session.get("role") == "admin":
        data = list(db.accounts.find().sort("created_at", DESCENDING))
    else:
        data = list(db.accounts.find({"user_id": ObjectId(session["user_id"])}))
    for item in data:
        item["owner"] = db.users.find_one({"_id": item["user_id"]})
    return render_template("accounts.html", accounts=data)


@app.route("/accounts/<account_id>/status", methods=["POST"])
@admin_required
def account_status(account_id):
    status = request.form.get("status")
    if status not in ["Active", "Inactive"]:
        flash("Invalid account status.", "danger")
    else:
        db.accounts.update_one({"_id": ObjectId(account_id)}, {"$set": {"status": status}})
        flash(f"Account marked {status.lower()}.", "success")
    return redirect(url_for("accounts"))


@app.route("/transactions")
@login_required
def transactions():
    if session.get("role") == "admin":
        rows = list(db.transactions.find().sort("created_at", DESCENDING).limit(200))
    else:
        account = db.accounts.find_one({"user_id": ObjectId(session["user_id"])})
        number = account["account_number"] if account else ""
        rows = list(db.transactions.find({"$or": [{"from_account": number}, {"to_account": number}]}).sort("created_at", DESCENDING).limit(200))
    return render_template("transactions.html", transactions=rows)


def post_transaction(kind, source, target, amount, description):
    """Validate and record a demo ledger transaction.

    MongoDB Atlas shared/free deployments may not support multi-document
    transactions in every configuration. This academic demo uses guarded
    balance updates and compensating rollback for the second update.
    For real banking, use a replica-set transaction and a professionally
    audited ledger, idempotency keys, authorization and compliance controls.
    """
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    now = datetime.now(timezone.utc)
    if kind == "Deposit":
        result = db.accounts.update_one(
            {"account_number": target, "status": "Active"},
            {"$inc": {"balance": amount}}
        )
        if result.modified_count != 1:
            raise ValueError("Active destination account not found.")
    elif kind == "Withdrawal":
        result = db.accounts.update_one(
            {"account_number": source, "status": "Active", "balance": {"$gte": amount}},
            {"$inc": {"balance": -amount}}
        )
        if result.modified_count != 1:
            raise ValueError("Account not found, inactive, or insufficient balance.")
    else:
        if source == target:
            raise ValueError("Source and destination accounts must be different.")
        result = db.accounts.update_one(
            {"account_number": source, "status": "Active", "balance": {"$gte": amount}},
            {"$inc": {"balance": -amount}}
        )
        if result.modified_count != 1:
            raise ValueError("Source account not found, inactive, or insufficient balance.")
        credited = db.accounts.update_one(
            {"account_number": target, "status": "Active"},
            {"$inc": {"balance": amount}}
        )
        if credited.modified_count != 1:
            db.accounts.update_one({"account_number": source}, {"$inc": {"balance": amount}})
            raise ValueError("Destination account not found or inactive.")
    db.transactions.insert_one({
        "type": kind, "from_account": source or "—", "to_account": target or "—",
        "amount": amount, "description": description[:120],
        "created_at": now, "performed_by": session.get("user_id")
    })


@app.route("/transactions/new", methods=["GET", "POST"])
@login_required
def new_transaction():
    if request.method == "POST":
        kind = request.form.get("type")
        amount = money(request.form.get("amount"))
        source = request.form.get("from_account", "").strip().upper()
        target = request.form.get("to_account", "").strip().upper()
        description = request.form.get("description", "").strip()
        own = db.accounts.find_one({"user_id": ObjectId(session["user_id"])})
        if session.get("role") != "admin":
            if not own:
                flash("No account is linked to your profile.", "danger")
                return redirect(url_for("new_transaction"))
            if kind in ["Withdrawal", "Transfer"] and source != own["account_number"]:
                flash("Customers can only debit their own account.", "danger")
                return redirect(url_for("new_transaction"))
            if kind == "Deposit" and target != own["account_number"]:
                flash("Customers can only deposit into their own account.", "danger")
                return redirect(url_for("new_transaction"))
        try:
            if kind not in ["Deposit", "Withdrawal", "Transfer"]:
                raise ValueError("Choose a valid transaction type.")
            post_transaction(kind, source if kind != "Deposit" else "",
                             target if kind != "Withdrawal" else "", amount, description)
            flash(f"{kind} completed successfully.", "success")
            return redirect(url_for("transactions"))
        except (ValueError, PyMongoError) as exc:
            flash(str(exc) or "Transaction could not be completed.", "danger")
    own = db.accounts.find_one({"user_id": ObjectId(session["user_id"])})
    return render_template("new_transaction.html", own=own, admin=session.get("role") == "admin")


@app.route("/admin/create", methods=["GET", "POST"])
def create_admin():
    # One-time bootstrap route: enabled only when no admin exists.
    if db is None:
        flash("Configure MongoDB Atlas first.", "danger")
        return redirect(url_for("index"))
    if db.users.count_documents({"role": "admin"}) > 0:
        flash("An administrator already exists. Ask the current admin to manage access.", "warning")
        return redirect(url_for("login"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if len(password) < 10 or not all([name, username, email]):
            flash("Complete all fields. Admin password must be at least 10 characters.", "warning")
        else:
            try:
                db.users.insert_one({
                    "name": name, "username": username, "email": email,
                    "password_hash": bcrypt.generate_password_hash(password).decode("utf-8"),
                    "role": "admin", "created_at": datetime.now(timezone.utc)
                })
                flash("Admin created. Sign in with your new credentials.", "success")
                return redirect(url_for("login"))
            except DuplicateKeyError:
                flash("Username or email already exists.", "danger")
    return render_template("admin_setup.html")


@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", message="The page you requested could not be found."), 404


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
