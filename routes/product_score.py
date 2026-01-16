from flask import Blueprint, session, redirect, render_template
from functools import wraps
import os

product_score_bp = Blueprint('product_score', __name__)

# 로컬 서버 URL
RANK_API_URL = os.environ.get('RANK_API_URL', 'https://bat-loved-independence-attachments.trycloudflare.com')

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


@product_score_bp.route('/product-score')
@login_required
def product_score_page():
    return render_template('product_score.html', 
                           active_menu='product-score',
                           rank_api_url=RANK_API_URL)
