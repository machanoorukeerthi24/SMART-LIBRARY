import pandas as pd
import sqlite3
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, GridSearchCV, learning_curve
from sklearn.metrics import classification_report, accuracy_score
from sklearn.preprocessing import StandardScaler
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
import pickle
import numpy as np
import matplotlib.pyplot as plt

# --- 1. Connect to the SQLite database and query data ---
conn = sqlite3.connect('instance/library.db')

# You can either enrich your query or handle joins in pandas
# Let's start with a richer query that includes more data points if available
try:
    query = """
    SELECT
        BB.regno,
        S.gender,
        S.major,
        S.year_of_study,
        B.category,
        B.publication_year,
        COUNT(BB.regno) as borrow_count,
        AVG(CASE 
              WHEN BB.actual_return_date IS NOT NULL AND julianday(BB.actual_return_date) > julianday(BB.due_date) 
              THEN julianday(BB.actual_return_date) - julianday(BB.due_date)
              ELSE 0
            END) as avg_days_late,
        SUM(CASE 
              WHEN BB.actual_return_date IS NOT NULL AND julianday(BB.actual_return_date) > julianday(BB.due_date) 
              THEN 1
              ELSE 0
            END) as late_return_count
    FROM borrowed_book AS BB
    LEFT JOIN student AS S ON BB.regno = S.regno
    LEFT JOIN book AS B ON BB.book_id = B.book_id
    GROUP BY BB.regno, S.gender, S.major, S.year_of_study, B.category, B.publication_year
    """
    df = pd.read_sql_query(query, conn)
except pd.io.sql.DatabaseError:
    print("Warning: Could not join with student or book tables. Proceeding with original query.")
    query = """
    SELECT regno,
           COUNT(*) as borrow_count,
           AVG(CASE 
                 WHEN actual_return_date IS NOT NULL AND julianday(actual_return_date) > julianday(due_date) 
                 THEN julianday(actual_return_date) - julianday(due_date)
                 ELSE 0
               END) as avg_days_late,
           SUM(CASE 
                 WHEN actual_return_date IS NOT NULL AND julianday(actual_return_date) > julianday(due_date) 
                 THEN 1
                 ELSE 0
               END) as late_return_count
    FROM borrowed_book
    GROUP BY regno
    """
    df = pd.read_sql_query(query, conn)

conn.close()

# Handle potential missing values
df = df.fillna(0)

# Create the target variable
df['late_return'] = (df['late_return_count'] > 0).astype(int)

# --- 2. Feature Engineering and Preprocessing ---

# One-hot encode categorical features if they exist from the richer query
if 'major' in df.columns and 'category' in df.columns:
    df = pd.get_dummies(df, columns=['gender', 'major', 'category'], drop_first=True)

# Separate features (X) and target (y)
# We remove 'late_return_count' from features as it's directly related to the target
if 'major' in df.columns:
    X = df.drop(['regno', 'late_return', 'late_return_count'], axis=1)
else:
    X = df[['borrow_count', 'avg_days_late']]
y = df['late_return']

# --- 3. Split data ---

# Check if there are enough samples to stratify and split
if len(y) > 1 and y.nunique() > 1 and len(y) > 5:
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
elif len(y) > 1:
    # Fallback to non-stratified split if not enough classes or samples for stratify
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
else:
    # If only one sample, use all data as training set and empty test set
    X_train, X_test, y_train, y_test = X, pd.DataFrame(), y, pd.Series()

# Check class distribution
print("Class distribution in original data:")
print(y.value_counts(normalize=True))
print("-" * 30)

# --- 4. Define Pipelines and Models ---

# Check if there are enough samples for cross-validation
if len(X_train) >= 5 and y_train.nunique() > 1:
    # We'll use a pipeline to combine preprocessing with the model training
    # This prevents data leakage from the test set.

    # Define a pipeline for Logistic Regression
    pipeline_lr = ImbPipeline([
        ('scaler', StandardScaler()),
        ('smote', SMOTE(random_state=42, k_neighbors=3)),
        ('classifier', LogisticRegression(random_state=42, max_iter=1000))
    ])

    # Define a pipeline for Random Forest Classifier
    pipeline_rf = ImbPipeline([
        ('scaler', StandardScaler()),
        ('smote', SMOTE(random_state=42, k_neighbors=3)),
        ('classifier', RandomForestClassifier(random_state=42))
    ])

    # --- 5. Hyperparameter Tuning using GridSearchCV ---

    # Parameters for Logistic Regression
    param_grid_lr = {
        'classifier__C': [0.01, 0.1, 1, 10, 100]
    }

    # Parameters for Random Forest
    param_grid_rf = {
        'classifier__n_estimators': [100, 200],
        'classifier__max_depth': [10, 20, None],
        'classifier__min_samples_split': [2, 5]
    }

    print("Searching for best Logistic Regression model...")
    grid_search_lr = GridSearchCV(pipeline_lr, param_grid_lr, cv=5, scoring='f1', n_jobs=-1, verbose=1)
    grid_search_lr.fit(X_train, y_train)

    print("\nSearching for best Random Forest model...")
    grid_search_rf = GridSearchCV(pipeline_rf, param_grid_rf, cv=5, scoring='f1', n_jobs=-1, verbose=1)
    grid_search_rf.fit(X_train, y_train)
