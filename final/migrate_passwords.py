from app import app, db, Admin, Student # Import from your app.py
from werkzeug.security import generate_password_hash

with app.app_context():
    print("Starting password migration...")

    # Migrate Admin passwords
    admins = Admin.query.all()
    for admin in admins:
        # Only hash if it looks like a plain-text password and not already hashed
        # (A simple heuristic, a real check would be better)
        if len(admin.password) < 60 or not admin.password.startswith('pbkdf2:sha256:'): # Hashed passwords are usually longer
            print(f"Hashing password for admin: {admin.email}")
            admin.password = generate_password_hash(admin.password)
    db.session.commit()
    print("Admin passwords migrated.")

    # Migrate Student passwords
    students = Student.query.all()
    for student in students:
        # Only hash if it looks like a plain-text password
        if student.password and (len(student.password) < 60 or not student.password.startswith('pbkdf2:sha256:')):
            print(f"Hashing password for student: {student.regno}")
            student.password = generate_password_hash(student.password)
    db.session.commit()
    print("Student passwords migrated.")

    print("Password migration complete.")