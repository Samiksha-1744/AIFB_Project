from flask import (
    Flask, render_template, request, jsonify,
    redirect, session, send_file, url_for
)
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os, io

app = Flask(__name__)
app.secret_key = "wallet_secret_key_2024"

# ─────────────────────────────────────────────
# FX RATE SETUP
# ─────────────────────────────────────────────

def load_fx():
    col_map = {
        "Time Serie":                                       "Date",
        "INDIA - INDIAN RUPEE/US$":                        "INR",
        "EURO AREA - EURO/US$":                            "EUR",
        "UNITED KINGDOM - UNITED KINGDOM POUND/US$":       "GBP",
        "JAPAN - YEN/US$":                                 "JPY",
    }
    raw = pd.read_csv("Foreign_Exchange_Rates.csv")
    df  = raw[list(col_map.keys())].rename(columns=col_map)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = (df.replace("ND", np.nan)
            .apply(pd.to_numeric, errors="coerce")
            .set_index("Date")
            .sort_index()
            .ffill()
            .dropna())
    df["AED"] = 3.6725          # AED is pegged to USD
    return df

fx_df  = load_fx()
latest = fx_df.iloc[-1]
INR_per_USD = latest["INR"]

# Rates expressed as: 1 INR = X foreign
RATES = {
    "INR": 1.0,
    "USD": round(1 / INR_per_USD,                    6),
    "EUR": round(latest["EUR"] / INR_per_USD,        6),
    "GBP": round(latest["GBP"] / INR_per_USD,        6),
    "JPY": round(latest["JPY"] / INR_per_USD,        6),
    "AED": round(latest["AED"] / INR_per_USD,        6),
}

CURRENCY_SYMBOLS = {
    "INR": "₹", "USD": "$", "EUR": "€",
    "GBP": "£", "JPY": "¥", "AED": "د.إ"
}

# ─────────────────────────────────────────────
# WALLET STATE
# ─────────────────────────────────────────────

INITIAL_BALANCE = 45_000.0
balance = INITIAL_BALANCE
transactions: list[dict] = []

RECEIVERS = ["rahul@upi", "sneha@upi", "amit@bank", "neha@paytm"]
TRANSACTION_FEE_PCT = 0.005   # 0.5 %

# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

CREDENTIALS = {"admin": "1234"}

def logged_in():
    return session.get("user") is not None

# ─────────────────────────────────────────────
# ROUTES — AUTH
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("wallet") if logged_in() else url_for("login_page"))

