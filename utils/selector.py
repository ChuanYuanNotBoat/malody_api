# malody_api/utils/selector.py
import re
from typing import List, Dict, Any, Union, Optional, Tuple
from datetime import datetime, timedelta

class MCSelector:
    """类似MC的选择器，支持玩家、谱师、难度、时间范围、模式、状态等筛选"""
    
    def __init__(self):
        self.current_mode = -1  # -1 表示所有模式
        self.filters = {
            'players': [],      # 玩家名称/UID列表（在玩家命令中为玩家，在谱面命令中为谱师）
            'difficulties': [], # 难度范围
            'time_range': None, # 时间范围
            'modes': [],        # 模式列表
            'statuses': []      # 谱面状态列表 (0=Alpha, 1=Beta, 2=Stable)
        }
        
        # 状态名称映射
        self.status_names = {
            0: "Alpha",
            1: "Beta", 
            2: "Stable"
        }
        
    def parse_selector(self, selector_str: str) -> Dict[str, Any]:
        """
        解析选择器字符串
        格式: @<类型>[<条件>]
        示例: 
          @p[Zani,N0tYour1dol]        # 选择玩家/谱师
          @d[5-10]                    # 选择难度5-10
          @t[7d]                      # 选择最近7天
          @m[0,3,5]                   # 选择模式0,3,5
          @s[0,2]                     # 选择状态Alpha和Stable
          @*                          # 选择所有
        """
        if not selector_str.strip():
            return {}
            
        result = {}
        pattern = r'@([pdtsm*])\[([^\]]*)\]|@(\*)'
        
        matches = re.findall(pattern, selector_str)
        for match in matches:
            selector_type = match[0] or match[2]
            condition = match[1]
            
            if selector_type == 'p':  # 玩家/谱师
                result['players'] = [p.strip() for p in condition.split(',') if p.strip()]
            elif selector_type == 'd':  # 难度
                result['difficulties'] = self._parse_difficulty_range(condition)
            elif selector_type == 't':  # 时间
                result['time_range'] = self._parse_time_range(condition)
            elif selector_type == 's':  # 状态
                result['statuses'] = [int(s.strip()) for s in condition.split(',') if s.strip()]
            elif selector_type == 'm':  # 模式
                result['modes'] = [int(m.strip()) for m in condition.split(',') if m.strip()]
            elif selector_type == '*':  # 所有
                result['all'] = True
                
        return result
    
    def _parse_difficulty_range(self, condition: str) -> List[float]:
        """解析难度范围"""
        if not condition:
            return []
            
        try:
            if '-' in condition:
                start, end = condition.split('-')
                return [float(start.strip()), float(end.strip())]
            else:
                return [float(condition.strip())]
        except ValueError:
            return []
    
    def _parse_time_range(self, condition: str) -> Dict[str, datetime]:
        """解析时间范围"""
        now = datetime.now()
        
        if not condition:
            return {'start': now - timedelta(days=30), 'end': now}
            
        try:
            if condition.endswith('d'):  # 天数
                days = int(condition[:-1])
                return {'start': now - timedelta(days=days), 'end': now}
            elif condition.endswith('h'):  # 小时
                hours = int(condition[:-1])
                return {'start': now - timedelta(hours=hours), 'end': now}
            elif condition.endswith('w'):  # 周数
                weeks = int(condition[:-1])
                return {'start': now - timedelta(weeks=weeks), 'end': now}
            elif condition.endswith('m'):  # 月数
                months = int(condition[:-1])
                return {'start': now - timedelta(days=months*30), 'end': now}
            else:
                # 尝试解析为具体日期
                target_date = datetime.strptime(condition, '%Y-%m-%d')
                return {'start': target_date, 'end': now}
        except (ValueError, TypeError):
            return {'start': now - timedelta(days=30), 'end': now}
    
    def build_player_sql_where(self, base_table: str = "pr") -> tuple:
        """构建玩家相关的SQL WHERE条件和参数"""
        conditions = []
        params = []
        
        # 玩家筛选
        if self.filters['players']:
            player_conditions = []
            for player in self.filters['players']:
                if player.isdigit():  # UID
                    player_conditions.append(f"{base_table}.uid = ?")
                    params.append(player)
                else:  # 玩家名
                    player_conditions.append(f"{base_table}.name LIKE ?")
                    params.append(f"%{player}%")
            conditions.append(f"({' OR '.join(player_conditions)})")
        
        # 时间范围筛选
        if self.filters['time_range']:
            conditions.append(f"{base_table}.crawl_time BETWEEN ? AND ?")
            params.extend([
                self.filters['time_range']['start'],
                self.filters['time_range']['end']
            ])
        
        # 模式筛选
        if self.filters['modes']:
            conditions.append(f"{base_table}.mode IN ({','.join(['?']*len(self.filters['modes']))})")
            params.extend(self.filters['modes'])
        elif self.current_mode != -1:  # 当前单个模式
            conditions.append(f"{base_table}.mode = ?")
            params.append(self.current_mode)
        
        # 注意：玩家命令不应用状态筛选
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        return where_clause, params
    
    def build_chart_sql_where(self, base_table: str = "c") -> tuple:
        """构建谱面相关的SQL WHERE条件和参数"""
        conditions = []
        params = []
        
        # 谱师筛选（复用玩家筛选条件，应用到creator_name字段）
        if self.filters['players']:
            creator_conditions = []
            for creator in self.filters['players']:
                # 对于谱面，我们只支持名称匹配（creator_name字段）
                creator_conditions.append(f"{base_table}.creator_name LIKE ?")
                params.append(f"%{creator}%")
            conditions.append(f"({' OR '.join(creator_conditions)})")
        
        # 难度筛选
        if self.filters['difficulties']:
            if len(self.filters['difficulties']) == 1:
                conditions.append(f"{base_table}.level = ?")
                params.append(str(self.filters['difficulties'][0]))
            elif len(self.filters['difficulties']) == 2:
                conditions.append(f"CAST({base_table}.level AS REAL) BETWEEN ? AND ?")
                params.extend(self.filters['difficulties'])
        
        # 时间范围筛选
        if self.filters['time_range']:
            conditions.append(f"{base_table}.last_updated BETWEEN ? AND ?")
            params.extend([
                self.filters['time_range']['start'],
                self.filters['time_range']['end']
            ])
        
        # 模式筛选
        if self.filters['modes']:
            conditions.append(f"{base_table}.mode IN ({','.join(['?']*len(self.filters['modes']))})")
            params.extend(self.filters['modes'])
        elif self.current_mode != -1:  # 当前单个模式
            conditions.append(f"{base_table}.mode = ?")
            params.append(self.current_mode)
        
        # 状态筛选
        if self.filters['statuses']:
            conditions.append(f"{base_table}.status IN ({','.join(['?']*len(self.filters['statuses']))})")
            params.extend(self.filters['statuses'])
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        return where_clause, params
    
    def set_filters(self, **filters):
        """设置筛选条件"""
        for key, value in filters.items():
            if key in self.filters:
                self.filters[key] = value
    
    def clear_filters(self):
        """清除所有筛选条件"""
        self.filters = {
            'players': [],
            'difficulties': [],
            'time_range': None,
            'modes': [],
            'statuses': []
        }
    
    def get_current_selection(self) -> str:
        """获取当前选择的描述"""
        parts = []
        
        if self.filters['players']:
            # 根据上下文决定显示"玩家"还是"谱师"
            # 在实际使用中，可以根据命令类型来调整显示
            parts.append(f"谱师: {', '.join(self.filters['players'])}")
        
        if self.filters['difficulties']:
            if len(self.filters['difficulties']) == 1:
                parts.append(f"难度: {self.filters['difficulties'][0]}")
            else:
                parts.append(f"难度: {self.filters['difficulties'][0]}-{self.filters['difficulties'][1]}")
        
        if self.filters['time_range']:
            days = (self.filters['time_range']['end'] - self.filters['time_range']['start']).days
            parts.append(f"时间: 最近{days}天")
        
        if self.filters['modes']:
            mode_names = {0: "Key", 1: "Step", 2: "DJ", 3: "Catch", 4: "Pad", 
                         5: "Taiko", 6: "Ring", 7: "Slide", 8: "Live", 9: "Cube"}
            mode_str = ', '.join([f"{m}({mode_names.get(m, '未知')})" for m in self.filters['modes']])
            parts.append(f"模式: {mode_str}")
        elif self.current_mode != -1:
            mode_names = {0: "Key", 1: "Step", 2: "DJ", 3: "Catch", 4: "Pad", 
                         5: "Taiko", 6: "Ring", 7: "Slide", 8: "Live", 9: "Cube"}
            parts.append(f"模式: {self.current_mode}({mode_names.get(self.current_mode, '未知')})")
        else:
            parts.append("模式: 所有")
        
        # 添加状态筛选显示
        if self.filters['statuses']:
            status_str = ', '.join([f"{s}({self.status_names.get(s, '未知')})" for s in self.filters['statuses']])
            parts.append(f"状态: {status_str}")
        
        return " | ".join(parts) if parts else "无筛选条件"