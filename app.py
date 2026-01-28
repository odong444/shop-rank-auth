from flask import Flask, redirect, session
from flask_cors import CORS
import os
import atexit

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from utils.db import init_db
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.product_score import product_score_bp
from routes.brand_sales import brand_sales_bp
from routes.admin import admin_bp

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')
CORS(app)

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(product_score_bp)
app.register_blueprint(brand_sales_bp)
app.register_blueprint(admin_bp)


@app.route('/')
def index():
    return redirect('/naver-shop' if 'user_id' in session else '/login')


# Initialize database
with app.app_context():
    try:
        init_db()
    except:
        pass


# ===== 스케줄러 설정 (매일 오후 1시 KST 전체 상품 업데이트) =====
def scheduled_rank_update():
    """스케줄러에서 호출되는 전체 상품 업데이트 함수"""
    from Scheduler import main as run_scheduler
    print("[Scheduler] 전체 상품 순위 업데이트 시작...")
    try:
        run_scheduler()
        print("[Scheduler] 전체 상품 순위 업데이트 완료!")
    except Exception as e:
        print(f"[Scheduler] 에러 발생: {e}")


# 스케줄러 시작 (gunicorn 중복 실행 방지)
if os.environ.get('WERKZEUG_RUN_MAIN') != 'true' or os.environ.get('SCHEDULER_ENABLED', 'true') == 'true':
    scheduler = BackgroundScheduler(timezone=pytz.timezone('Asia/Seoul'))
    scheduler.add_job(
        func=scheduled_rank_update,
        trigger=CronTrigger(hour=13, minute=0, timezone=pytz.timezone('Asia/Seoul')),
        id='daily_rank_update',
        name='매일 오후 1시 전체 상품 순위 업데이트',
        replace_existing=True
    )
    scheduler.start()
    print("[Scheduler] 스케줄러 시작됨 - 매일 오후 1시(KST) 실행 예정")

    # 앱 종료 시 스케줄러도 종료
    atexit.register(lambda: scheduler.shutdown())


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
