# malody_api/routers/system.py
from fastapi import APIRouter
from datetime import datetime
import sqlite3
import os

# 修复导入路径 - 改为绝对导入
from malody_api.core.database import get_db_connection
from malody_api.core.models import APIResponse

router = APIRouter(prefix="/system", tags=["system"])

@router.get("/health", response_model=APIResponse)
async def health_check():
    """健康检查"""
    try:
        # 检查数据库连接
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 执行简单查询验证数据库状态
        cursor.execute("SELECT COUNT(*) FROM sqlite_master")
        table_count = cursor.fetchone()[0]
        
        conn.close()
        
        return APIResponse(
            success=True,
            data={
                "status": "healthy",
                "database_tables": table_count,
                "timestamp": datetime.now()
            },
            message="系统运行正常",
            timestamp=datetime.now()
        )
        
    except Exception as e:
        return APIResponse(
            success=False,
            error=f"系统异常: {str(e)}",
            timestamp=datetime.now()
        )

@router.get("/database-info", response_model=APIResponse)
async def get_database_info():
    """获取数据库信息"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 获取表信息
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' 
            ORDER BY name
        """)
        tables = [row[0] for row in cursor.fetchall()]
        
        # 获取各表记录数
        table_stats = {}
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            table_stats[table] = count
        
        # 获取数据库文件信息
        db_path = "malody_rankings.db"
        file_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        
        conn.close()
        
        return APIResponse(
            success=True,
            data={
                "tables": tables,
                "table_stats": table_stats,
                "file_size_bytes": file_size,
                "file_size_mb": round(file_size / (1024 * 1024), 2) if file_size > 0 else 0,
                "timestamp": datetime.now()
            },
            timestamp=datetime.now()
        )
        
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )