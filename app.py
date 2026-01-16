from flask import Flask, redirect, session
from flask_cors import CORS
import os

from utils.db import init_db
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.product_score import product_score_bp
from routes.admin import admin_bp

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')
CORS(app)

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(product_score_bp)
app.register_blueprint(admin_bp)


@app.route('/')
def index():
    return redirect('/dashboard' if 'user_id' in session else '/login')


# Initialize database
with app.app_context():
    try:
        init_db()
    except:
        pass


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