else:
    print("Not enough samples or class diversity for cross-validation and hyperparameter tuning.")
    grid_search_lr = None
    grid_search_rf = None

# --- 6. Evaluate and Compare Models ---

if grid_search_lr is not None and grid_search_rf is not None:
    # Best Logistic Regression model
    best_lr_model = grid_search_lr.best_estimator_
    y_pred_lr = best_lr_model.predict(X_test)
    report_lr = classification_report(y_test, y_pred_lr)
    accuracy_lr = accuracy_score(y_test, y_pred_lr)

    print("\n" + "=" * 50)
    print("Results for Best Logistic Regression Model")
    print("=" * 50)
    print(f"Best Parameters: {grid_search_lr.best_params_}")
    print(f"Accuracy: {accuracy_lr:.4f}")
    print("Classification Report:\n", report_lr)

    # Best Random Forest model
    best_rf_model = grid_search_rf.best_estimator_
    y_pred_rf = best_rf_model.predict(X_test)
    report_rf = classification_report(y_test, y_pred_rf)
    accuracy_rf = accuracy_score(y_test, y_pred_rf)

    print("\n" + "=" * 50)
    print("Results for Best Random Forest Model")
    print("=" * 50)
    print(f"Best Parameters: {grid_search_rf.best_params_}")
    print(f"Accuracy: {accuracy_rf:.4f}")
    print("Classification Report:\n", report_rf)

    # --- 7. Choose the best model and save it ---

    if accuracy_rf > accuracy_lr:
        final_model = best_rf_model
        final_accuracy = accuracy_rf
        model_name = "RandomForest"
        print("\nRandom Forest model was better. Saving it.")
    else:
        final_model = best_lr_model
        final_accuracy = accuracy_lr
        model_name = "LogisticRegression"
        print("\nLogistic Regression model was better. Saving it.")

    # Evaluate on training set
    y_pred_train = final_model.predict(X_train)
    accuracy_train = accuracy_score(y_train, y_pred_train)
    print(f"Training Accuracy: {accuracy_train:.4f}")

    # Learning curve
    train_sizes, train_scores, val_scores = learning_curve(
        final_model, X_train, y_train, cv=5, scoring='accuracy', n_jobs=-1,
        train_sizes=np.linspace(0.1, 1.0, 10)
    )
    train_scores_mean = np.mean(train_scores, axis=1)
    val_scores_mean = np.mean(val_scores, axis=1)
    plt.figure()
    plt.plot(train_sizes, train_scores_mean, 'o-', color='r', label='Training score')
    plt.plot(train_sizes, val_scores_mean, 'o-', color='g', label='Cross-validation score')
    plt.xlabel('Training examples')
    plt.ylabel('Score')
    plt.legend(loc='best')
    plt.title('Learning Curve')

    import os
    desktop_path = os.path.expanduser('~/Desktop/project output')
    if not os.path.exists(desktop_path):
        os.makedirs(desktop_path)

    plt.savefig(os.path.join(desktop_path, 'learning_curve.png'))
    print(f"Learning curve saved as {os.path.join(desktop_path, 'learning_curve.png')}")

    # Save the classification report to a file on Desktop/project output
    report_path = os.path.join(desktop_path, 'classification_report.txt')
    with open(report_path, 'w') as f:
        f.write(f"Final Model: {model_name}\n")
        f.write(f"Training Accuracy: {accuracy_train:.4f}\n")
        f.write(f"Test Accuracy: {final_accuracy:.4f}\n")
        if model_name == "LogisticRegression":
            f.write(f"Best Parameters: {grid_search_lr.best_params_}\n")
            f.write(report_lr)
        else:
            f.write(f"Best Parameters: {grid_search_rf.best_params_}\n")
            f.write(report_rf)
        f.write("\nLearning curve saved as learning_curve.png\n")
            
    print(f"Final Accuracy: {final_accuracy:.4f}")

    # Save the final best model on Desktop/project output
    model_path = os.path.join(desktop_path, 'best_model.pkl')
    with open(model_path, 'wb') as f:
        pickle.dump(final_model, f)

    print(f"✅ Improved model trained and saved as {model_path}")
else:
    print("Model training and evaluation skipped due to insufficient data or class diversity.")
