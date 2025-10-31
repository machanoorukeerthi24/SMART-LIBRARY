import sqlite3
from datetime import datetime, timedelta

# Connect to the existing database
conn = sqlite3.connect('instance/library.db')
cursor = conn.cursor()

# Insert sample students (if not already present)
sample_students = [
    ('S001', 'user1@example.com', 'password1'),
    ('S002', 'user2@example.com', 'password2'),
    ('S003', 'user3@example.com', 'password3'),
]

for regno, email, password in sample_students:
    cursor.execute("""
        INSERT OR IGNORE INTO student (regno, email, password)
        VALUES (?, ?, ?)
    """, (regno, email, password))

# Insert sample books (if not already present)
sample_books = [
    ('Book1', 'Author1', 3),
    ('Book2', 'Author2', 2),
    ('Book3', 'Author3', 1),
]

for title, author, available_copies in sample_books:
    cursor.execute("""
        INSERT OR IGNORE INTO book (title, author, available_copies)
        VALUES (?, ?, ?)
    """, (title, author, available_copies))

# Insert sample borrowed_book records
today = datetime.now()
sample_borrowed_books = [
    # regno, book_name, borrow_date, due_date, actual_return_date
    ('S001', 'Book1', today - timedelta(days=30), today - timedelta(days=15), today - timedelta(days=10)),  # returned late
    ('S001', 'Book2', today - timedelta(days=20), today - timedelta(days=5), today - timedelta(days=5)),    # returned on time
    ('S002', 'Book3', today - timedelta(days=10), today + timedelta(days=5), None),                        # not returned yet
    ('S003', 'Book1', today - timedelta(days=40), today - timedelta(days=25), today - timedelta(days=20)), # returned late
]

for regno, book_name, borrow_date, due_date, actual_return_date in sample_borrowed_books:
    cursor.execute("""
        INSERT INTO borrowed_book (regno, book_name, borrow_date, due_date, actual_return_date)
        VALUES (?, ?, ?, ?, ?)
    """, (regno, book_name, borrow_date.strftime('%Y-%m-%d'), due_date.strftime('%Y-%m-%d'),
          actual_return_date.strftime('%Y-%m-%d') if actual_return_date else None))

conn.commit()
conn.close()

print("Sample data added successfully without modifying existing data.")
