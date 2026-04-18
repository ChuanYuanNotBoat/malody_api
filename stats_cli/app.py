# malody_stats.py
import sqlite3
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import cmd
import os
import sys
from typing import Dict, List, Tuple, Optional
import matplotlib.dates as mdates
from matplotlib.ticker import MaxNLocator, LogLocator, FuncFormatter
import subprocess
import atexit
import signal
from functools import wraps
import shutil
import re
import math
import json
import copy                     # 新增导入，用于深拷贝选择器
from selector import global_selector, MCSelector
from utils.stats_export_runner import parse_export_request, run_export
from utils.stats_update_runner import build_update_command, run_streaming_command, split_cli_args
from stats_cli.plugins.registry import install_plugins

# 修复matplotlib中文字体问题
def setup_chinese_font():
    """设置中文字体支持（增强版）"""
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    import platform
    import os

    # 常见中文字体名称（按优先级排序）
    chinese_font_names = [
        'Microsoft YaHei',        # Windows
        'SimHei',                  # Windows
        'PingFang SC',             # macOS
        'STHeiti',                 # macOS
        'WenQuanYi Micro Hei',     # Linux
        'Noto Sans CJK SC',        # Linux
        'Droid Sans Fallback',     # Android
    ]

    # 如果系统是 Windows，可以指定完整路径（备选）
    if platform.system() == 'Windows':
        # 尝试从系统字体目录加载
        win_font_dir = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts')
        win_fonts = {
            'Microsoft YaHei': os.path.join(win_font_dir, 'msyh.ttc'),
            'SimHei': os.path.join(win_font_dir, 'simhei.ttf'),
        }
        for name, path in win_fonts.items():
            if os.path.exists(path):
                fm.fontManager.addfont(path)
                chinese_font_names.insert(0, name)  # 优先使用已找到的字体

    # 查找系统中可用的中文字体
    available_fonts = set(f.name for f in fm.fontManager.ttflist)
    found_font = None
    for font_name in chinese_font_names:
        if font_name in available_fonts:
            found_font = font_name
            break

    if found_font:
        plt.rcParams['font.sans-serif'] = [found_font] + plt.rcParams['font.sans-serif']
        plt.rcParams['axes.unicode_minus'] = False
        print(f"已设置中文字体: {found_font}")
        return True
    else:
        print("警告: 未找到支持中文的字体，图表中的中文可能显示为方块")
        print("可尝试手动安装以下字体之一: " + ", ".join(chinese_font_names))
        return False

# 在程序初始化时调用字体设置
setup_chinese_font()


# PowerShell 颜色支持修复
def enable_powershell_colors():
    """在 PowerShell 中启用 ANSI 颜色支持"""
    if sys.platform == "win32":
        try:
            # 方法1: 通过设置环境变量启用虚拟终端
            os.environ["TERM"] = "xterm-256color"
            
            # 方法2: 使用 ctypes 启用虚拟终端处理
            if hasattr(sys, 'getwindowsversion'):
                import ctypes
                from ctypes import wintypes
                
                kernel32 = ctypes.windll.kernel32
                STD_OUTPUT_HANDLE = -11
                
                # 获取标准输出句柄
                hstdout = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
                
                # 获取当前控制台模式
                mode = wintypes.DWORD()
                if kernel32.GetConsoleMode(hstdout, ctypes.byref(mode)):
                    # 启用虚拟终端处理
                    ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                    new_mode = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
                    kernel32.SetConsoleMode(hstdout, new_mode)
                    return True
        except:
            pass
    return False

# 在程序启动时启用 PowerShell 颜色
enable_powershell_colors()

# 修复Python 3.12中SQLite datetime适配器的弃用警告
def adapt_datetime(dt):
    return dt.isoformat()

def convert_datetime(s):
    return datetime.fromisoformat(s.decode())

sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("timestamp", convert_datetime)

# 设置matplotlib使用Agg后端（无GUI）
plt.switch_backend('Agg')

