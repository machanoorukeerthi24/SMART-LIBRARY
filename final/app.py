from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from email.message import EmailMessage
import smtplib
import os
import random
import secrets
import numpy as np
import pickle

# --- UNIVERSAL ADMIN CONFIG (Guaranteed Access) ---
UNIVERSAL_ADMIN_EMAIL = 'deploy@admin.com'
UNIVERSAL_ADMIN_PASSWORD = 'admin123'
# -------------------------------------------------

app = Flask(__name__)

app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'a_super_secret_fallback_key_that_should_be_changed_in_prod')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.root_path, 'instance', 'library.db')
db = SQLAlchemy(app)

# Add a teardown function to close the session and release the lock
@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()

class Admin(db.Model):
    email = db.Column(db.String(50), primary_key=True)
    password = db.Column(db.String(256), nullable=False)


class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    author = db.Column(db.String(50), nullable=False)
    available_copies = db.Column(db.Integer, default=1)

class Student(db.Model):
    regno = db.Column(db.String(20), primary_key=True)
    email = db.Column(db.String(50), nullable=False)
    password = db.Column(db.String(256), nullable=True)

class BorrowedBook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    regno = db.Column(db.String(20), nullable=False)
    book_name = db.Column(db.String(100), nullable=False)
    borrow_date = db.Column(db.Date, default=datetime.today)
    due_date = db.Column(db.Date)
    actual_return_date = db.Column(db.Date, nullable=True)

class PasswordResetRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    regno = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='pending')
    token = db.Column(db.String(100), unique=True, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    regno = db.Column(db.String(20), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    reserved_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='active')

    book = db.relationship('Book', backref=db.backref('reservations', lazy=True))

class BookRating(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    regno = db.Column(db.String(20), db.ForeignKey('student.regno'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5 rating
    review = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    book = db.relationship('Book', backref=db.backref('ratings', lazy=True))
    student = db.relationship('Student', backref=db.backref('ratings', lazy=True))

class Wishlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    regno = db.Column(db.String(20), db.ForeignKey('student.regno'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    book = db.relationship('Book', backref=db.backref('wishlists', lazy=True))
    student = db.relationship('Student', backref=db.backref('wishlists', lazy=True))

class Fine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    regno = db.Column(db.String(20), db.ForeignKey('student.regno'), nullable=False)
    borrowed_book_id = db.Column(db.Integer, db.ForeignKey('borrowed_book.id'), nullable=False)
    amount = db.Column(db.Float, default=0.0)
    due_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    status = db.Column(db.String(20), default='active')  # active, paid, waived
    
    student = db.relationship('Student', backref=db.backref('fines', lazy=True))
    borrowed_book = db.relationship('BorrowedBook', backref=db.backref('fines', lazy=True))

class FinePayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fine_id = db.Column(db.Integer, db.ForeignKey('fine.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_date = db.Column(db.DateTime, default=datetime.utcnow)
    payment_method = db.Column(db.String(50), default='online')
    transaction_id = db.Column(db.String(100), unique=True, nullable=True)
    status = db.Column(db.String(20), default='completed')  # completed, pending, failed
    
    fine = db.relationship('Fine', backref=db.backref('payments', lazy=True))

class Following(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    follower_regno = db.Column(db.String(20), db.ForeignKey('student.regno'), nullable=False)
    followed_regno = db.Column(db.String(20), db.ForeignKey('student.regno'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    follower = db.relationship('Student', foreign_keys=[follower_regno], backref='following')
    followed = db.relationship('Student', foreign_keys=[followed_regno], backref='followers')

class OTPAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(50), nullable=False)
    otp_code = db.Column(db.String(6), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resend_count = db.Column(db.Integer, default=0)
    
    def is_resend_allowed(self):
        """Check if resend is allowed (2 minutes cooldown)"""
        return datetime.utcnow() >= self.created_at + timedelta(minutes=2)
    
    def get_resend_time_left(self):
        """Get seconds remaining until resend is allowed"""
        if self.is_resend_allowed():
            return 0
        return int((self.created_at + timedelta(minutes=2) - datetime.utcnow()).total_seconds())
    
    @staticmethod
    def get_attempts_in_last_hour(email):
        """Get number of OTP attempts in the last hour for an email"""
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        return OTPAttempt.query.filter(
            OTPAttempt.email == email,
            OTPAttempt.created_at >= one_hour_ago
        ).count()
    
    @staticmethod
    def get_latest_attempt(email):
        """Get the latest OTP attempt for an email"""
        return OTPAttempt.query.filter_by(email=email).order_by(OTPAttempt.created_at.desc()).first()


try:
    model = pickle.load(open('model.pkl', 'rb'))
except FileNotFoundError:
    print("Warning: model.pkl not found. ML prediction feature will be disabled.")
    model = None

def send_email(to, subject, body):
    sender = os.environ.get('EMAIL_SENDER', 'your_email@gmail.com')
    password = os.environ.get('EMAIL_PASSWORD')
    
    if not sender or not password:
        print("Email sender or password not configured. Skipping email.")
        return

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = to
    msg.set_content(body)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
    except Exception as e:
        print(f"Failed to send email to {to}: {e}")

def flash_errors(form):
    """Flashes form errors."""
    for field, errors in form.errors.items():
        for error in errors:
            flash(u"Error in the %s field - %s" % (
                getattr(form, field).label.text, error), 'error')

def admin_login_required(f):
    def wrap(*args, **kwargs):
        if 'admin_email' not in session:
            flash('Please log in as admin first.', 'error')
            return redirect(url_for('admin'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

def super_admin_required(f):
    def wrap(*args, **kwargs):
        if 'admin_email' not in session or not session.get('is_super_admin', False):
            flash('Unauthorized access. Super admin privileges required.', 'error')
            return redirect(url_for('admin_panel'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

# --- SUPER ADMIN EMAIL LIST (UPDATED) ---
SUPER_ADMIN_EMAILS = [
    '23091A3251@rgmcet.edu.in', 
    '23091A3259@rgmcet.edu.in',
    UNIVERSAL_ADMIN_EMAIL # Added the universal admin email
]
# ----------------------------------------

@app.route('/')
def index():
    return render_template('index.html', now=datetime.now())

@app.route('/student')
def student():
    return render_template('student.html', now=datetime.now())

@app.route('/student_login', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        regno = request.form['regno'].strip()
        password = request.form['password']
        student = Student.query.filter_by(regno=regno).first()

        if student and check_password_hash(student.password, password):
            session['regno'] = student.regno
            flash('Login successful!', 'success')
            return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid registration number or password.', 'error')
            return redirect(url_for('student_login'))
    return render_template('student_login.html', now=datetime.now())

@app.route('/student_signup', methods=['GET', 'POST'])
def student_signup():
    if request.method == 'POST':
        regno = request.form['regno'].strip()
        email = request.form['email'].strip()
        password = request.form['password']

        # Validation checks
        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'error')
            return redirect(url_for('student_signup'))

        if not email.endswith('@rgmcet.edu.in'):
            flash('Email must end with @rgmcet.edu.in', 'error')
            return redirect(url_for('student_signup'))

        existing_student = Student.query.filter_by(regno=regno).first()
        if existing_student:
            flash('Registration number already exists. Please log in.', 'error')
            return redirect(url_for('student_login'))
        
        # Check if email has reached OTP limit (3 per hour)
        attempts_in_hour = OTPAttempt.get_attempts_in_last_hour(email)
        if attempts_in_hour >= 3:
            flash('Maximum OTP attempts reached for this email. Please try again later.', 'error')
            return redirect(url_for('student_signup'))
        
        # Store data in session and send OTP
        otp = str(random.randint(100000, 999999))
        session['otp'] = otp
        session['regno'] = regno
        session['email'] = email
        session['password'] = password
        
        # Save OTP attempt to database
        otp_attempt = OTPAttempt(
            email=email,
            otp_code=otp,
            created_at=datetime.utcnow(),
            resend_count=0
        )
        db.session.add(otp_attempt)
        db.session.commit()
        
        send_email(email, "Your OTP Code", f"Your OTP code is: {otp}")
        flash('OTP sent to your email. Please enter the OTP to verify.')
        return redirect(url_for('verify_otp'))

    return render_template('student_signup.html', now=datetime.now())

@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    if request.method == 'POST':
        # Handle resend OTP request
        if 'resend_otp' in request.form:
            email = session.get('email')
            if not email:
                flash('Session expired. Please start the signup process again.', 'error')
                return redirect(url_for('student_signup'))
            
            # Check if email has reached OTP limit (3 per hour)
            attempts_in_hour = OTPAttempt.get_attempts_in_last_hour(email)
            if attempts_in_hour >= 3:
                flash('Maximum OTP attempts reached for this email. Please try again later.', 'error')
                return redirect(url_for('student_signup'))
            
            # Check if resend is allowed (2 minutes cooldown)
            latest_attempt = OTPAttempt.get_latest_attempt(email)
            if latest_attempt and not latest_attempt.is_resend_allowed():
                time_left = latest_attempt.get_resend_time_left()
                flash(f'Please wait {time_left} seconds before requesting another OTP.', 'warning')
                return render_template('otp_verification.html', now=datetime.now(), time_left=time_left)
            
            # Generate new OTP
            otp = str(random.randint(100000, 999999))
            session['otp'] = otp
            
            # Save new OTP attempt to database
            otp_attempt = OTPAttempt(
                email=email,
                otp_code=otp,
                created_at=datetime.utcnow(),
                resend_count=(latest_attempt.resend_count + 1) if latest_attempt else 1
            )
            db.session.add(otp_attempt)
            db.session.commit()
            
            send_email(email, "Your OTP Code", f"Your OTP code is: {otp}")
            flash('New OTP sent to your email.', 'success')
            return render_template('otp_verification.html', now=datetime.now(), time_left=120)
        
        # Handle OTP verification
        user_otp = request.form['otp']
        if 'otp' in session and user_otp == session['otp']:
            regno = session.get('regno')
            email = session.get('email')
            password = session.get('password')

            # Create the student account
            hashed_password = generate_password_hash(password)
            new_student = Student(regno=regno, email=email, password=hashed_password)
            db.session.add(new_student)
            db.session.commit() # This commit is crucial

            # Clear session data
            session.pop('otp', None)
            session.pop('regno', None)
            session.pop('email', None)
            session.pop('password', None)

            flash('OTP verified successfully! Account created. Please log in now.', 'success')
            return redirect(url_for('student_login'))
        else:
            flash('Invalid OTP. Please try again.')
            # Get time left for resend
            email = session.get('email')
            time_left = 0
            if email:
                latest_attempt = OTPAttempt.get_latest_attempt(email)
                if latest_attempt:
                    time_left = latest_attempt.get_resend_time_left()
            return render_template('otp_verification.html', now=datetime.now(), time_left=time_left)
    
    # Ensure all required session variables are present before rendering the OTP form
    if 'regno' not in session or 'otp' not in session:
        flash('Please start the signup process again.', 'error')
        return redirect(url_for('student_signup'))

    # Get time left for resend
    email = session.get('email')
    time_left = 0
    if email:
        latest_attempt = OTPAttempt.get_latest_attempt(email)
        if latest_attempt:
            time_left = latest_attempt.get_resend_time_left()
    
    return render_template('otp_verification.html', now=datetime.now(), time_left=time_left)

@app.route('/student_dashboard')
def student_dashboard():
    if 'regno' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('student_login'))
    regno = session['regno']

    # Calculate fines for the student
    # calculate_fine_for_student(regno)  # Commented out to prevent overwriting paid amounts

    # Get book recommendations based on borrowing history
    recommended_books = get_book_recommendations(regno)
    
    # Get fine information
    active_fines = Fine.query.filter_by(regno=regno, status='active').all()
    total_fine = sum(fine.amount for fine in active_fines)
    can_borrow = can_student_borrow_books(regno)
    
    return render_template('student_dashboard.html', 
                         regno=regno, 
                         now=datetime.now(), 
                         recommended_books=recommended_books,
                         active_fines=active_fines,
                         total_fine=total_fine,
                         can_borrow=can_borrow)

def get_book_recommendations(regno, limit=5):
    """
    Get book recommendations based on student's borrowing history
    Returns books by the same authors or in similar genres
    """
    # Get student's borrowed books
    borrowed_books = BorrowedBook.query.filter_by(regno=regno).all()
    
    if not borrowed_books:
        # If no borrowing history, return some random popular books
        return Book.query.order_by(db.func.random()).limit(limit).all()
    
    # Get authors of borrowed books
    borrowed_authors = []
    for borrowed in borrowed_books:
        book = Book.query.filter_by(title=borrowed.book_name).first()
        if book and book.author not in borrowed_authors:
            borrowed_authors.append(book.author)
    
    # Find books by the same authors that the student hasn't borrowed yet
    recommended_books = []
    if borrowed_authors:
        # Get books by the same authors
        author_books = Book.query.filter(
            Book.author.in_(borrowed_authors),
            Book.title.notin_([b.book_name for b in borrowed_books])
        ).limit(5).all()
        recommended_books.extend(author_books)
    
    # If we don't have enough recommendations, add some popular books
    if len(recommended_books) < limit:
        additional_books = Book.query.filter(
            Book.title.notin_([b.book_name for b in borrowed_books]),
            Book.id.notin_([b.id for b in recommended_books]) if recommended_books else True
        ).order_by(db.func.random()).limit(limit - len(recommended_books)).all()
        recommended_books.extend(additional_books)
    
    return recommended_books[:5]

@app.route('/borrowing_history')
def borrowing_history():
    if 'regno' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('student_login'))
    regno = session['regno']
    books = BorrowedBook.query.filter_by(regno=regno).order_by(BorrowedBook.borrow_date.desc()).all()
    
    # Get ratings for each book
    book_ratings = {}
    for book in books:
        if book.actual_return_date:  # Only get ratings for returned books
            book_obj = Book.query.filter_by(title=book.book_name).first()
            if book_obj:
                existing_rating = BookRating.query.filter_by(regno=regno, book_id=book_obj.id).first()
                if existing_rating:
                    book_ratings[book.id] = {
                        'rating': existing_rating.rating,
                        'review': existing_rating.review
                    }
    
    return render_template('borrowing_history.html', books=books, regno=regno, 
                          today_date=datetime.today().date(), now=datetime.now(), 
                          book_ratings=book_ratings)

@app.route('/reading_analytics')
def reading_analytics():
    if 'regno' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('student_login'))
    
    regno = session['regno']
    
    # Get all borrowed books for this student
    borrowed_books = BorrowedBook.query.filter_by(regno=regno).all()
    
    # Calculate reading statistics
    total_books_borrowed = len(borrowed_books)
    books_returned = [book for book in borrowed_books if book.actual_return_date is not None]
    books_currently_borrowed = [book for book in borrowed_books if book.actual_return_date is None]
    
    # Calculate on-time returns vs late returns
    on_time_returns = 0
    late_returns = 0
    total_days_late = 0
    
    for book in books_returned:
        if book.actual_return_date <= book.due_date:
            on_time_returns += 1
        else:
            late_returns += 1
            days_late = (book.actual_return_date - book.due_date).days
            total_days_late += days_late
    
    # Calculate average days late
    average_days_late = total_days_late / late_returns if late_returns > 0 else 0
    
    # Get favorite authors
    author_counts = {}
    for book in borrowed_books:
        book_obj = Book.query.filter_by(title=book.book_name).first()
        if book_obj:
            author = book_obj.author
            if author in author_counts:
                author_counts[author] += 1
            else:
                author_counts[author] = 1
    
    # Sort authors by count
    favorite_authors = sorted(author_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # Get books per month (for the last 12 months)
    books_per_month = {}
    current_date = datetime.today()
    
    for i in range(12):
        # Calculate the month and year for each of the last 12 months
        month_date = current_date - timedelta(days=30*i)
        month_key = month_date.strftime('%Y-%m')
        books_per_month[month_key] = 0
    
    # Count books borrowed each month
    for book in borrowed_books:
        month_key = book.borrow_date.strftime('%Y-%m')
        if month_key in books_per_month:
            books_per_month[month_key] += 1
    
    # Sort months chronologically
    sorted_months = sorted(books_per_month.items())
    
    return render_template('reading_analytics.html', 
                          regno=regno,
                          total_books_borrowed=total_books_borrowed,
                          books_returned=len(books_returned),
                          books_currently_borrowed=len(books_currently_borrowed),
                          on_time_returns=on_time_returns,
                          late_returns=late_returns,
                          average_days_late=round(average_days_late, 2),
                          favorite_authors=favorite_authors,
                          books_per_month=sorted_months,
                          now=datetime.now())

@app.route('/social')
def social():
    if 'regno' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('student_login'))
    
    regno = session['regno']
    
    # Get students the current user is following
    following = Following.query.filter_by(follower_regno=regno).all()
    following_regnos = [f.followed_regno for f in following]
    
    # Get students who are following the current user
    followers = Following.query.filter_by(followed_regno=regno).all()
    follower_regnos = [f.follower_regno for f in followers]
    
    # Get all students except the current user
    all_students = Student.query.filter(Student.regno != regno).all()
    
    # Get currently borrowed books for all students
    all_borrowed_books = BorrowedBook.query.filter(
        BorrowedBook.actual_return_date.is_(None)
    ).order_by(BorrowedBook.borrow_date.desc()).all()
    
    # Filter to only show borrowed books from followed students
    followed_borrowed_books = [
        book for book in all_borrowed_books 
        if book.regno in following_regnos
    ]
    
    return render_template('social.html', 
                          regno=regno,
                          all_students=all_students,
                          following_regnos=following_regnos, # Pass following_regnos for template logic
                          followers=followers,
                          borrowed_books=followed_borrowed_books,
                          now=datetime.now())

@app.route('/follow/<string:target_regno>')
def follow(target_regno):
    if 'regno' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('student_login'))
    
    regno = session['regno']
    
    # Check if trying to follow self
    if regno == target_regno:
        flash('You cannot follow yourself.', 'error')
        return redirect(url_for('social'))
    
    # Check if already following
    existing_follow = Following.query.filter_by(
        follower_regno=regno, 
        followed_regno=target_regno
    ).first()
    
    if existing_follow:
        flash('You are already following this student.', 'info')
    else:
        # Create new follow relationship
        new_follow = Following(
            follower_regno=regno,
            followed_regno=target_regno
        )
        db.session.add(new_follow)
        db.session.commit()
        flash(f'You are now following {target_regno}.', 'success')
    
    return redirect(url_for('social'))

@app.route('/unfollow/<string:target_regno>')
def unfollow(target_regno):
    if 'regno' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('student_login'))
    
    regno = session['regno']
    
    # Check if following
    follow_relationship = Following.query.filter_by(
        follower_regno=regno, 
        followed_regno=target_regno
    ).first()
    
    if follow_relationship:
        db.session.delete(follow_relationship)
        db.session.commit()
        flash(f'You have unfollowed {target_regno}.', 'success')
    else:
        flash('You are not following this student.', 'info')
    
    return redirect(url_for('social'))

def get_book_suggestions(regno):
    """
    Get book suggestions based on student's borrowing history
    Returns a list of suggested books
    """
    # Get student's borrowed books
    borrowed_books = BorrowedBook.query.filter_by(regno=regno).all()
    
    if not borrowed_books:
        # If no borrowing history, return some random popular books
        return Book.query.order_by(db.func.random()).limit(5).all()
    
    # Get authors of borrowed books
    borrowed_authors = []
    for borrowed in borrowed_books:
        book = Book.query.filter_by(title=borrowed.book_name).first()
        if book and book.author not in borrowed_authors:
            borrowed_authors.append(book.author)
    
    # Find books by the same authors that the student hasn't borrowed yet
    suggested_books = []
    if borrowed_authors:
        # Get books by the same authors
        author_books = Book.query.filter(
            Book.author.in_(borrowed_authors),
            Book.title.notin_([b.book_name for b in borrowed_books])
        ).limit(5).all()
        suggested_books.extend(author_books)
    
    # If we don't have enough suggestions, add some popular books
    if len(suggested_books) < 5:
        additional_books = Book.query.filter(
            Book.title.notin_([b.book_name for b in borrowed_books]),
            Book.id.notin_([b.id for b in suggested_books]) if suggested_books else True
        ).order_by(db.func.random()).limit(5 - len(suggested_books)).all()
        suggested_books.extend(additional_books)
    
    return suggested_books[:5]


@app.route('/rate_book/<int:borrowed_book_id>', methods=['POST'])
def rate_book(borrowed_book_id):
    if 'regno' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('student_login'))
    
    borrowed_book = BorrowedBook.query.get_or_404(borrowed_book_id)
    
    # Check if the book belongs to the logged-in student
    if borrowed_book.regno != session['regno']:
        flash('You are not authorized to rate this book.', 'error')
        return redirect(url_for('borrowing_history'))
    
    rating = request.form.get('rating', type=int)
    review = request.form.get('review', '').strip()
    
    # Validate rating
    if rating is None or rating < 1 or rating > 5:
        flash('Please provide a valid rating between 1 and 5.', 'error')
        return redirect(url_for('borrowing_history'))
    
    # Get the book object
    book = Book.query.filter_by(title=borrowed_book.book_name).first()
    if not book:
        flash('Book not found.', 'error')
        return redirect(url_for('borrowing_history'))
    
    # Check if the student has already rated this book
    existing_rating = BookRating.query.filter_by(regno=session['regno'], book_id=book.id).first()
    if existing_rating:
        # Update existing rating
        existing_rating.rating = rating
        existing_rating.review = review
        existing_rating.created_at = datetime.utcnow()
    else:
        # Create new rating
        new_rating = BookRating(
            regno=session['regno'],
            book_id=book.id,
            rating=rating,
            review=review
        )
        db.session.add(new_rating)
    
    db.session.commit()
    flash('Thank you for rating this book!', 'success')
    return redirect(url_for('borrowing_history'))

def get_book_average_rating(book_id):
    """Get the average rating for a book"""
    ratings = BookRating.query.filter_by(book_id=book_id).all()
    if not ratings:
        return 0
    return sum(r.rating for r in ratings) / len(ratings)

def get_book_rating_count(book_id):
    """Get the number of ratings for a book"""
    return BookRating.query.filter_by(book_id=book_id).count()

@app.route('/logout')
def logout():
    session.pop('regno', None)
    session.pop('admin_email', None)
    session.pop('is_super_admin', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/check_books', methods=['GET'])
def check_books():
    if 'regno' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('student_login'))

    regno = session['regno']
    books = BorrowedBook.query.filter_by(regno=regno, actual_return_date=None).all()

    if not books:
        flash('No borrowed books found for this student.', 'info')

    return render_template('check_books.html', books=books, regno=regno, now=datetime.now())

@app.route('/search_books')
def search_books():
    if 'regno' not in session:
        flash('Please log in first to search for books.', 'error')
        return redirect(url_for('student_login'))
    regno = session['regno']
    books = Book.query.all()
    return render_template('search_books.html', books=books, regno=regno, now=datetime.now())

@app.route('/search_api')
def search_api():
    # Get query parameters
    term = request.args.get('q', '').strip()
    title_filter = request.args.get('title', '').strip()
    author_filter = request.args.get('author', '').strip()
    sort_by = request.args.get('sort', 'title')
    availability = request.args.get('availability', 'all')
    
    # Build query based on filters
    query = Book.query
    
    # Apply search term filter (for the original search input)
    if term:
        query = query.filter(Book.title.ilike(f"%{term}%") | Book.author.ilike(f"%{term}%"))
    
    # Apply title filter
    if title_filter:
        query = query.filter(Book.title.ilike(f"%{title_filter}%"))
    
    # Apply author filter
    if author_filter:
        query = query.filter(Book.author.ilike(f"%{author_filter}%"))
    
    # Apply availability filter
    if availability == 'available':
        query = query.filter(Book.available_copies > 0)
    elif availability == 'unavailable':
        query = query.filter(Book.available_copies == 0)
    
    # Apply sorting
    if sort_by == 'title':
        query = query.order_by(Book.title.asc())
    elif sort_by == '-title':
        query = query.order_by(Book.title.desc())
    elif sort_by == 'author':
        query = query.order_by(Book.author.asc())
    elif sort_by == '-author':
        query = query.order_by(Book.author.desc())
    elif sort_by == 'available_copies':
        query = query.order_by(Book.available_copies.desc())
    elif sort_by == '-available_copies':
        query = query.order_by(Book.available_copies.asc())
    
    books = query.all()
    results = [{"id": b.id, "title": b.title, "author": b.author, "available_copies": b.available_copies} for b in books]
    return {"books": results}

@app.route('/borrow_book/<int:book_id>', methods=['GET', 'POST'])
def borrow_book(book_id):
    book = Book.query.get_or_404(book_id)
    if 'regno' not in session:
        flash('Please log in first to borrow a book.', 'error')
        return redirect(url_for('student_login'))

    regno = session['regno']

    active_reservations = Reservation.query.filter_by(book_id=book.id, status='active').order_by(Reservation.reserved_at).all()
    if active_reservations:
        if active_reservations[0].regno != regno:
            flash('This book is reserved by another student. You cannot borrow it now.', 'error')
            return redirect(url_for('search_books'))
        else:
            active_reservations[0].status = 'fulfilled'
            db.session.commit()

    if book.available_copies == 0:
        flash('Book not available for borrowing.', 'error')
        return redirect(url_for('search_books'))

    if request.method == 'POST':
        student = Student.query.filter_by(regno=regno).first()
        if not student:
            flash("Student not found. Please log in again.", 'error')
            session.pop('regno', None)
            return redirect(url_for('student_login'))

        active_borrow = BorrowedBook.query.filter_by(regno=regno, book_name=book.title, actual_return_date=None).first()
        if active_borrow:
            flash("You can borrow only one copy of a specific book at a time.", 'warning')
            return redirect(url_for('student_dashboard'))

        borrow_date = datetime.today().date()
        due_date = borrow_date + timedelta(days=14)

        if model:
            past_borrows = BorrowedBook.query.filter_by(regno=regno).count()
            borrowed_books = BorrowedBook.query.filter_by(regno=regno).all()
            late_return_count = 0
            total_days_late = 0
            for b in borrowed_books:
                if b.actual_return_date and b.due_date and b.actual_return_date > b.due_date:
                    late_return_count += 1
                    total_days_late += (b.actual_return_date - b.due_date).days
            avg_days_late = total_days_late / late_return_count if late_return_count > 0 else 0

            # The ML model expects an array of features (even if just two)
            # The features used in the best_model.pkl file (from a previous file) were: ['borrow_count', 'avg_days_late']
            features = np.array([[past_borrows, avg_days_late]]) 
            try:
                # Assuming the loaded model is a Scikit-learn or Imblearn Pipeline/Model
                prediction = model.predict(features)
                if prediction[0] == 1:
                    flash('Note: Based on your borrowing history, you are likely to return this book late.', 'warning')
            except Exception as e:
                print(f"ML model prediction failed: {e}")
                flash('Warning: Could not predict late return likelihood.', 'warning')

        new_borrow = BorrowedBook(
            regno=regno,
            book_name=book.title,
            borrow_date=borrow_date,
            due_date=due_date
        )
        db.session.add(new_borrow)

        book.available_copies -= 1
        db.session.commit()

        flash(f"Book '{book.title}' borrowed successfully! Due on {due_date.strftime('%Y-%m-%d')}", 'success')
        return redirect(url_for('student_dashboard'))

    return render_template('borrow_book_confirm.html', book=book, regno=regno, now=datetime.now())

@app.route('/reserve_book/<int:book_id>', methods=['GET', 'POST'])
def reserve_book(book_id):
    if 'regno' not in session:
        flash('Please log in first to reserve a book.', 'error')
        return redirect(url_for('student_login'))

    book = Book.query.get_or_404(book_id)
    regno = session['regno']

    existing_reservation = Reservation.query.filter_by(book_id=book.id, regno=regno, status='active').first()
    if existing_reservation:
        # Get student's position in the queue
        all_reservations = Reservation.query.filter_by(book_id=book.id, status='active').order_by(Reservation.reserved_at).all()
        position = all_reservations.index(existing_reservation) + 1
        flash(f'You already have an active reservation for this book. You are #{position} in the queue.', 'info')
        return redirect(url_for('student_dashboard'))

    if request.method == 'POST':
        new_reservation = Reservation(book_id=book.id, regno=regno)
        db.session.add(new_reservation)
        db.session.commit()
        flash(f"You have successfully reserved '{book.title}'. You will be notified when it becomes available.", 'success')
        return redirect(url_for('student_dashboard'))

    # Get current queue position if student already has a reservation
    queue_position = None
    all_reservations = Reservation.query.filter_by(book_id=book.id, status='active').order_by(Reservation.reserved_at).all()
    for i, reservation in enumerate(all_reservations):
        if reservation.regno == regno:
            queue_position = i + 1
            break

    return render_template('reserve_book_confirm.html', book=book, queue_position=queue_position, now=datetime.now())

@app.route('/my_reservations')
def my_reservations():
    if 'regno' not in session:
        flash('Please log in first to view your reservations.', 'error')
        return redirect(url_for('student_login'))

    regno = session['regno']
    reservations = Reservation.query.filter_by(regno=regno).order_by(Reservation.reserved_at.desc()).all()
    return render_template('my_reservations.html', reservations=reservations, now=datetime.now())

@app.route('/wishlist')
def wishlist():
    if 'regno' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('student_login'))
    
    regno = session['regno']
    wishlist_items = Wishlist.query.filter_by(regno=regno).all()
    
    # Get book details for each wishlist item
    wishlist_books = []
    for item in wishlist_items:
        book = Book.query.get(item.book_id)
        if book:
            # Check if book is available
            is_available = book.available_copies > 0
            
            # Check if student has already reserved this book
            is_reserved = Reservation.query.filter_by(
                regno=regno, 
                book_id=book.id, 
                status='active'
            ).first() is not None
            
            wishlist_books.append({
                'item': item,
                'book': book,
                'is_available': is_available,
                'is_reserved': is_reserved
            })
    
    return render_template('wishlist.html', wishlist_books=wishlist_books, regno=regno, now=datetime.now())

@app.route('/add_to_wishlist/<int:book_id>')
def add_to_wishlist(book_id):
    if 'regno' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('student_login'))
    
    regno = session['regno']
    book = Book.query.get_or_404(book_id)
    
    # Check if book is already in wishlist
    existing_wishlist_item = Wishlist.query.filter_by(regno=regno, book_id=book_id).first()
    if existing_wishlist_item:
        flash(f"'{book.title}' is already in your wishlist.", 'info')
    else:
        # Add book to wishlist
        wishlist_item = Wishlist(regno=regno, book_id=book_id)
        db.session.add(wishlist_item)
        db.session.commit()
        flash(f"Added '{book.title}' to your wishlist.", 'success')
    
    return redirect(url_for('search_books'))

@app.route('/remove_from_wishlist/<int:wishlist_item_id>')
def remove_from_wishlist(wishlist_item_id):
    if 'regno' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('student_login'))
    
    regno = session['regno']
    wishlist_item = Wishlist.query.get_or_404(wishlist_item_id)
    
    # Check if the wishlist item belongs to the logged-in student
    if wishlist_item.regno != regno:
        flash('You are not authorized to remove this item from wishlist.', 'error')
        return redirect(url_for('wishlist'))
    
    # Remove item from wishlist
    db.session.delete(wishlist_item)
    db.session.commit()
    flash('Removed from wishlist.', 'success')
    
    return redirect(url_for('wishlist'))

@app.route('/forget_password', methods=['GET', 'POST'])
def forget_password():
    if request.method == 'POST':
        regno = request.form['regno'].strip()
        student = Student.query.filter_by(regno=regno).first()
        if not student:
            flash('Registration number not found.', 'error')
            return redirect(url_for('forget_password'))

        existing_request = PasswordResetRequest.query.filter_by(regno=regno, status='pending').first()
        if existing_request:
            if existing_request.expires_at and existing_request.expires_at > datetime.now():
                flash('You already have a pending password reset request. Please check your email.', 'info')
                return redirect(url_for('student_login'))
            else:
                db.session.delete(existing_request)
                db.session.commit()
                flash('Your previous password reset link expired. Please submit a new request.', 'warning')
                return redirect(url_for('forget_password'))

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(hours=1)

        new_request = PasswordResetRequest(regno=regno, status='pending', token=token, expires_at=expires_at)
        db.session.add(new_request)
        db.session.commit()
        
        reset_link = url_for('reset_password_with_token', token=token, _external=True)
        subject = "Password Reset Request for Library System"
        body = f"""
Dear {student.regno},

You have requested a password reset for your library account.
Please click on the following link to reset your password:
{reset_link}

This link will expire in 1 hour. If you did not request this, please ignore this email.

Thank you,
Library Management Team
        """
        send_email(student.email, subject, body)
        
        flash('Password reset link sent to your registered email. Please check your inbox.', 'info')
        return redirect(url_for('student_login'))

    return render_template('forget_password.html', now=datetime.now())

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password_with_token(token):
    reset_request = PasswordResetRequest.query.filter_by(token=token, status='pending').first()

    if not reset_request or (reset_request.expires_at and reset_request.expires_at < datetime.now()):
        flash('Invalid or expired password reset link.', 'error')
        return redirect(url_for('forget_password'))

    student = Student.query.filter_by(regno=reset_request.regno).first()
    if not student:
        flash('Student not found for this reset request.', 'error')
        return redirect(url_for('forget_password'))

    if request.method == 'POST':
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        if new_password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('reset_password.html', token=token, now=datetime.now())

        if len(new_password) < 8:
            flash('New password must be at least 8 characters long.', 'error')
            return render_template('reset_password.html', token=token, now=datetime.now())

        student.password = generate_password_hash(new_password)
        reset_request.status = 'completed'
        reset_request.token = None
        reset_request.expires_at = None
        db.session.commit()

        flash('Your password has been reset successfully. Please log in with your new password.', 'success')
        return redirect(url_for('student_login'))

    return render_template('reset_password.html', token=token, now=datetime.now())

@app.route('/return', methods=['GET'])
def return_book():
    if 'regno' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('student_login'))

    regno = session['regno']
    books = BorrowedBook.query.filter_by(regno=regno, actual_return_date=None).all()

    if not books:
        flash('No borrowed books found for this student to return.', 'info')

    return render_template('return.html', books=books, regno=regno, now=datetime.now())

# --- CORRECTED RETURN LOGIC (BLOCKS RETURN IF FINE IS ACTIVE) ---
@app.route('/return_confirm/<int:borrowed_book_id>', methods=['POST'])
def return_confirm(borrowed_book_id):
    if 'regno' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('student_login'))

    regno = session['regno']
    
    # Recalculate fines to get the most accurate total
    calculate_fine_for_student(regno)
    total_fine = get_student_total_fine(regno)
    
    if total_fine > 0:
        flash(f'Return blocked: You have an outstanding fine of ₹{total_fine:.2f}. You need to clear your fine before returning your book.', 'error')
        return redirect(url_for('return_book'))

    borrowed_book = BorrowedBook.query.get_or_404(borrowed_book_id)

    if borrowed_book.regno != session['regno']:
        flash('Unauthorized attempt to return a book.', 'error')
        return redirect(url_for('student_dashboard'))

    if borrowed_book.actual_return_date is not None:
        flash('This book has already been returned.', 'warning')
        return redirect(url_for('check_books'))

    borrowed_book.actual_return_date = datetime.today().date()

    book = Book.query.filter_by(title=borrowed_book.book_name).first()
    if book:
        book.available_copies += 1
    else:
        print(f"Warning: Book '{borrowed_book.book_name}' not found in Book table when returning.")

    db.session.commit()
    
    # Final check for fines and status update after successful return
    calculate_fine_for_student(regno) 
    
    flash(f"Book '{borrowed_book.book_name}' returned successfully.", 'success')
    return redirect(url_for('student_dashboard'))
# -------------------------------------------------------------------

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        email = request.form['email'].strip()
        password = request.form['password']

        admin_user = Admin.query.filter_by(email=email).first()
        if admin_user and check_password_hash(admin_user.password, password):
            session['admin_email'] = email
            # --- CRITICAL FIX: Check against the new combined list ---
            session['is_super_admin'] = (email in SUPER_ADMIN_EMAILS)
            # ---------------------------------------------------------
            flash('Admin login successful!', 'success')
            return redirect(url_for('admin_panel'))
        else:
            flash('Invalid admin credentials. Please try again.', 'error')
    return render_template('admin.html', now=datetime.now())

@app.route('/admin_panel')
@admin_login_required
def admin_panel():
    search_query = request.args.get('search', '').strip()
    students = Student.query.all()
    borrowed_books = BorrowedBook.query.filter_by(actual_return_date=None).all()
    if search_query:
        books = Book.query.filter(
            (Book.title.ilike(f'%{search_query}%')) | (Book.author.ilike(f"%{search_query}%"))
        ).all()
    else:
        books = Book.query.all()
    students_dict = {s.regno: s.email for s in students}

    # Get statistics for charts
    total_books = Book.query.count()
    total_borrowed = len(borrowed_books)
    total_overdue = BorrowedBook.query.filter(
        BorrowedBook.due_date < datetime.today().date(), 
        BorrowedBook.actual_return_date.is_(None)
    ).count()
    total_students = len(students)
    
    # Books borrowed per month (for the last 6 months)
    books_per_month = {}
    current_date = datetime.today()
    
    for i in range(6):
        # Calculate the month and year for each of the last 6 months
        month_date = current_date - timedelta(days=30*i)
        month_key = month_date.strftime('%Y-%m')
        books_per_month[month_key] = 0
    
    # Count books borrowed each month
    all_borrowed_books = BorrowedBook.query.all()
    for book in all_borrowed_books:
        month_key = book.borrow_date.strftime('%Y-%m')
        if month_key in books_per_month:
            books_per_month[month_key] += 1
    
    # Sort months chronologically
    sorted_months = sorted(books_per_month.items())

    current_admin_email = session.get('admin_email')
    is_super_admin = session.get('is_super_admin', False)

    return render_template('admin_panel.html', 
                          students=students, 
                          borrowed_books=borrowed_books, 
                          books=books, 
                          students_dict=students_dict, 
                          current_admin_email=current_admin_email, 
                          is_super_admin=is_super_admin, 
                          total_books=total_books,
                          total_borrowed=total_borrowed,
                          total_overdue=total_overdue,
                          total_students=total_students,
                          books_per_month=sorted_months,
                          now=datetime.now())

@app.route('/admin_password_resets')
@admin_login_required
def admin_password_resets():
    requests = PasswordResetRequest.query.filter_by(status='pending').all()
    return render_template('admin_password_resets.html', requests=requests, now=datetime.now())

@app.route('/admin_reservations')
@admin_login_required
def admin_reservations():
    reservations = Reservation.query.order_by(Reservation.reserved_at.desc()).all()
    return render_template('admin_reservations.html', reservations=reservations, now=datetime.now())

@app.route('/admin_stats')
@admin_login_required
def admin_stats():
    total_books = Book.query.count()
    total_borrowed = BorrowedBook.query.filter_by(actual_return_date=None).count()
    total_overdue = BorrowedBook.query.filter(BorrowedBook.due_date < datetime.today().date(), BorrowedBook.actual_return_date==None).count()
    total_students = Student.query.count()

    data = {
        'total_books': total_books,
        'total_borrowed': total_borrowed,
        'total_overdue': total_overdue,
        'total_students': total_students
    }
    return jsonify(data)

@app.route('/library_statistics')
@admin_login_required
def library_statistics():
    return render_template('library_statistics.html', now=datetime.now())

@app.route('/borrowed_books')
@admin_login_required
def borrowed_books():
    borrowed_books = BorrowedBook.query.filter_by(actual_return_date=None).all()
    students = Student.query.all()
    students_dict = {s.regno: s.email for s in students}
    return render_template('borrowed_books.html', borrowed_books=borrowed_books, students_dict=students_dict, now=datetime.now())

@app.route('/registered_students')
@admin_login_required
def registered_students():
    students = Student.query.all()
    return render_template('registered_students.html', students=students, now=datetime.now())

@app.route('/delete_student_confirm/<regno>', methods=['GET', 'POST'])
@admin_login_required
def delete_student_confirm(regno):
    student = Student.query.filter_by(regno=regno).first()
    if not student:
        flash(f"Student with registration number {regno} not found.", 'error')
        return redirect(url_for('registered_students'))

    active_borrowed_books = BorrowedBook.query.filter_by(regno=regno, actual_return_date=None).all()

    if request.method == 'POST':
        # This part handles the POST request from the confirmation page
        confirm = request.form.get('confirm')
        if confirm == 'yes' or confirm is None:
            # Delete active borrowed books first
            for book in active_borrowed_books:
                db.session.delete(book)
            # Now delete the student
            db.session.delete(student)
            db.session.commit()
            flash(f"Student {regno} and their active borrowed books have been deleted.", 'success')
        else:
            flash("Deletion cancelled.", 'info')
        return redirect(url_for('registered_students'))
    
    # This part handles the GET request from the registered_students table
    if active_borrowed_books:
        # If there are active books, show the confirmation page
        return render_template('delete_student_confirm.html', student=student, active_books=active_borrowed_books)
    else:
        # No active books, proceed with direct deletion
        db.session.delete(student)
        db.session.commit()
        flash(f"Student {regno} has been deleted.", 'success')
        return redirect(url_for('registered_students'))

@app.route('/all_books')
@admin_login_required
def all_books():
    books = Book.query.all()
    return render_template('all_books.html', books=books, now=datetime.now())

@app.route('/approve_password_reset/<string:regno>', methods=['POST'])
@admin_login_required
def approve_password_reset(regno):
    reset_request = PasswordResetRequest.query.filter_by(regno=regno, status='pending').first_or_404()
    student = Student.query.filter_by(regno=regno).first_or_404()

    default_password = secrets.token_urlsafe(10)
    student.password = generate_password_hash(default_password)
    reset_request.status = 'approved'
    reset_request.token = None
    reset_request.expires_at = None #TODO add more error handling
    db.session.commit()

    subject = "Your Library Account Password Has Been Reset"
    body = f"""
Dear {student.regno},

Your password reset request for the library system has been approved by an administrator.
Your temporary password is: {default_password}

Please log in with this temporary password at {url_for('student_login', _external=True)} and change it immediately for security.

Thank you,
Library Management Team
"""
    send_email(student.email, subject, body)

    flash(f"Password reset approved for {regno}. Student notified. Temporary password is '{default_password}'.", 'success')
    return redirect(url_for('admin_password_resets'))

@app.route('/view_record/<regno>')
@admin_login_required
def view_record(regno):
    borrowed_books_history = BorrowedBook.query.filter_by(regno=regno).order_by(BorrowedBook.borrow_date.desc()).all()
    student = Student.query.filter_by(regno=regno).first_or_404()
    return render_template('view_record.html', borrowed_books=borrowed_books_history, student=student, today_date=datetime.today().date(), now=datetime.now())

@app.route('/edit_due/<int:borrowed_book_id>', methods=['GET', 'POST'])
@admin_login_required
def edit_due(borrowed_book_id):
    book = BorrowedBook.query.get_or_404(borrowed_book_id)
    if request.method == 'POST':
        new_due_str = request.form['new_due'].strip()
        try:
            new_due = datetime.strptime(new_due_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", 'error')
            return redirect(url_for('edit_due', borrowed_book_id=borrowed_book_id))

        book.due_date = new_due
        db.session.commit()

        student = Student.query.filter_by(regno=book.regno).first()
        if student and student.email:
            subject = f"Library Book Due Date Updated for '{book.book_name}'"
            body = f"""
Dear {student.regno},

The due date for the book '{book.book_name}' has been updated to {new_due.strftime('%Y-%m-%d')}.
Please return the book by the new due date.

Thank you,
Library Management Team
"""
            send_email(student.email, subject, body)
            flash('Due date updated and notification sent.', 'success')
        else:
            flash('Due date updated, but could not send email (student or email not found).', 'warning')
        return redirect(url_for('admin_panel'))
    return render_template('edit_due.html', book=book, now=datetime.now())

@app.route('/send_reminders')
@admin_login_required
def send_reminders():
    today = datetime.today().date()
    borrowed_books = BorrowedBook.query.filter_by(actual_return_date=None).all()
    reminders_sent = 0

    for book in borrowed_books:
        student = Student.query.filter_by(regno=book.regno).first()
        if not student or not student.email:
            print(f"Skipping reminder for {book.regno}: Student or email not found.")
            continue

        email = student.email
        days_left = (book.due_date - today).days

        subject = None
        body = None

        if days_left < 0:
            subject = '⚠️ Book Return Overdue!'
            body = f"Dear {student.regno},\n\nYour book '{book.book_name}' was due on {book.due_date.strftime('%Y-%m-%d')} and is now overdue. Please return it as soon as possible to avoid penalties.\n\nThank you,\nLibrary Management Team"
        elif days_left <= 2:
            subject = '📖 Book Due Soon Reminder'
            body = f"Dear {student.regno},\n\nReminder: Your book '{book.book_name}' is due on {book.due_date.strftime('%Y-%m-%d')}. Please return it on time to avoid overdue charges.\n\nThank you,\nLibrary Management Team"
        else:
            continue

        if subject and body:
            send_email(email, subject, body)
            reminders_sent += 1
            print(f"Sent reminder to {email} for book {book.book_name}. Days left: {days_left}")

    flash(f"Sent {reminders_sent} reminder emails.", 'info')
    return redirect(url_for('admin_panel'))

@app.route('/add_book', methods=['GET', 'POST'])
@admin_login_required
def add_book():
    if request.method == 'POST':
        title = request.form['title'].strip()
        author = request.form['author'].strip()
        try:
            copies = int(request.form['copies'])
        except ValueError:
            flash("Number of copies must be a valid integer.", 'error')
            return render_template('add_book.html', now=datetime.now())

        if not title or not author or copies <= 0:
            flash("Please provide valid title, author, and at least 1 copy.", 'error')
            return render_template('add_book.html', now=datetime.now())

        existing_book = Book.query.filter_by(title=title, author=author).first()

        if existing_book:
            flash(f"'{title}' by {author} already exists in database. You can increase its copies below.", 'warning')
            return redirect(url_for('update_copies', book_id=existing_book.id))
        else:
            new_book = Book(title=title, author=author, available_copies=copies)
            db.session.add(new_book)
            db.session.commit()
            flash(f"Book '{title}' added successfully!", 'success')
            return redirect(url_for('admin_panel'))

    return render_template('add_book.html', now=datetime.now())

@app.route('/update_copies/<int:book_id>', methods=['GET', 'POST'])
@admin_login_required
def update_copies(book_id):
    book = Book.query.get_or_404(book_id)
    if request.method == 'POST':
        try:
            extra_copies = int(request.form['copies'])
        except ValueError:
            flash("Number of copies must be a valid integer.", 'error')
            return redirect(url_for('update_copies', book_id=book_id))

        if extra_copies <= 0:
            flash("Please enter a positive number of copies to add.", 'error')
            return redirect(url_for('update_copies', book_id=book_id))

        book.available_copies += extra_copies
        db.session.commit()
        flash(f"Updated copies for '{book.title}'. New total: {book.available_copies}", 'success')
        return redirect(url_for('admin_panel'))
    return render_template('update_copies.html', book=book, now=datetime.now())

@app.route('/delete_book/<int:book_id>', methods=['GET', 'POST'])
@admin_login_required
def delete_book(book_id):
    book = Book.query.get_or_404(book_id)

    if request.method == 'POST':
        try:
            copies_to_delete = int(request.form.get('copies_to_delete', 0))
        except ValueError:
            flash("Please enter a valid number of copies to delete.", 'error')
            return redirect(url_for('delete_book', book_id=book_id))

        if copies_to_delete <= 0:
            flash("Please enter a valid number of copies to delete.", 'error')
            return redirect(url_for('delete_book', book_id=book_id))

        if copies_to_delete >= book.available_copies:
            db.session.delete(book)
            flash(f"Deleted all copies of '{book.title}' and removed it from the library.", 'success')
        else:
            book.available_copies -= copies_to_delete
            flash(f"Deleted {copies_to_delete} copies of '{book.title}'. Remaining: {book.available_copies}", 'success')

        db.session.commit()
        return redirect(url_for('admin_panel'))

    return render_template('delete_book_confirm.html', book=book, now=datetime.now())

@app.route('/admin_management')
@admin_login_required
def admin_management():
    admins = Admin.query.all()
    current_admin_email = session.get('admin_email')
    super_admin_emails = SUPER_ADMIN_EMAILS # Use the updated list
    return render_template('admin_management.html', admins=admins, current_admin_email=current_admin_email, super_admin_emails=super_admin_emails, now=datetime.now())

@app.route('/add_admin_post', methods=['POST'])
@admin_login_required
def add_admin_post():
    email = request.form.get('email').strip()
    password = request.form.get('password')

    if not email or not password:
        flash('Email and password are required.', 'error')
        return redirect(url_for('admin_management'))

    existing_admin = Admin.query.filter_by(email=email).first()
    if existing_admin:
        flash('Admin with this email already exists.', 'error')
        return redirect(url_for('admin_management'))

    new_admin = Admin(email=email, password=generate_password_hash(password))
    db.session.add(new_admin)
    db.session.commit()
    flash(f'Admin {email} added successfully.', 'success')
    return redirect(url_for('admin_management'))

@app.route('/delete_admin_post/<email>', methods=['POST'])
@admin_login_required
def delete_admin_post(email):
    if email in SUPER_ADMIN_EMAILS: # Use the updated list
        flash('Cannot delete super admin.', 'error')
        return redirect(url_for('admin_management'))

    admin_to_delete = Admin.query.filter_by(email=email).first()
    if not admin_to_delete:
        flash('Admin not found.', 'error')
        return redirect(url_for('admin_management'))

    db.session.delete(admin_to_delete)
    db.session.commit()
    flash(f'Admin {email} deleted successfully.', 'success')
    return redirect(url_for('admin_management'))

@app.route('/update_admin', methods=['POST'])
@super_admin_required
def update_admin():
    current_email = session.get('admin_email')
    new_email = request.form.get('new_email').strip()
    new_password = request.form.get('new_password')

    if not new_email or not new_password:
        flash('New email and password are required.', 'error')
        return redirect(url_for('admin_management'))

    if new_email != current_email:
        existing_admin = Admin.query.filter_by(email=new_email).first()
        if existing_admin:
            flash('Email already in use by another admin.', 'error')
            return redirect(url_for('admin_management'))

    admin = Admin.query.filter_by(email=current_email).first()
    if admin:
        admin.email = new_email
        admin.password = generate_password_hash(new_password)
        db.session.commit()
        session['admin_email'] = new_email
        flash('Admin details updated successfully.', 'success')
    else:
        flash('Admin not found in database for update.', 'error')

    return redirect(url_for('admin_management'))

# In app.py
@app.route('/my_fines')
def my_fines():
    if 'regno' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('student_login'))

    regno = session['regno']
    today = datetime.today().date()
    
    # 1. Ensure fines are up to date
    calculate_fine_for_student(regno)

    # 2. Query active fines
    active_fines = Fine.query.filter_by(regno=regno, status='active').all()
    
    # 3. Prepare fine_details (FILLED IN)
    fine_details = []
    total_active_fine = 0.0
    for fine in active_fines:
        if fine.amount > 0.01:
            borrowed_book = BorrowedBook.query.get(fine.borrowed_book_id)
            
            # Calculate days overdue
            days_overdue = 0
            if borrowed_book and borrowed_book.due_date < today:
                days_overdue = (today - borrowed_book.due_date).days
            
            fine_details.append({
                'fine': fine,
                'book': borrowed_book,
                'days_overdue': days_overdue,
                'fine_amount': fine.amount
            })
            total_active_fine += fine.amount
    
    # Get the IDs of all fine records for the student
    student_fine_ids = [f.id for f in Fine.query.filter_by(regno=regno).all()]
    
    # 4. Query the FinePayment table for history related to this student's fines
    history_payments = FinePayment.query.filter(
        FinePayment.fine_id.in_(student_fine_ids),
        FinePayment.status == 'completed'
    ).order_by(FinePayment.payment_date.desc()).all()
    
    # 5. Prepare history details
    history_details = []
    for payment in history_payments:
        fine_record = Fine.query.get(payment.fine_id)
        borrowed_book = BorrowedBook.query.get(fine_record.borrowed_book_id) if fine_record else None
        
        if borrowed_book:
            history_details.append({
                'book_name': borrowed_book.book_name,
                'amount_paid': payment.amount,
                'payment_date': payment.payment_date.strftime('%Y-%m-%d'),
                'payment_status': payment.status
            })

    return render_template('my_fines.html',
                           fine_details=fine_details,
                           history_details=history_details,
                           total_active_fine=total_active_fine,
                           regno=regno,
                           now=datetime.now())

@app.route('/my_recommendations')
def my_recommendations():
    if 'regno' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('student_login'))
    regno = session['regno']

    # Calculate fines for the student
    calculate_fine_for_student(regno)

    # Get book recommendations based on borrowing history
    recommended_books = get_book_recommendations(regno)

    # Get fine information
    active_fines = Fine.query.filter_by(regno=regno, status='active').all()
    total_fine = sum(fine.amount for fine in active_fines)
    can_borrow = can_student_borrow_books(regno)

    return render_template('my_recommendations.html',
                         regno=regno,
                         now=datetime.now(),
                         recommended_books=recommended_books,
                         active_fines=active_fines,
                         total_fine=total_fine,
                         can_borrow=can_borrow)

@app.route('/admin_fines', methods=['GET'])
@admin_login_required
def admin_fines():
    search_regno = request.args.get('regno', '').strip()
    
    # Recalculate all fines to ensure data is up-to-date
    calculate_all_fines()

    if search_regno:
        student_record = Student.query.filter_by(regno=search_regno).first()
        if student_record:
            all_fines = Fine.query.filter_by(regno=search_regno).order_by(Fine.created_at.desc()).all()
        else:
            flash(f"No student found with registration number {search_regno}.", 'error')
            all_fines = []
    else:
        student_record = None
        all_fines = Fine.query.order_by(Fine.created_at.desc()).all()

    fine_details = []
    for fine in all_fines:
        borrowed_book = BorrowedBook.query.get(fine.borrowed_book_id)
        fine_details.append({
            'fine': fine,
            'book_name': borrowed_book.book_name if borrowed_book else 'N/A',
            'days_overdue': (datetime.today().date() - borrowed_book.due_date).days if borrowed_book and borrowed_book.due_date < datetime.today().date() else 0
        })

    return render_template('admin_fines.html', 
                           fine_details=fine_details,
                           student_record=student_record,
                           search_regno=search_regno, 
                           now=datetime.now())

# --- CORRECTED PAY FINE LOGIC (DEDUDCTS FINE AND UPDATES DASHBOARD) ---
# In app.py
@app.route('/pay_fine/<int:fine_id>', methods=['GET', 'POST'])
def pay_fine(fine_id):
    if 'regno' not in session:
        flash('Please log in first.', 'error')
        return redirect(url_for('student_login'))

    fine = Fine.query.get_or_404(fine_id)
    if fine.regno != session['regno']:
        flash('Unauthorized.', 'error')
        return redirect(url_for('my_fines'))

    # Calculate minimum payment amount (20% of due)
    min_payment = fine.amount * 0.20

    if request.method == 'POST':
        try:
            pay_amount = float(request.form.get('pay_amount'))
        except (ValueError, TypeError):
            flash('Invalid payment amount.', 'error')
            return redirect(url_for('pay_fine', fine_id=fine_id))

        if pay_amount <= 0:
            flash('Payment amount must be greater than zero.', 'error')
        elif pay_amount < min_payment:
            flash(f'Minimum payment amount is ₹{min_payment:.2f} (20% of due).', 'error')
        elif pay_amount > fine.amount:
            flash('Cannot pay more than the outstanding fine amount.', 'error')
        else:
            # Deduction Logic
            fine.amount -= pay_amount
            
            # Correctly mark as 'paid' if the balance is zero or negligibly small
            if fine.amount <= 0.01:
                fine.amount = 0.0
                fine.status = 'paid' # Status changes from 'active' to 'paid'
            
            # --- CRITICAL FIX: Record the payment in FinePayment table ---
            new_payment = FinePayment(
                fine_id=fine.id,
                amount=pay_amount, # This is the amount that should show in history
                transaction_id=generate_transaction_id()
            )
            db.session.add(new_payment)
            # -----------------------------------------------------------

            db.session.commit()
            
            # Recalculate fines to instantly update the dashboard total
            calculate_fine_for_student(session['regno'])

            flash(f'Successfully paid ₹{pay_amount:.2f}. Your new fine balance is ₹{fine.amount:.2f}.', 'success')
            return redirect(url_for('my_fines'))

    borrowed_book = BorrowedBook.query.get(fine.borrowed_book_id)

    return render_template('pay_fine.html',
                           fine=fine,
                           book_name=borrowed_book.book_name if borrowed_book else 'N/A',
                           min_payment=min_payment,
                           now=datetime.now())
# -------------------------------------------------------------------

# --- CORRECTED FINE CALCULATION LOGIC (PRESERVES PAYMENTS) ---
def calculate_fine_for_student(regno):
    """Calculate and update fines for all overdue books for a student, preserving partial payments."""
    today = datetime.today().date()
    overdue_books = BorrowedBook.query.filter(
        BorrowedBook.regno == regno,
        BorrowedBook.actual_return_date.is_(None),
        BorrowedBook.due_date < today
    ).all()
    
    total_fine = 0
    for book in overdue_books:
        days_overdue = (today - book.due_date).days
        if days_overdue > 0:
            fine_amount = days_overdue * 20  # ₹20 per day per book
            
            # Check if an active fine already exists for this book
            existing_fine = Fine.query.filter_by(
                regno=regno,
                borrowed_book_id=book.id,
                status='active'
            ).first()
            
            if existing_fine:
                # Only increase the existing fine amount if the newly calculated amount 
                # (based on overdue days) is greater than the current balance.
                old_amount = existing_fine.amount
                
                if fine_amount > existing_fine.amount:
                    existing_fine.amount = fine_amount
                    existing_fine.updated_at = datetime.utcnow()

                    # Check if fine crossed threshold for email notification
                    if old_amount < 500 <= fine_amount:
                        send_fine_notification_email(regno, fine_amount)
                    elif int(old_amount / 100) < int(fine_amount / 100):
                        send_fine_notification_email(regno, fine_amount)
                
                # After checking for update, use the existing/updated fine amount for the total
                total_fine += existing_fine.amount

            else:
                # Create new fine
                new_fine = Fine(
                    regno=regno,
                    borrowed_book_id=book.id,
                    amount=fine_amount,
                    due_date=book.due_date
                )
                db.session.add(new_fine)
                
                # Send email for new fine
                if fine_amount >= 500:
                    send_fine_notification_email(regno, fine_amount)
            
                total_fine += fine_amount
    
    # Prune paid fines that were somehow marked active (cleanup)
    for fine in Fine.query.filter_by(regno=regno, status='active').all():
        if fine.amount <= 0.01:
            fine.amount = 0.0
            fine.status = 'paid'
            
    db.session.commit()
    return total_fine
# -------------------------------------------------------------------

def calculate_all_fines():
    """Calculate fines for all students"""
    students = Student.query.all()
    for student in students:
        calculate_fine_for_student(student.regno)

def get_student_total_fine(regno):
    """Get total active fine amount for a student"""
    active_fines = Fine.query.filter_by(regno=regno, status='active').all()
    return sum(fine.amount for fine in active_fines)

def can_student_borrow_books(regno):
    """Check if student can borrow books based on fine amount"""
    total_fine = get_student_total_fine(regno)
    return total_fine < 1000

def send_fine_notification_email(regno, fine_amount):
    """Send email notification for fine amount"""
    student = Student.query.filter_by(regno=regno).first()
    if not student or not student.email:
        return
    
    subject = "Library Fine Notification"
    body = f"""
Dear {student.regno},

You have accumulated a library fine of ₹{fine_amount:.2f}.
Please pay your fine as soon as possible to avoid further restrictions.

If your fine reaches ₹1000, you will not be able to borrow any more books until the fine is paid.

You can pay your fine through the student dashboard.

Thank you,
Library Management Team
"""
    send_email(student.email, subject, body)


def generate_transaction_id():
    """Generate unique transaction ID for payments"""
    return f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(1000, 9999)}"

# --- UPDATED seed_super_admins FOR UNIVERSAL ACCESS ---
def seed_super_admins():
    """Seeds the required Super Admin accounts and the universal access admin."""
    with app.app_context():
        
        # Hardcoded Super Admin accounts (must use the same password for consistency)
        super_admins_data = [
            {'email': '23091A3251@rgmcet.edu.in', 'password': os.environ.get('ADMIN_PASSWORD', 'jk@12345')},
            {'email': '23091A3259@rgmcet.edu.in', 'password': os.environ.get('ADMIN_PASSWORD', 'jk@12345')}
        ]
        
        # Universal Failsafe Admin Account (always uses the fixed password)
        universal_admin_data = {
            'email': UNIVERSAL_ADMIN_EMAIL, 
            'password': UNIVERSAL_ADMIN_PASSWORD
        }
        
        # Add the universal admin to the list to be seeded
        accounts_to_seed = super_admins_data + [universal_admin_data]
        
        for account in accounts_to_seed:
            existing = Admin.query.filter_by(email=account['email']).first()
            if not existing:
                hashed_password = generate_password_hash(account['password'])
                new_admin = Admin(email=account['email'], password=hashed_password)
                db.session.add(new_admin)
        db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        if not os.path.exists('instance'):
            os.makedirs('instance')
        db.create_all() # TODO use migrations instead of create_all
        seed_super_admins()
    app.run(debug=True, use_reloader=False)