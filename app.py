import os
try:
    from dotenv import load_dotenv
    load_dotenv()          # must run BEFORE config.py reads SECRET_KEY
except ImportError:
    print("WARNING: python-dotenv not installed — .env will NOT be loaded.")

from flask import Flask
from flask_cors import CORS
from migration.db_init import init_db

app = Flask(__name__)
CORS(app)

from routes.auth_routes import auth_bp
from routes.registration_routes import registration_bp
from routes.classes_routes import classes_bp
from routes.teachers_routes import teachers_bp
from routes.terms_routes import terms_bp
from routes.students_routes import students_bp
from routes.marks_routes import marks_bp
from routes.analytics_routes import analytics_bp
from routes.config_routes import config_bp
from routes.reports_routes import reports_bp
from routes.scoresheet_routes import scoresheet_bp
from routes.announcements_routes import announcements_bp
from routes.parent_routes import parent_bp
from routes.subscription_routes import subscription_bp
from routes.pdf_routes import pdf_bp
from routes.superadmin_routes import superadmin_bp
from routes.import_routes import import_bp
from routes.static_routes import static_bp
from routes.access_routes import access_bp

for bp in (auth_bp, registration_bp, classes_bp, teachers_bp, terms_bp, students_bp,
           marks_bp, analytics_bp, config_bp, reports_bp, scoresheet_bp, announcements_bp,
           parent_bp, subscription_bp, pdf_bp, superadmin_bp, import_bp,access_bp,
           static_bp):                      # static last: it owns the catch-all route
    app.register_blueprint(bp)

with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))