# 设置图表字体颜色为深色，避免与背景冲突
plt.rcParams['text.color'] = 'black'
plt.rcParams['axes.labelcolor'] = 'black'
plt.rcParams['xtick.color'] = 'black'
plt.rcParams['ytick.color'] = 'black'
plt.rcParams['axes.titlecolor'] = 'black'

# 颜色定义 (ANSI转义码)
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

def color_enabled():
    """检查当前环境是否支持颜色输出"""
    if sys.platform == "win32":
        # 在 Windows 上检查是否在支持颜色的终端中运行
        try:
            # 检查是否在 Windows Terminal、PowerShell 5.1+ 或支持 ANSI 的 CMD 中运行
            term_program = os.environ.get('TERM_PROGRAM', '')
            term = os.environ.get('TERM', '')
            
            # Windows Terminal 或现代 PowerShell
            if 'WindowsTerminal' in term_program or 'TERM' in os.environ:
                return True
            
            # 检查 PowerShell 版本（5.1+ 支持 ANSI）
            import subprocess
            result = subprocess.run(['powershell', '$PSVersionTable.PSVersion.Major'], 
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0 and result.stdout.strip().isdigit():
                ps_version = int(result.stdout.strip())
                if ps_version >= 5:
                    return True
                    
            # 最后的手段：尝试检测控制台能力
            import ctypes
            from ctypes import wintypes
            
            kernel32 = ctypes.windll.kernel32
            STD_OUTPUT_HANDLE = -11
            hstdout = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            
            mode = wintypes.DWORD()
            if kernel32.GetConsoleMode(hstdout, ctypes.byref(mode)):
                ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                return (mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING) != 0
                
        except:
            pass
        return False
    else:
        # 非 Windows 系统通常支持颜色
        return True

def colorize(text, color):
    """有条件地添加颜色到文本"""
    if color_enabled():
        return f"{color}{text}{Colors.END}"
    return text

def db_safe_operation(func):
    """装饰器用于确保数据库操作安全"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except sqlite3.Error as e:
            print(colorize(f"数据库错误: {e}", Colors.RED))
            return False
        except Exception as e:
            print(colorize(f"操作错误: {e}", Colors.RED))
            return False
    return wrapper

def format_change(change_value, reverse=False, is_percent=False):
    """格式化变化值，添加颜色"""
    if change_value is None:
        return "N/A"
    
    if change_value == 0:
        return "0"
    
    if is_percent:
        change_str = f"{change_value:+.2f}%"
    else:
        change_str = f"{change_value:+d}"
    
    # 对于排名变化，负数表示进步（排名上升）
    if reverse:
        if change_value < 0:
            return colorize(change_str, Colors.GREEN)  # 进步
        elif change_value > 0:
            return colorize(change_str, Colors.RED)    # 退步
    else:
        if change_value > 0:
            return colorize(change_str, Colors.GREEN)  # 增加
        elif change_value < 0:
            return colorize(change_str, Colors.RED)    # 减少
    
    return change_str

def format_number(number):
    """格式化大数字，添加千位分隔符"""
    if number is None:
        return "N/A"
    return f"{number:,}"

def get_terminal_width():
    """获取终端宽度"""
    try:
        return shutil.get_terminal_size().columns
    except:
        return 80

def get_separator(width=None):
    """获取自适应分隔线"""
    if width is None:
        width = get_terminal_width()
    return colorize("=" * min(width, 120), Colors.CYAN)

def get_subseparator(width=None):
    """获取自适应子分隔线"""
    if width is None:
        width = get_terminal_width()
    return colorize("-" * min(width, 100), Colors.CYAN)

class MalodyViz(cmd.Cmd):
    """Malody排行榜数据可视化工具"""
    
    intro = colorize("\n欢迎使用Malody排行榜数据可视化工具!\n\n", Colors.CYAN) + \
            "输入 " + colorize("help", Colors.GREEN) + " 或 " + colorize("?", Colors.GREEN) + " 查看命令列表。\n" + \
            "输入 " + colorize("help <命令名>", Colors.GREEN) + " 查看具体命令的详细说明。\n\n" + \
            "所有生成的图表将保存在 " + colorize("viz_output", Colors.YELLOW) + " 目录中。\n" + \
            "提示: 可以使用 " + colorize("ls", Colors.GREEN) + " 命令查看当前目录文件。\n"
    prompt = colorize("(malody-viz) ", Colors.BLUE)
    
    def __init__(self):
        super().__init__()
        self.db_path = "malody_rankings.db"
        self.conn = None
        self.current_mode = -1  # -1 表示所有模式
        self.output_dir = "viz_output"
        
        atexit.register(self.cleanup)
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        
        self.connect_db()
        
        # 初始化选择器
        self.selector = global_selector
        self.selector.current_mode = self.current_mode
        
        self.mode_names = {
            -1: "All",  # 所有模式
            0: "Key",
            1: "Step", 
            2: "DJ",
            3: "Catch",
            4: "Pad",
            5: "Taiko",
            6: "Ring", 
            7: "Slide",
            8: "Live",
            9: "Cube"
        }
        
        # 自动修复数据库问题
        self.auto_repair_database()
    
    def connect_db(self):
        """连接到SQLite数据库"""
        try:
            self.conn = sqlite3.connect(
                self.db_path, 
                detect_types=sqlite3.PARSE_DECLTYPES,
                check_same_thread=False
            )
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA busy_timeout = 3000")
            print(colorize(f"成功连接到数据库: {self.db_path}", Colors.GREEN))
        except sqlite3.Error as e:
            print(colorize(f"数据库连接错误: {e}", Colors.RED))
            sys.exit(1)
    
    def cleanup(self):
        """清理资源"""
        if self.conn:
            try:
                self.conn.close()
                print(colorize("\n数据库连接已安全关闭", Colors.GREEN))
            except:
                pass
    
    def signal_handler(self, signum, frame):
        """处理中断信号"""
        print(colorize("\n正在安全退出...", Colors.YELLOW))
        self.cleanup()
        sys.exit(0)
    
    def emptyline(self):
        """空行时不执行任何操作"""
        pass
    
    def get_unique_filename(self, base_name, extension):
        """生成不重复的文件名，添加时间戳"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name_only = os.path.splitext(base_name)[0]
        return f"{name_only}_{timestamp}.{extension}"
    
    @db_safe_operation
    def auto_repair_database(self):
        """
        自动修复数据库常见问题
        """
        cursor = self.conn.cursor()
        
        print(colorize("\n正在检查数据库状态...", Colors.CYAN))
        
        try:
            # 检查数据库完整性
            cursor.execute("PRAGMA integrity_check")
            integrity_result = cursor.fetchone()[0]
            
            issues_found = []
            
            if integrity_result != "ok":
                issues_found.append(f"数据库完整性: {integrity_result}")
                print(colorize(f"发现数据库完整性问题: {integrity_result}", Colors.YELLOW))
            
            # 检查状态为1的记录是否存在但统计不显示的问题
            cursor.execute("SELECT COUNT(*) FROM charts WHERE status = 1")
            beta_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT cid FROM charts WHERE status = 1 LIMIT 1")
            beta_exists = cursor.fetchone()
            
            if beta_count == 0 and beta_exists:
                issues_found.append("状态为1的记录存在但统计不显示")
                print(colorize("发现状态统计不一致问题", Colors.YELLOW))
            
            # 如果有问题，自动修复
            if issues_found:
                print(colorize(f"发现 {len(issues_found)} 个问题，正在自动修复...", Colors.YELLOW))
                
                # 修复索引
                print("修复数据库索引...")
                cursor.execute("REINDEX")
                
                # 清理数据库
                print("清理数据库...")
                cursor.execute("VACUUM")
                
                # 修复已知的状态不一致问题
                print("修复状态不一致问题...")
                known_issues = [
                    (139970, 1),  # CID 139970 应该是状态1
                    # 可以在这里添加其他已知的问题CID和正确状态
                ]
                
                for cid, correct_status in known_issues:
                    cursor.execute("SELECT status FROM charts WHERE cid = ?", (cid,))
                    current_status = cursor.fetchone()
                    if current_status and current_status[0] != correct_status:
                        cursor.execute("UPDATE charts SET status = ? WHERE cid = ?", (correct_status, cid))
                        print(f"  修复 CID {cid}: 状态 {current_status[0]} -> {correct_status}")
                
                self.conn.commit()
                
                # 验证修复结果
                cursor.execute("PRAGMA integrity_check")
                new_integrity = cursor.fetchone()[0]
                
                if new_integrity == "ok":
                    print(colorize("自动修复完成！数据库现在正常。", Colors.GREEN))
                else:
                    print(colorize(f"修复后完整性检查: {new_integrity}", Colors.YELLOW))
                    
            else:
                print(colorize("数据库状态正常，无需修复。", Colors.GREEN))
                
        except Exception as e:
            print(colorize(f"自动修复过程中发生错误: {e}", Colors.RED))
    @db_safe_operation
    def do_stb_creator_trends(self, arg):
        """
        分析特定创作者的谱面更新趋势

        用法: stb_creator_trends <创作者名> [周期] [--since YYYY-MM-DD] [--last N(d|w|m|y)]
        周期: days(日), months(月), 默认months
        --since: 指定起始日期，格式 YYYY-MM-DD
        --last: 指定最近一段时间，如 30d (天), 8w (周), 6m (月), 1y (年)

        示例:
        stb_creator_trends chuanyuan
        stb_creator_trends chuanyuan days --last 90d
        stb_creator_trends chuanyuan months --since 2025-01-01
        """
        args = arg.split()
        if not args:
            print(colorize("错误: 请输入创作者名", Colors.RED))
            return

        creator = args[0]
        period = "months"
        time_range = None  # None 表示全部时间

        i = 1
        while i < len(args):
            if args[i] in ["days", "months"]:
                period = args[i]
                i += 1
            elif args[i] == "--since":
                if i+1 >= len(args):
                    print(colorize("错误: --since 需要指定日期 (YYYY-MM-DD)", Colors.RED))
                    return
                try:
                    start_date = datetime.strptime(args[i+1], "%Y-%m-%d")
                    time_range = {"start": start_date, "end": datetime.now()}
                    i += 2
                except ValueError:
                    print(colorize("错误: 日期格式应为 YYYY-MM-DD", Colors.RED))
                    return
            elif args[i] == "--last":
                if i+1 >= len(args):
                    print(colorize("错误: --last 需要指定时间范围 (如 30d, 6m)", Colors.RED))
                    return
                time_str = args[i+1]
                parsed = self._parse_time_range_string(time_str)
                if parsed:
                    time_range = parsed
                    i += 2
                else:
                    print(colorize(f"错误: 无法解析时间范围 '{time_str}'", Colors.RED))
                    return
            else:
                # 忽略未知参数
                i += 1

        selector = copy.deepcopy(self.selector)
        selector.set_filters(players=[creator])
        where_clause, params = selector.build_chart_sql_where("c")

        # 根据时间范围构建条件
        if time_range:
            # 使用用户指定的时间范围
            start = time_range['start']
            end = time_range['end']
            time_condition = "c.last_updated BETWEEN ? AND ?"
            params.extend([start, end])
            if where_clause != "1=1":
                where_clause += f" AND {time_condition}"
            else:
                where_clause = time_condition
        # 否则不添加时间条件（查询全部）

        # 根据周期设置分组
        if period == "days":
            group_by = "DATE(c.last_updated)"
            order_by = "DATE(c.last_updated)"
            x_label = "日期"
        else:
            group_by = "strftime('%Y-%m', c.last_updated)"
            order_by = "strftime('%Y-%m', c.last_updated)"
            x_label = "月份"

        query = f"""
        SELECT {group_by}, COUNT(*)
        FROM charts c
        WHERE {where_clause}
        GROUP BY {group_by}
        ORDER BY {order_by}
        """
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        trend_data = cursor.fetchall()

        if not trend_data:
            print(colorize("没有找到趋势数据", Colors.YELLOW))
            return

        dates = [row[0] for row in trend_data]
        counts = [row[1] for row in trend_data]

        # 显示统计
        total = sum(counts)
        avg = total/len(counts)
        print(colorize(f"\n创作者 {creator} 的谱面更新趋势 ({period})", Colors.CYAN))
        if time_range:
            print(colorize(f"时间范围: {time_range['start'].strftime('%Y-%m-%d')} 至 {time_range['end'].strftime('%Y-%m-%d')}", Colors.YELLOW))
        else:
            print(colorize("时间范围: 全部时间", Colors.YELLOW))
        print(f"总更新谱面: {total}, 平均{period}更新: {avg:.1f}")

        # 生成图表
        fig, ax = plt.subplots(figsize=(12,6))
        ax.plot(dates, counts, 'o-', linewidth=2, markersize=6, color='#2196F3')
        ax.fill_between(dates, counts, alpha=0.3, color='#2196F3')
        ax.axhline(y=avg, color='red', linestyle='--', alpha=0.7, label=f'平均 {avg:.1f}')
        ax.set_title(f'创作者 {creator} 谱面更新趋势')
        ax.set_xlabel(x_label)
        ax.set_ylabel('更新谱面数量')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()

        safe_creator = re.sub(r'[^\w]', '_', creator)
        filename = self.get_unique_filename(f"creator_trends_{safe_creator}_{period}.png", "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor='white')
        plt.close()
        print(colorize(f"已生成趋势图表: {filepath}", Colors.GREEN))

    def _parse_time_range_string(self, time_str):
        """解析时间范围字符串，支持格式：N(d|w|m|y) 或 YYYY-MM-DD"""
        now = datetime.now()
        try:
            if time_str.endswith('d'):
                days = int(time_str[:-1])
                return {'start': now - timedelta(days=days), 'end': now}
            elif time_str.endswith('w'):
                weeks = int(time_str[:-1])
                return {'start': now - timedelta(weeks=weeks), 'end': now}
            elif time_str.endswith('m'):
                months = int(time_str[:-1])
                return {'start': now - timedelta(days=months*30), 'end': now}
            elif time_str.endswith('y'):
                years = int(time_str[:-1])
                return {'start': now - timedelta(days=years*365), 'end': now}
            else:
                # 尝试解析为具体日期
                start = datetime.strptime(time_str, "%Y-%m-%d")
                return {'start': start, 'end': now}
        except:
            return None

    # 增强 do_update 命令


    def print_topics(self, header, cmds, cmdlen, maxcol):
        if cmds:
            self.stdout.write(colorize("%s\n" % str(header), Colors.CYAN))
            if self.ruler:
                self.stdout.write(colorize("%s\n" % str(self.ruler * len(header)), Colors.CYAN))
            self.columnize(cmds, maxcol-1)
            self.stdout.write("\n")


install_plugins(
    MalodyViz,
    colorize=colorize,
    colors=Colors,
    db_safe_operation=db_safe_operation,
    get_separator=get_separator,
    get_subseparator=get_subseparator,
    get_terminal_width=get_terminal_width,
    base_dir=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

def main() -> int:
    if not os.path.exists("malody_rankings.db"):
        print(colorize("Error: database file 'malody_rankings.db' not found", Colors.RED))
        print(colorize("Please place the database file in the project root directory", Colors.YELLOW))
        return 1

    try:
        MalodyViz().cmdloop()
        return 0
    except KeyboardInterrupt:
        print(colorize("\nInterrupted by user", Colors.YELLOW))
        return 130
    except Exception as e:
        print(colorize(f"\nProgram error: {e}", Colors.RED))
        return 1


if __name__ == "__main__":
    sys.exit(main())
