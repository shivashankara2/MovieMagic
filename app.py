from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import boto3
from decimal import Decimal
import uuid
import os
from boto3.dynamodb.conditions import Attr

app = Flask(__name__)

# ==============================
# SECURITY & CONFIG
# ==============================

app.secret_key = os.environ.get("SECRET_KEY", "moviemagic_super_secret")

AWS_REGION = "us-east-1"
SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:533266960062:MovieTicketNotifications"

# ==============================
# AWS SERVICES
# ==============================

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
sns = boto3.client("sns", region_name=AWS_REGION)

users_table = dynamodb.Table("MovieMagic_Users")
bookings_table = dynamodb.Table("MovieMagic_Bookings")
movies_table = dynamodb.Table("MovieMagic_Movies")

# ==============================
# HELPER FUNCTION
# ==============================

def replace_decimals(obj):

    if isinstance(obj, list):
        return [replace_decimals(i) for i in obj]

    elif isinstance(obj, dict):
        return {k: replace_decimals(v) for k, v in obj.items()}

    elif isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)

    return obj


def send_email(booking):

    try:

        message = f"""
Hello {booking['user_name']},

Your booking for {booking['movie_name']} is CONFIRMED!

Booking ID : {booking['booking_id']}
Theater    : {booking['theater']}
Date       : {booking['date']}
Time       : {booking['time']}
Seats      : {booking['seats']}
Amount Paid: Rs. {booking['amount_paid']}
Payment ID : {booking['payment_id']}

Enjoy your movie 🎬
MovieMagic Team
"""

        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject="🎟 MovieMagic Ticket Confirmation",
            Message=message
        )

    except Exception as e:
        print("SNS ERROR:", e)

# ==============================
# HOME PAGE
# ==============================

@app.route("/")
def index():
    return render_template("index.html")


# ==============================
# SIGNUP
# ==============================

@app.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        try:

            name = request.form.get("name")
            email = request.form.get("email")
            password_raw = request.form.get("password")

            if not name or not email or not password_raw:
                flash("All fields are required")
                return redirect(url_for("signup"))

            password = generate_password_hash(password_raw)

            response = users_table.get_item(Key={"email": email})

            if "Item" in response:
                flash("Email already registered")
                return redirect(url_for("signup"))

            users_table.put_item(
                Item={
                    "email": email,
                    "name": name,
                    "password": password,
                    "theme": "dark"
                }
            )

            flash("Account created successfully! Please login.")
            return redirect(url_for("login"))

        except Exception as e:
            print("Signup Error:", e)
            flash("Signup failed")

    return render_template("signup.html")


# ==============================
# LOGIN
# ==============================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email")
        password = request.form.get("password")

        if email == "admin@moviemagic.com" and password == "admin123":

            session["user"] = {
                "name": "Administrator",
                "email": email,
                "is_admin": True,
                "theme": "dark"
            }

            return redirect(url_for("dashboard"))

        try:

            response = users_table.get_item(Key={"email": email})

            if "Item" in response:

                user = response["Item"]

                if check_password_hash(user["password"], password):

                    session["user"] = {
                        "name": user["name"],
                        "email": user["email"],
                        "theme": user.get("theme", "dark")
                    }

                    return redirect(url_for("dashboard"))

            flash("Invalid email or password")

        except Exception as e:
            print("Login Error:", e)
            flash("Login failed")

    return render_template("login.html")


# ==============================
# LOGOUT
# ==============================

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("index"))


# ==============================
# DASHBOARD
# ==============================

@app.route("/dashboard")
def dashboard():

    if "user" not in session:
        return redirect(url_for("login"))

    try:

        response = movies_table.scan()
        movies = replace_decimals(response.get("Items", []))

    except Exception:
        movies = []

    return render_template("dashboard.html", movies=movies)


# ==============================
# PROFILE
# ==============================

