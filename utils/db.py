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
    
    cur.close()
    conn.close()
