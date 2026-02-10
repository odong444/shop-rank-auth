import psycopg
import os

DATABASE_URL = os.environ.get('DATABASE_URL')


def get_db():
    return psycopg.connect(DATABASE_URL)


def init_db():
    conn = get_db()
    cur = conn.cursor()
    
    # users 테이블
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY, 
        user_id VARCHAR(50) UNIQUE NOT NULL,
        password VARCHAR(100) NOT NULL, 
        name VARCHAR(50) NOT NULL,
        phone VARCHAR(20) NOT NULL, 
        reg_date DATE DEFAULT CURRENT_DATE,
        approved CHAR(1) DEFAULT 'N')''')
    
    # products 테이블
    cur.execute('''CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY, 
        user_id VARCHAR(50) NOT NULL,
        mid VARCHAR(50) NOT NULL, 
        keyword VARCHAR(100) NOT NULL,
        title VARCHAR(500) DEFAULT '', 
        mall VARCHAR(100) DEFAULT '',
        current_rank VARCHAR(20) DEFAULT '-',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, mid, keyword))''')
    
    # rank_history 테이블
    cur.execute('''CREATE TABLE IF NOT EXISTS rank_history (
        id SERIAL PRIMARY KEY, 
        product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
        rank VARCHAR(20) NOT NULL, 
        checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # keyword_cache 테이블
    cur.execute('''CREATE TABLE IF NOT EXISTS keyword_cache (
        id SERIAL PRIMARY KEY,
        keyword VARCHAR(100) UNIQUE NOT NULL,
        search_results TEXT,
        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # sms_verify 테이블
    cur.execute('''CREATE TABLE IF NOT EXISTS sms_verify (
        id SERIAL PRIMARY KEY,
        phone VARCHAR(20) NOT NULL,
        code VARCHAR(6) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        verified BOOLEAN DEFAULT FALSE)''')

    # withdrawals 테이블 (출금 요청)
    cur.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
        id SERIAL PRIMARY KEY,
        user_id VARCHAR(50) NOT NULL,
        amount INTEGER NOT NULL,
        bank_name VARCHAR(50) NOT NULL,
        account_number VARCHAR(50) NOT NULL,
        account_holder VARCHAR(50) NOT NULL,
        status VARCHAR(20) DEFAULT 'pending',
        requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        processed_at TIMESTAMP,
        memo VARCHAR(200))''')

    # user_logs 테이블 (방문/이용 기록)
    cur.execute('''CREATE TABLE IF NOT EXISTS user_logs (
        id SERIAL PRIMARY KEY,
        user_id VARCHAR(50) NOT NULL,
        action VARCHAR(50) NOT NULL,
        detail VARCHAR(200),
        ip_address VARCHAR(50),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # notices 테이블 (공지사항)
    cur.execute('''CREATE TABLE IF NOT EXISTS notices (
        id SERIAL PRIMARY KEY,
        title VARCHAR(200) NOT NULL,
        content TEXT,
        is_popup BOOLEAN DEFAULT FALSE,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # place_ranks 테이블 (플레이스 순위)
    cur.execute('''CREATE TABLE IF NOT EXISTS place_ranks (
        id SERIAL PRIMARY KEY,
        user_id VARCHAR(50) NOT NULL,
        place_id VARCHAR(50) NOT NULL,
        keyword VARCHAR(100) NOT NULL,
        title VARCHAR(500) DEFAULT '',
        first_rank VARCHAR(20) DEFAULT '-',
        prev_rank VARCHAR(20) DEFAULT '-',
        current_rank VARCHAR(20) DEFAULT '-',
        last_checked TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, place_id, keyword))''')

    # place_rank_history 테이블 (플레이스 순위 이력)
    cur.execute('''CREATE TABLE IF NOT EXISTS place_rank_history (
        id SERIAL PRIMARY KEY,
        place_rank_id INTEGER REFERENCES place_ranks(id) ON DELETE CASCADE,
        rank VARCHAR(20) NOT NULL,
        checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    conn.commit()
    
    # 기존 테이블에 새 컬럼 추가
    for col in [("first_rank", "VARCHAR(20) DEFAULT '-'"), 
                ("prev_rank", "VARCHAR(20) DEFAULT '-'"), 
                ("last_checked", "TIMESTAMP")]:
        try:
            cur.execute(f"ALTER TABLE products ADD COLUMN {col[0]} {col[1]}")
            conn.commit()
        except Exception:
            conn.rollback()
    
    # users 테이블에 role 컬럼 추가
    try:
        cur.execute("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'normal'")
        conn.commit()
    except Exception:
        conn.rollback()
    
    # users 테이블에 사용량 컬럼 추가
    for col in [("product_score_used", "INTEGER DEFAULT 0"),
                ("brand_sales_used", "INTEGER DEFAULT 0"),
                ("coupang_sales_used", "INTEGER DEFAULT 0")]:
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col[0]} {col[1]}")
            conn.commit()
        except Exception:
            conn.rollback()

    # users 테이블에 약관 동의 컬럼 추가
    for col in [("terms_agreed", "BOOLEAN DEFAULT FALSE"),
                ("marketing_agreed", "BOOLEAN DEFAULT FALSE"),
                ("terms_agreed_at", "TIMESTAMP")]:
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col[0]} {col[1]}")
            conn.commit()
        except Exception:
            conn.rollback()

    # notices 테이블 컬럼 크기 확장
    try:
        cur.execute("ALTER TABLE notices ALTER COLUMN title TYPE VARCHAR(500)")
        conn.commit()
    except Exception:
        conn.rollback()

    # user_logs 테이블 컬럼 크기 확장
    try:
        cur.execute("ALTER TABLE user_logs ALTER COLUMN ip_address TYPE VARCHAR(200)")
        conn.commit()
    except Exception:
        conn.rollback()

    cur.close()
    conn.close()


def get_user_usage(user_id):
    """사용자의 사용량 및 권한 정보 조회"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''SELECT role, product_score_used, brand_sales_used, marketing_agreed, coupang_sales_used
                   FROM users WHERE user_id = %s''', (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row:
        return {
            'role': row[0] or 'normal',
            'product_score_used': row[1] or 0,
            'brand_sales_used': row[2] or 0,
            'marketing_agreed': row[3] or False,
            'coupang_sales_used': row[4] or 0
        }
    return None


def increment_usage(user_id, usage_type):
    """사용량 증가 (usage_type: 'product_score', 'brand_sales', 'coupang_sales')"""
    conn = get_db()
    cur = conn.cursor()

    if usage_type == 'product_score':
        cur.execute('UPDATE users SET product_score_used = product_score_used + 1 WHERE user_id = %s', (user_id,))
    elif usage_type == 'brand_sales':
        cur.execute('UPDATE users SET brand_sales_used = brand_sales_used + 1 WHERE user_id = %s', (user_id,))
    elif usage_type == 'coupang_sales':
        cur.execute('UPDATE users SET coupang_sales_used = coupang_sales_used + 1 WHERE user_id = %s', (user_id,))

    conn.commit()
    cur.close()
    conn.close()


def reset_user_usage(user_id, usage_type=None):
    """사용량 초기화 (usage_type: None이면 전체, 아니면 해당 타입만)"""
    conn = get_db()
    cur = conn.cursor()

    if usage_type == 'product_score':
        cur.execute('UPDATE users SET product_score_used = 0 WHERE user_id = %s', (user_id,))
    elif usage_type == 'brand_sales':
        cur.execute('UPDATE users SET brand_sales_used = 0 WHERE user_id = %s', (user_id,))
    elif usage_type == 'coupang_sales':
        cur.execute('UPDATE users SET coupang_sales_used = 0 WHERE user_id = %s', (user_id,))
    else:
        cur.execute('UPDATE users SET product_score_used = 0, brand_sales_used = 0, coupang_sales_used = 0 WHERE user_id = %s', (user_id,))

    conn.commit()
    cur.close()
    conn.close()


def reset_all_usage():
    """전체 사용자 사용량 초기화"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('UPDATE users SET product_score_used = 0, brand_sales_used = 0, coupang_sales_used = 0')
    conn.commit()
    cur.close()
    conn.close()


def get_pending_withdrawals_count():
    """대기 중인 출금 요청 수"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM withdrawals WHERE status = 'pending'")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count


def get_all_withdrawals():
    """전체 출금 요청 목록 (관리자용)"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''SELECT w.id, w.user_id, u.name, w.amount, w.bank_name, w.account_number,
                   w.account_holder, w.status, w.requested_at, w.processed_at, w.memo
                   FROM withdrawals w
                   LEFT JOIN users u ON w.user_id = u.user_id
                   ORDER BY w.requested_at DESC''')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_user_withdrawals(user_id):
    """사용자별 출금 요청 목록"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''SELECT id, amount, bank_name, account_number, account_holder,
                   status, requested_at, processed_at, memo
                   FROM withdrawals WHERE user_id = %s
                   ORDER BY requested_at DESC''', (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def create_withdrawal(user_id, amount, bank_name, account_number, account_holder):
    """출금 요청 생성"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''INSERT INTO withdrawals (user_id, amount, bank_name, account_number, account_holder)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id''',
                (user_id, amount, bank_name, account_number, account_holder))
    withdrawal_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return withdrawal_id


def update_withdrawal_status(withdrawal_id, status, memo=None):
    """출금 요청 상태 업데이트"""
    conn = get_db()
    cur = conn.cursor()
    if status in ['approved', 'rejected']:
        cur.execute('''UPDATE withdrawals SET status = %s, processed_at = CURRENT_TIMESTAMP, memo = %s
                       WHERE id = %s''', (status, memo, withdrawal_id))
    else:
        cur.execute('UPDATE withdrawals SET status = %s WHERE id = %s', (status, withdrawal_id))
    conn.commit()
    cur.close()
    conn.close()


# ===== 사용자 로그 관련 =====

def add_user_log(user_id, action, detail=None, ip_address=None):
    """사용자 활동 로그 추가"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''INSERT INTO user_logs (user_id, action, detail, ip_address)
                   VALUES (%s, %s, %s, %s)''', (user_id, action, detail, ip_address))
    conn.commit()
    cur.close()
    conn.close()


def get_user_logs(limit=100, user_id=None, action=None):
    """사용자 로그 조회"""
    conn = get_db()
    cur = conn.cursor()

    query = '''SELECT l.id, l.user_id, u.name, l.action, l.detail, l.ip_address, l.created_at
               FROM user_logs l
               LEFT JOIN users u ON l.user_id = u.user_id
               WHERE 1=1'''
    params = []

    if user_id:
        query += ' AND l.user_id = %s'
        params.append(user_id)
    if action:
        query += ' AND l.action = %s'
        params.append(action)

    query += ' ORDER BY l.created_at DESC LIMIT %s'
    params.append(limit)

    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_log_stats():
    """로그 통계 (오늘 방문자 수, 기능별 사용 횟수 등)"""
    conn = get_db()
    cur = conn.cursor()

    # 오늘 로그인 수
    cur.execute("""SELECT COUNT(DISTINCT user_id) FROM user_logs
                   WHERE action = 'login' AND DATE(created_at) = CURRENT_DATE""")
    today_logins = cur.fetchone()[0]

    # 오늘 기능 사용 횟수
    cur.execute("""SELECT action, COUNT(*) FROM user_logs
                   WHERE DATE(created_at) = CURRENT_DATE
                   GROUP BY action ORDER BY COUNT(*) DESC""")
    today_actions = cur.fetchall()

    cur.close()
    conn.close()

    return {
        'today_logins': today_logins,
        'today_actions': today_actions
    }


# ===== 공지사항 관련 =====

def get_notices(active_only=False):
    """공지사항 목록 조회"""
    conn = get_db()
    cur = conn.cursor()

    if active_only:
        cur.execute('SELECT id, title, content, is_popup, is_active, created_at FROM notices WHERE is_active = TRUE ORDER BY created_at DESC')
    else:
        cur.execute('SELECT id, title, content, is_popup, is_active, created_at FROM notices ORDER BY created_at DESC')

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_notice(notice_id):
    """공지사항 상세 조회"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT id, title, content, is_popup, is_active, created_at FROM notices WHERE id = %s', (notice_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def create_notice(title, content, is_popup=False):
    """공지사항 생성"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''INSERT INTO notices (title, content, is_popup) VALUES (%s, %s, %s) RETURNING id''',
                (title, content, is_popup))
    notice_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return notice_id


def update_notice(notice_id, title, content, is_popup, is_active):
    """공지사항 수정"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''UPDATE notices SET title = %s, content = %s, is_popup = %s, is_active = %s, updated_at = CURRENT_TIMESTAMP
                   WHERE id = %s''', (title, content, is_popup, is_active, notice_id))
    conn.commit()
    cur.close()
    conn.close()


def delete_notice(notice_id):
    """공지사항 삭제"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM notices WHERE id = %s', (notice_id,))
    conn.commit()
    cur.close()
    conn.close()


def get_popup_notices():
    """팝업 공지사항 조회 (활성화되고 제목이 있는 것만)"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''SELECT id, title, content FROM notices
                   WHERE is_popup = TRUE AND is_active = TRUE
                   AND title IS NOT NULL AND TRIM(title) != ''
                   ORDER BY created_at DESC''')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows
