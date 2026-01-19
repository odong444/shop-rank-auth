from flask import Blueprint, request, jsonify, session, redirect, render_template
from functools import wraps
import os

brand_sales_bp = Blueprint('brand_sales', __name__)

# 로컬 서버 URL
RANK_API_URL = os.environ.get('RANK_API_URL', '')

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


@brand_sales_bp.route('/brand-sales')
@login_required
def brand_sales_page():
    return render_template('brand_sales.html', active_menu='brand-sales', rank_api_url=RANK_API_URL)
