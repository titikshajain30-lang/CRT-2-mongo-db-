# BankX — Bank Management System

A full-stack academic banking-management demo built with **Python Flask**, **MongoDB Atlas**, **PyMongo**, HTML, CSS and JavaScript. The interface is inspired by the supplied banking-dashboard reference.

> **Academic/demo software only.** This is not a real banking platform and must not be used to hold, transfer or manage real money. It has no connection to any bank or payment network. The transaction workflow is a classroom simulation. A production banking system requires audited ledger design, database transactions, robust authorization, KYC/AML, regulatory compliance, monitoring, backups and security review.

## Features

- Customer registration and login; passwords are hashed with bcrypt.
- One-time admin bootstrap page at `/admin/create`.
- Automatic unique demo account number on customer registration.
- Dashboard with account balance, customer/account/transaction totals for admins.
- Customer search (admin only).
- Account listing and admin account activation/deactivation.
- Simulated deposit, withdrawal and account-to-account transfer.
- Transaction history with timestamps.
- MongoDB Atlas persistence through PyMongo.
- Responsive dashboard layout, charts and recent transactions.

## Requirements

- Python 3.10+
- MongoDB Atlas account and a database user
- Internet access for the Atlas connection

## Setup

1. **Extract the ZIP** and open the `BankX_Bank_Management_System` folder in VS Code.
2. Create and activate a virtual environment:

   Windows PowerShell:
   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

   macOS/Linux:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure MongoDB Atlas**:
   - Create a free cluster in MongoDB Atlas.
   - Under **Database Access**, create a database username and password.
   - Under **Network Access**, allow your current IP address. Avoid `0.0.0.0/0` except for a temporary classroom test, and remove it afterwards.
   - Click **Connect → Drivers → Python** and copy the connection string.
   - Copy `.env.example` to a new file named `.env`.
   - Replace the URI placeholders with your real Atlas username, password and cluster hostname. URL-encode special characters in the password.
   - Set a long random `SECRET_KEY`. Never share or commit `.env`.

   Example `.env` shape:
   ```env
   MONGO_URI=mongodb+srv://myUser:myPassword@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   DB_NAME=bankx
   SECRET_KEY=a-long-random-secret-value
   FLASK_DEBUG=true
   ```

5. Run the application:
   ```bash
   python app.py
   ```
6. Open `http://127.0.0.1:5000`.

## First-time use

1. Visit `http://127.0.0.1:5000/admin/create` and create the first administrator. This route automatically disables itself once an admin exists.
2. Sign in as the admin.
3. Register a customer using **Create account**.
4. Use the customer's account number to test simulated deposits, withdrawals and transfers.
5. The admin can search customers and view all accounts and transactions.

## Main routes

| Route | Purpose | Access |
|---|---|---|
| `/` | Landing page | Public |
| `/register` | Customer registration | Public |
| `/login` | Sign in | Public |
| `/admin/create` | First admin setup (only before an admin exists) | Public until initialized |
| `/dashboard` | Dashboard | Signed in |
| `/customers` | Search/manage customer list | Admin |
| `/accounts` | View accounts | Signed in |
| `/transactions` | Transaction history | Signed in |
| `/transactions/new` | Simulated deposit/withdrawal/transfer | Signed in |

## MongoDB collections

- `users`: name, username, email, bcrypt password hash, role, created timestamp.
- `accounts`: owner user ID, unique account number, account type, balance, status, created timestamp.
- `transactions`: type, source/destination account numbers, amount, description, timestamp and actor.

Unique indexes are created automatically when the app connects.

## Troubleshooting

- **Server selection timeout / can't connect:** check Atlas cluster status, IP access list, database username/password and the exact URI.
- **Authentication failed:** the Atlas database user is different from your Atlas website login. Check Database Access.
- **Invalid URI:** replace every placeholder and URL-encode special characters in the password.
- **PowerShell blocks activation:** run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal, then activate the venv again.
- **Port already in use:** stop the other Flask process or change the port in the `app.run(...)` line.

## Notes for academic demonstration

The transfer code uses guarded balance updates and a compensating rollback if the destination cannot be credited. This is intentionally a simple demonstration, **not a substitute for MongoDB multi-document transactions**. For a robust implementation, use an Atlas replica set transaction and an immutable double-entry ledger. Also add CSRF protection, rate limiting, email verification, audit logs, secure cookie settings and formal tests before any deployment.
