import sqlite3
from datetime import datetime, timedelta
import random

conn = sqlite3.connect('instance/library.db')
cursor = conn.cursor()

# Generate additional sample students
for i in range(4, 21):
    regno = f'S{str(i).zfill(3)}'
    email = f'user{i}@example.com'
    password = f'password{i}'
    cursor.execute("""
        INSERT OR IGNORE INTO student (regno, email, password)
        VALUES (?, ?, ?)
    """, (regno, email, password))

# Generate additional sample books
for i in range(4, 21):
    title = f'Book{i}'
    author = f'Author{i}'
    available_copies = random.randint(1, 5)
    cursor.execute("""
        INSERT OR IGNORE INTO book (title, author, available_copies)
        VALUES (?, ?, ?)
    """, (title, author, available_copies))

# Generate additional borrowed_book records
today = datetime.now()
student_regnos = [f'S{str(i).zfill(3)}' for i in range(1, 21)]
book_titles = [f'Book{i}' for i in range(1, 21)]

for _ in range(50):
    regno = random.choice(student_regnos)
    book_name = random.choice(book_titles)
    borrow_days_ago = random.randint(1, 100)
    borrow_date = today - timedelta(days=borrow_days_ago)
    due_date = borrow_date + timedelta(days=14)
    # 70% chance book is returned
    if random.random() < 0.7:
        # Return date between borrow_date and due_date + 10 days
        return_delay = random.randint(-5, 10)
        actual_return_date = due_date + timedelta(days=return_delay)
        if actual_return_date < borrow_date:
            actual_return_date = borrow_date
        actual_return_date_str = actual_return_date.strftime('%Y-%m-%d')
    else:
        actual_return_date_str = None

    cursor.execute("""
        INSERT INTO borrowed_book (regno, book_name, borrow_date, due_date, actual_return_date)
        VALUES (?, ?, ?, ?, ?)
    """, (regno, book_name, borrow_date.strftime('%Y-%m-%d'), due_date.strftime('%Y-%m-%d'), actual_return_date_str))

conn.commit()
conn.close()

print("Added 17 students, 17 books, and 50 borrowed_book records to the database.")
