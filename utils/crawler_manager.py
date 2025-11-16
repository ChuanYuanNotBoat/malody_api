# malody_api/utils/crawler_manager.py
import os
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

class CrawlerManager:
    """爬虫状态管理器"""
    
    def __init__(self, db_path: str = "malody_rankings.db"):
        self.status_file = "crawler_status.json"
        self.db_path = db_path
        self.status_data = self._load_status()
    
    def _load_status(self) -> Dict[str, Any]:
        """加载爬虫状态"""
        try:
            if os.path.exists(self.status_file):
                with open(self.status_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"⚠️ 加载爬虫状态文件失败: {e}")
        return {}
    
    def _save_status(self):
        """保存爬虫状态"""
        try:
            with open(self.status_file, 'w', encoding='utf-8') as f:
                json.dump(self.status_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"❌ 保存爬虫状态失败: {e}")
    
    def update_status(self, sid: int, status: str, message: str = "", data: Dict = None):
        """更新爬虫状态"""
        self.status_data[str(sid)] = {
            "status": status,
            "message": message,
            "data": data or {},
            "last_updated": datetime.now().isoformat()
        }
        self._save_status()
    
    def get_status(self, sid: int) -> Optional[Dict[str, Any]]:
        """获取爬虫状态"""
        return self.status_data.get(str(sid))
    
    def can_update(self, sid: int, cooldown_hours: int = 24) -> bool:
        """检查是否可以更新（冷却时间）"""
        status = self.get_status(sid)
        if not status:
            return True
        
        last_updated_str = status.get("last_updated")
        if not last_updated_str:
            return True
        
        try:
            last_updated = datetime.fromisoformat(last_updated_str)
            return datetime.now() - last_updated > timedelta(hours=cooldown_hours)
        except ValueError:
            return True
    
    def get_all_status(self) -> Dict[str, Any]:
        """获取所有爬虫状态"""
        return self.status_data
    
    def get_song_info(self, sid: int) -> Optional[Dict[str, Any]]:
        """从数据库获取歌曲信息"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 获取歌曲基本信息
            cursor.execute("SELECT title, artist, cover_url FROM songs WHERE sid = ?", (sid,))
            song_result = cursor.fetchone()
            
            if not song_result:
                return None
            
            # 获取谱面统计
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_charts,
                    COUNT(CASE WHEN status = 2 THEN 1 END) as stable_charts,
                    GROUP_CONCAT(DISTINCT mode) as modes
                FROM charts WHERE sid = ?
            """, (sid,))
            stats_result = cursor.fetchone()
            
            conn.close()
            
            return {
                "sid": sid,
                "title": song_result[0],
                "artist": song_result[1],
                "cover_url": song_result[2],
                "total_charts": stats_result[0] if stats_result else 0,
                "stable_charts": stats_result[1] if stats_result else 0,
                "modes": [int(m) for m in stats_result[2].split(',')] if stats_result and stats_result[2] else []
            }
        except Exception as e:
            print(f"❌ 获取歌曲信息失败: {e}")
            return None
    
    def get_recently_updated(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近更新的歌曲"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT s.sid, s.title, s.artist, MAX(c.last_updated) as last_updated
                FROM songs s
                JOIN charts c ON s.sid = c.sid
                GROUP BY s.sid, s.title, s.artist
                ORDER BY last_updated DESC
                LIMIT ?
            """, (limit,))
            
            results = cursor.fetchall()
            conn.close()
            
            return [
                {
                    "sid": row[0],
                    "title": row[1],
                    "artist": row[2],
                    "last_updated": row[3]
                } for row in results
            ]
        except Exception as e:
            print(f"❌ 获取最近更新失败: {e}")
            return []

# 全局爬虫管理器实例
crawler_manager = CrawlerManager()