# malody_api/core/database.py
import sqlite3
import os
from datetime import datetime
from typing import Optional

def get_db_connection(db_path: Optional[str] = None):
    """
    获取数据库连接，复用现有配置
    """
    if db_path is None:
        # 使用当前目录下的现有数据库
        db_path = "malody_rankings.db"
    
    # 检查数据库文件是否存在
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")
    
    # 修复Python 3.12中SQLite datetime适配器的弃用警告
    def adapt_datetime(dt):
        return dt.isoformat()

    def convert_datetime(s):
        return datetime.fromisoformat(s.decode())

    sqlite3.register_adapter(datetime, adapt_datetime)
    sqlite3.register_converter("timestamp", convert_datetime)
    
    conn = sqlite3.connect(
        db_path,
        detect_types=sqlite3.PARSE_DECLTYPES,
        check_same_thread=False
    )
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 3000")
    
    return conn

def db_safe_operation(func):
    """
    数据库操作安全装饰器，复用现有逻辑
    """
    from functools import wraps
    
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except sqlite3.Error as e:
            print(f"数据库错误: {e}")
            return None
        except Exception as e:
            print(f"操作错误: {e}")
            return None
    return wrapper