@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        user = request.form.get("username", "").strip()
        pwd  = request.form.get("password", "")
        if CREDENTIALS.get(user) == pwd:
            session["user"] = user
            return redirect(url_for("wallet"))
        return render_template("login.html", error="Invalid username or password.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))

# ─────────────────────────────────────────────
# ROUTES — WALLET
# ─────────────────────────────────────────────

@app.route("/wallet")
def wallet():
    if not logged_in():
        return redirect(url_for("login_page"))
    return render_template(
        "index.html",
        balance=balance,
        receivers=RECEIVERS,
        transactions=transactions[-10:][::-1],  # last 10, newest first
        currency_symbols=CURRENCY_SYMBOLS,
    )

# ─────────────────────────────────────────────
# ROUTES — SEND / RECEIVE
# ─────────────────────────────────────────────

@app.route("/send", methods=["POST"])
def send_money():
    global balance
    if not logged_in():
        return jsonify({"error": "Unauthorized"}), 401

    data     = request.get_json(force=True)
    amount   = float(data.get("amount", 0))
    receiver = data.get("receiver", "")

    if amount <= 0:
        return jsonify({"status": "FAILED", "message": "Amount must be positive", "balance": balance})

    if balance >= amount:
        balance -= amount
        status  = "SUCCESS"
        message = f"₹{amount:,.2f} sent to {receiver}"
    else:
        status  = "FAILED"
        message = "Insufficient balance"

    transactions.append({
        "id":       f"TXN{1000 + len(transactions)}",
        "type":     "Sent",
        "party":    receiver,
        "amount":   amount,
        "status":   status,
        "balance":  balance,
    })

    return jsonify({"status": status, "message": message, "balance": round(balance, 2)})


@app.route("/receive", methods=["POST"])
def receive_money():
    global balance
    if not logged_in():
        return jsonify({"error": "Unauthorized"}), 401

    data   = request.get_json(force=True)
    amount = float(data.get("amount", 0))

    if amount <= 0:
        return jsonify({"status": "FAILED", "message": "Amount must be positive", "balance": balance})

    balance += amount

    transactions.append({
        "id":      f"TXN{1000 + len(transactions)}",
        "type":    "Received",
        "party":   "Self",
        "amount":  amount,
        "status":  "SUCCESS",
        "balance": balance,
    })

    return jsonify({"status": "SUCCESS", "balance": round(balance, 2)})

# ─────────────────────────────────────────────
# ROUTES — CURRENCY CONVERTER
# ─────────────────────────────────────────────

@app.route("/convert", methods=["POST"])
def convert_currency():
    if not logged_in():
        return jsonify({"error": "Unauthorized"}), 401

    data     = request.get_json(force=True)
    amount   = float(data.get("amount", 0))
    from_cur = data.get("from", "INR")
    to_cur   = data.get("to",   "USD")

    if from_cur not in RATES or to_cur not in RATES:
        return jsonify({"error": "Unsupported currency"}), 400

    # Convert via INR as base
    inr_amount  = amount / RATES[from_cur]
    raw_result  = inr_amount * RATES[to_cur]
    fee         = raw_result * TRANSACTION_FEE_PCT
    final       = raw_result - fee

    return jsonify({
        "raw":    round(raw_result, 4),
        "fee":    round(fee, 4),
        "final":  round(final, 4),
        "symbol": CURRENCY_SYMBOLS.get(to_cur, ""),
    })

# ─────────────────────────────────────────────
# ROUTES — EXPORT
# ─────────────────────────────────────────────

@app.route("/export")
def export_excel():
    if not logged_in():
        return redirect(url_for("login_page"))

    if not transactions:
        return "No transactions to export.", 400

    df_txn = pd.DataFrame(transactions)
    buf    = io.BytesIO()
    df_txn.to_excel(buf, index=False)
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name="transactions.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

# ─────────────────────────────────────────────
# ROUTES — DASHBOARD
# ─────────────────────────────────────────────

@app.route("/dashboard")
def dashboard():
    if not logged_in():
        return redirect(url_for("login_page"))
    generate_charts()
    return render_template("dashboard.html", transactions=transactions)

def generate_charts():
    os.makedirs("static", exist_ok=True)

    plt.style.use("dark_background")

    if not transactions:
        return

    txn_df = pd.DataFrame(transactions)

    # Transaction type bar chart
    fig, ax = plt.subplots(figsize=(7, 4))
    counts = txn_df["type"].value_counts()
    colors = ["#00d4aa" if t == "Received" else "#ff6b6b" for t in counts.index]
    counts.plot(kind="bar", ax=ax, color=colors, edgecolor="none")
    ax.set_title("Transaction Count by Type", color="#e0e0e0", fontsize=13, pad=12)
    ax.set_facecolor("#1a1a2e")
    fig.patch.set_facecolor("#1a1a2e")
    ax.tick_params(colors="#aaaaaa", rotation=0)
    ax.spines[:].set_visible(False)
    ax.set_ylabel("Count", color="#aaaaaa")
    fig.tight_layout()
    fig.savefig("static/txn_chart.png", dpi=120)
    plt.close(fig)

    # Balance history line chart
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(txn_df["balance"], color="#00d4aa", linewidth=2)
    ax.fill_between(range(len(txn_df)), txn_df["balance"], alpha=0.15, color="#00d4aa")
    ax.set_title("Balance Over Time", color="#e0e0e0", fontsize=13, pad=12)
    ax.set_facecolor("#1a1a2e")
    fig.patch.set_facecolor("#1a1a2e")
    ax.tick_params(colors="#aaaaaa")
    ax.spines[:].set_visible(False)
    ax.set_ylabel("Balance (₹)", color="#aaaaaa")
    ax.set_xlabel("Transaction #", color="#aaaaaa")
    fig.tight_layout()
    fig.savefig("static/balance_chart.png", dpi=120)
    plt.close(fig)

# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True)