@app.route("/profile")
def profile():

    if "user" not in session:
        return redirect(url_for("login"))

    try:

        response = users_table.get_item(
            Key={"email": session["user"]["email"]}
        )

        user = response.get("Item", session["user"])

        bookings_response = bookings_table.scan(
            FilterExpression=Attr("booked_by").eq(session["user"]["email"])
        )

        bookings = replace_decimals(bookings_response.get("Items", []))

    except Exception as e:

        print("Profile Error:", e)

        user = session["user"]
        bookings = []

    return render_template("profile.html", user=user, bookings=bookings)


# ==============================
# UPDATE PROFILE
# ==============================

@app.route("/update_profile", methods=["POST"])
def update_profile():

    if "user" not in session:
        return redirect(url_for("login"))

    try:

        email = session["user"]["email"]

        mobile = request.form.get("mobile")
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        birthday = request.form.get("birthday")
        theme = request.form.get("theme")
        gender = request.form.get("gender")
        married = request.form.get("married")

        users_table.update_item(
            Key={"email": email},
            UpdateExpression="""
                SET mobile = :m,
                    first_name = :f,
                    last_name = :l,
                    birthday = :b,
                    theme = :t,
                    gender = :g,
                    married = :mr
            """,
            ExpressionAttributeValues={
                ":m": mobile,
                ":f": first_name,
                ":l": last_name,
                ":b": birthday,
                ":t": theme,
                ":g": gender,
                ":mr": married
            }
        )

        session["user"]["theme"] = theme

        flash("Profile updated successfully")

    except Exception as e:

        print("Update Profile Error:", e)
        flash("Profile update failed")

    return redirect(url_for("profile"))


# ==============================
# MOVIE DETAILS
# ==============================

@app.route("/movie/<movie_id>")
def movie_details(movie_id):

    if "user" not in session:
        return redirect(url_for("login"))

    try:

        response = movies_table.get_item(
            Key={"movie_id": movie_id}
        )

        movie = replace_decimals(response.get("Item"))

        if not movie:
            flash("Movie not found")
            return redirect(url_for("dashboard"))

        return render_template("movie_details.html", movie=movie)

    except Exception:

        flash("Error loading movie")
        return redirect(url_for("dashboard"))


# ==============================
# BOOKING PAGE
# ==============================

@app.route("/booking")
def booking():

    if "user" not in session:
        return redirect(url_for("login"))

    movie = request.args.get("movie")
    theater = request.args.get("theater")
    address = request.args.get("address")
    price = request.args.get("price")

    return render_template(
        "booking.html",
        movie=movie,
        theater=theater,
        address=address,
        price=price
    )


# ==============================
# PAYMENT PAGE
# ==============================

@app.route("/payment", methods=["POST"])
def payment():

    if "user" not in session:
        return redirect(url_for("login"))

    booking_details = {
        "movie": request.form.get("movie"),
        "theater": request.form.get("theater"),
        "address": request.form.get("address"),
        "date": request.form.get("date"),
        "time": request.form.get("time"),
        "seats": request.form.get("seats"),
        "amount": request.form.get("amount")
    }

    return render_template("payment.html", booking_details=booking_details)


# ==============================
# CONFIRM BOOKING
# ==============================

@app.route("/confirm_booking", methods=["POST"])
def confirm_booking():

    if "user" not in session:
        return redirect(url_for("login"))

    try:

        data = request.form

        booking_id = f"MM-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8]}"
        payment_id = f"PAY-{str(uuid.uuid4())[:10].upper()}"

        booking_item = {
            "booking_id": booking_id,
            "movie_name": data.get("movie"),
            "theater": data.get("theater"),
            "date": data.get("date"),
            "time": data.get("time"),
            "seats": data.get("seats"),
            "amount_paid": data.get("amount"),
            "address": data.get("address"),
            "booked_by": session["user"]["email"],
            "user_name": session["user"]["name"],
            "payment_id": payment_id,
            "booking_time": datetime.now().isoformat()
        }

        bookings_table.put_item(Item=booking_item)

        send_email(booking_item)

        return render_template("confirmation.html", booking=booking_item)

    except Exception as e:

        print("Booking Error:", e)

        flash("Booking failed")
        return redirect(url_for("dashboard"))


# ==============================
# RUN APP
# ==============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True) 