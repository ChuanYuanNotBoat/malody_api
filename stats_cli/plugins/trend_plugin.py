import os
import shutil
from datetime import datetime, timedelta

import pandas as pd


def _safe_input(prompt: str, default: str = "") -> str:
    try:
        return input(prompt)
    except EOFError:
        return default


def get_terminal_width():
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 80


def format_number(number):
    if number is None:
        return "N/A"
    return f"{number:,}"


def format_change(change_value, reverse=False, is_percent=False):
    if change_value is None:
        return "N/A"
    if change_value == 0:
        return "0"
    if is_percent:
        return f"{change_value:+.2f}%"
    return f"{change_value:+d}"


def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors
    def do_trend(self, arg):
        """
        统计玩家数据变化趋势（参数优先）

        用法: trend <起始日期> [--mode 模式] [--fields 字段列表] [--match 时间窗口] [--rank-range 范围]
        选项:
            --mode        模式编号，默认为当前模式
            --fields      要显示的统计项，用逗号分隔，如 rank,lv,exp,acc,combo,pc
            --match       匹配时间窗口，如 1h(1小时), 30m(30分钟), 7d(7天)，默认1h
            --rank-range  排行榜名次范围，如 1-100，默认1-50

        示例:
            trend 2024-01-01
            trend 2024-01-01 0
            trend 2024-01-01 --match 2h --rank-range 1-50
            trend 2024-01-01 --mode 0 --fields rank,exp,acc
        """
        import re

        # 合法字段列表
        valid_fields = ["rank", "lv", "exp", "acc", "combo", "pc"]

        # 辅助函数：解析时间窗口字符串
        def parse_time_window(s):
            s = s.strip().lower()
            match = re.match(r'^(\d+)([dhms])$', s)
            if not match:
                raise ValueError(f"无效的时间窗口格式: {s}，应为数字后跟 d/h/m/s")
            num = int(match.group(1))
            unit = match.group(2)
            if unit == 'd':
                return timedelta(days=num)
            elif unit == 'h':
                return timedelta(hours=num)
            elif unit == 'm':
                return timedelta(minutes=num)
            elif unit == 's':
                return timedelta(seconds=num)
            else:
                raise ValueError(f"未知时间单位: {unit}")

        # 解析参数
        args_list = arg.split()
        start_date_str = None
        mode = self.current_mode
        display_fields = valid_fields[:]  # 默认显示所有字段
        match_window = timedelta(hours=1)  # 默认1小时
        rank_range = None  # (min, max) 或 None

        # 解析位置参数和选项
        i = 0
        while i < len(args_list):
            token = args_list[i]
            if token.startswith('--'):
                # 选项
                if token == '--mode':
                    if i+1 >= len(args_list):
                        print(colorize("错误: --mode 需要指定模式编号", Colors.RED))
                        return
                    try:
                        mode = int(args_list[i+1])
                        if mode not in self.mode_names or mode == -1:
                            print(colorize(f"错误: 无效的模式编号 {mode}", Colors.RED))
                            return
                    except ValueError:
                        print(colorize("错误: --mode 参数必须是数字", Colors.RED))
                        return
                    i += 2
                elif token == '--fields':
                    if i+1 >= len(args_list):
                        print(colorize("错误: --fields 需要指定字段列表", Colors.RED))
                        return
                    fields_str = args_list[i+1]
                    display_fields = [f.strip() for f in fields_str.split(',')]
                    # 验证字段
                    invalid = [f for f in display_fields if f not in valid_fields]
                    if invalid:
                        print(colorize(f"错误: 无效的显示项: {', '.join(invalid)}", Colors.RED))
                        print(colorize(f"有效的显示项: {', '.join(valid_fields)}", Colors.YELLOW))
                        return
                    i += 2
                elif token == '--match':
                    if i+1 >= len(args_list):
                        print(colorize("错误: --match 需要指定时间窗口", Colors.RED))
                        return
                    try:
                        match_window = parse_time_window(args_list[i+1])
                    except ValueError as e:
                        print(colorize(f"错误: {e}", Colors.RED))
                        return
                    i += 2
                elif token == '--rank-range':
                    if i+1 >= len(args_list):
                        print(colorize("错误: --rank-range 需要指定范围，如 1-100", Colors.RED))
                        return
                    range_str = args_list[i+1]
                    try:
                        parts = range_str.split('-')
                        if len(parts) != 2:
                            raise ValueError
                        min_rank = int(parts[0])
                        max_rank = int(parts[1])
                        if min_rank <= 0 or max_rank <= 0 or min_rank > max_rank:
                            raise ValueError
                        rank_range = (min_rank, max_rank)
                    except:
                        print(colorize("错误: --rank-range 格式应为 min-max，例如 1-100", Colors.RED))
                        return
                    i += 2
                else:
                    print(colorize(f"错误: 未知选项 {token}", Colors.RED))
                    return
            else:
                # 位置参数：起始日期，模式，显示字段（向后兼容）
                if start_date_str is None:
                    start_date_str = token
                elif mode == self.current_mode and not any(f in token for f in valid_fields) and token.isdigit():
                    # 如果模式还是默认且下一个是数字，可能是模式
                    try:
                        mode = int(token)
                        if mode not in self.mode_names or mode == -1:
                            print(colorize(f"错误: 无效的模式编号 {mode}", Colors.RED))
                            return
                    except ValueError:
                        # 不是数字，可能是显示字段的一部分
                        pass
                else:
                    # 可能是显示字段
                    display_fields = [f.strip() for f in token.split(',')]
                    invalid = [f for f in display_fields if f not in valid_fields]
                    if invalid:
                        print(colorize(f"错误: 无效的显示项: {', '.join(invalid)}", Colors.RED))
                        print(colorize(f"有效的显示项: {', '.join(valid_fields)}", Colors.YELLOW))
                        return
                i += 1

        if start_date_str is None:
            print(colorize("错误: 请输入起始日期 (YYYY-MM-DD)", Colors.RED))
            return
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        except ValueError:
            print(colorize("错误: 日期格式应为 YYYY-MM-DD", Colors.RED))
            return

        # 再次验证字段（避免遗漏）
        if any(f not in valid_fields for f in display_fields):
            print(colorize("错误: 无效的显示项", Colors.RED))
            return

        cursor = self.conn.cursor()

        # 获取数据库最新时间
        if mode != -1:
            cursor.execute("SELECT MAX(crawl_time) FROM player_rankings WHERE mode = ?", (mode,))
        else:
            cursor.execute("SELECT MAX(crawl_time) FROM player_rankings")
        latest_time_row = cursor.fetchone()
        if not latest_time_row or latest_time_row[0] is None:
            print(colorize("错误: 数据库中没有数据，无法进行趋势分析", Colors.RED))
            return

        raw_end_point = latest_time_row[0]
        # 确保 end_point 是 datetime 类型
        if isinstance(raw_end_point, str):
            try:
                end_point = datetime.fromisoformat(raw_end_point)
            except ValueError:
                # 尝试常见格式
                end_point = datetime.strptime(raw_end_point, '%Y-%m-%d %H:%M:%S')
        else:
            end_point = raw_end_point

        # 设置默认排名范围
        if rank_range is None:
            rank_range = (1, 50)
            print(colorize("未指定排名范围，默认使用 1-50", Colors.YELLOW))

        # 确保起始日期不晚于最新时间
        if start_date > end_point:
            print(colorize(f"错误: 起始日期 {start_date.strftime('%Y-%m-%d')} 晚于数据库最新时间 {end_point.strftime('%Y-%m-%d')}", Colors.RED))
            return

        # 匹配窗口基于最新时间向前推
        window_start = end_point - match_window

        # 构建基础模式条件
        mode_condition = "mode = ?" if mode != -1 else "1=1"
        params_start = [mode] if mode != -1 else []
        params_end = [mode] if mode != -1 else []

        # 起始快照：起始日期之前最近一条记录（不考虑窗口，仅用于对比）
        if mode != -1:
            cursor.execute("""
                SELECT pr.player_id, pr.name, pr.rank, pr.lv, pr.exp, pr.acc, pr.combo, pr.pc
                FROM player_rankings pr
                INNER JOIN (
                    SELECT player_id, MAX(crawl_time) as max_time
                    FROM player_rankings
                    WHERE mode = ? AND crawl_time <= ?
                    GROUP BY player_id
                ) latest ON pr.player_id = latest.player_id AND pr.crawl_time = latest.max_time
                WHERE pr.mode = ?
            """, (mode, start_date, mode))
        else:
            cursor.execute("""
                SELECT pr.player_id, pr.name, pr.rank, pr.lv, pr.exp, pr.acc, pr.combo, pr.pc
                FROM player_rankings pr
                INNER JOIN (
                    SELECT player_id, MAX(crawl_time) as max_time
                    FROM player_rankings
                    WHERE crawl_time <= ?
                    GROUP BY player_id
                ) latest ON pr.player_id = latest.player_id AND pr.crawl_time = latest.max_time
            """, (start_date,))
        start_players = {}
        for row in cursor.fetchall():
            pid = row[0]
            start_players[pid] = (row[1], row[2], row[3], row[4], row[5], row[6], row[7])

        # 结束快照：匹配窗口内最新记录（窗口内无记录视为掉出榜）
        if mode != -1:
            cursor.execute("""
                SELECT pr.player_id, pr.name, pr.rank, pr.lv, pr.exp, pr.acc, pr.combo, pr.pc, pr.crawl_time
                FROM player_rankings pr
                INNER JOIN (
                    SELECT player_id, MAX(crawl_time) as max_time
                    FROM player_rankings
                    WHERE mode = ? AND crawl_time BETWEEN ? AND ?
                    GROUP BY player_id
                ) latest ON pr.player_id = latest.player_id AND pr.crawl_time = latest.max_time
                WHERE pr.mode = ?
            """, (mode, window_start, end_point, mode))
        else:
            cursor.execute("""
                SELECT pr.player_id, pr.name, pr.rank, pr.lv, pr.exp, pr.acc, pr.combo, pr.pc, pr.crawl_time
                FROM player_rankings pr
                INNER JOIN (
                    SELECT player_id, MAX(crawl_time) as max_time
                    FROM player_rankings
                    WHERE crawl_time BETWEEN ? AND ?
                    GROUP BY player_id
                ) latest ON pr.player_id = latest.player_id AND pr.crawl_time = latest.max_time
            """, (window_start, end_point))
        end_players = {}
        latest_times = {}  # 存储每个玩家的最新记录时间（用于显示）
        for row in cursor.fetchall():
            pid = row[0]
            end_players[pid] = (row[1], row[2], row[3], row[4], row[5], row[6], row[7])
            latest_times[pid] = row[8]

        # 如果指定了排名范围，过滤起始和结束玩家
        if rank_range:
            min_rank, max_rank = rank_range
            # 过滤起始玩家
            start_players = {pid: data for pid, data in start_players.items()
                             if min_rank <= data[1] <= max_rank}
            # 过滤结束玩家
            end_players = {pid: data for pid, data in end_players.items()
                           if min_rank <= data[1] <= max_rank}
            # 对于掉出榜的玩家（仅在start中），需要判断其起始排名是否在范围内
            # 对于新上榜的玩家（仅在end中），结束排名已在范围内
            # 对于一直在榜的玩家，起始和结束都在范围内

        # 分析变化
        all_player_ids = set(start_players.keys()) | set(end_players.keys())

        trend_data = []

        for player_id in all_player_ids:
            in_start = player_id in start_players
            in_end = player_id in end_players

            if in_start and in_end:
                # 一直在榜
                start_data = start_players[player_id]
                end_data = end_players[player_id]
                start_name, start_rank, start_lv, start_exp, start_acc, start_combo, start_pc = start_data
                end_name, end_rank, end_lv, end_exp, end_acc, end_combo, end_pc = end_data
                current_name = end_name if end_name != start_name else start_name

                # 检查指定字段是否有变化
                field_has_changes = False
                for field in display_fields:
                    if field == "rank" and start_rank != end_rank:
                        field_has_changes = True
                        break
                    elif field == "lv" and start_lv != end_lv:
                        field_has_changes = True
                        break
                    elif field == "exp" and start_exp != end_exp:
                        field_has_changes = True
                        break
                    elif field == "acc" and start_acc != end_acc:
                        field_has_changes = True
                        break
                    elif field == "combo" and start_combo != end_combo:
                        field_has_changes = True
                        break
                    elif field == "pc" and start_pc != end_pc:
                        field_has_changes = True
                        break

                if not field_has_changes:
                    continue

                trend_data.append({
                    'player_id': player_id,
                    'name': current_name,
                    'status': '=',
                    'start_rank': start_rank,
                    'end_rank': end_rank,
                    'rank_change': end_rank - start_rank,
                    'start_lv': start_lv,
                    'end_lv': end_lv,
                    'lv_change': end_lv - start_lv,
                    'start_exp': start_exp,
                    'end_exp': end_exp,
                    'exp_change': end_exp - start_exp,
                    'start_acc': start_acc,
                    'end_acc': end_acc,
                    'acc_change': end_acc - start_acc,
                    'start_combo': start_combo,
                    'end_combo': end_combo,
                    'combo_change': end_combo - start_combo,
                    'start_pc': start_pc,
                    'end_pc': end_pc,
                    'pc_change': end_pc - start_pc,
                    'has_changes': True,
                    'latest_time': latest_times.get(player_id)
                })
            elif in_start and not in_end:
                # 掉出榜：起始玩家在范围内，但窗口内无记录
                start_data = start_players[player_id]
                start_name, start_rank, start_lv, start_exp, start_acc, start_combo, start_pc = start_data

                trend_data.append({
                    'player_id': player_id,
                    'name': start_name,
                    'status': '-',
                    'start_rank': start_rank,
                    'end_rank': None,
                    'rank_change': None,
                    'start_lv': start_lv,
                    'end_lv': None,
                    'lv_change': None,
                    'start_exp': start_exp,
                    'end_exp': None,
                    'exp_change': None,
                    'start_acc': start_acc,
                    'end_acc': None,
                    'acc_change': None,
                    'start_combo': start_combo,
                    'end_combo': None,
                    'combo_change': None,
                    'start_pc': start_pc,
                    'end_pc': None,
                    'pc_change': None,
                    'has_changes': True,
                    'latest_time': None
                })
            elif not in_start and in_end:
                # 新上榜：结束玩家在范围内
                end_data = end_players[player_id]
                end_name, end_rank, end_lv, end_exp, end_acc, end_combo, end_pc = end_data

                trend_data.append({
                    'player_id': player_id,
                    'name': end_name,
                    'status': '+',
                    'start_rank': None,
                    'end_rank': end_rank,
                    'rank_change': None,
                    'start_lv': None,
                    'end_lv': end_lv,
                    'lv_change': None,
                    'start_exp': None,
                    'end_exp': end_exp,
                    'exp_change': None,
                    'start_acc': None,
                    'end_acc': end_acc,
                    'acc_change': None,
                    'start_combo': None,
                    'end_combo': end_combo,
                    'combo_change': None,
                    'start_pc': None,
                    'end_pc': end_pc,
                    'pc_change': None,
                    'has_changes': True,
                    'latest_time': latest_times.get(player_id)
                })

        if not trend_data:
            print(colorize(f"\n在指定的时间范围内，模式 {mode} 没有发现数据变化", Colors.YELLOW))
            return

        # 按结束排名排序（掉出榜的玩家排最后）
        trend_data.sort(key=lambda x: (x['end_rank'] is None, x['end_rank'] or 9999))

        # 显示结果
        mode_name = self.mode_names.get(mode, "未知")
        print(colorize(f"\n玩家数据变化趋势 (模式 {mode} - {mode_name})", Colors.CYAN))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        if rank_range:
            print(colorize(f"排名范围: {rank_range[0]} - {rank_range[1]}", Colors.YELLOW))
        print(colorize(f"起始时间: {start_date.strftime('%Y-%m-%d')}", Colors.YELLOW))
        print(colorize(f"数据截止时间: {end_point.strftime('%Y-%m-%d %H:%M:%S')}", Colors.YELLOW))
        print(colorize(f"匹配窗口: {match_window} (基于数据库最新数据向前推)", Colors.YELLOW))

        separator_width = get_terminal_width()
        print(get_separator(separator_width))

        # 构建表头
        header_parts = ["状态", "玩家名"]
        format_specs = [8, 20]

        field_configs = {
            "rank": ("排名", 10, 10, 10),
            "lv": ("等级", 10, 10, 10),
            "exp": ("经验", 12, 12, 10),
            "acc": ("准确率", 12, 12, 12),
            "combo": ("连击", 10, 10, 10),
            "pc": ("游玩", 10, 10, 10)
        }

        for field in display_fields:
            if field in field_configs:
                name, start_width, end_width, change_width = field_configs[field]
                header_parts.extend([f"起始{name}", f"结束{name}", f"{name}变化"])
                format_specs.extend([start_width, end_width, change_width])

        # 调整玩家名宽度
        total_width = sum(format_specs) + (len(format_specs) - 1) * 2
        if total_width > separator_width:
            excess = total_width - separator_width
            player_width = max(10, 20 - excess)
            format_specs[1] = player_width

        format_parts = [f"{{:<{w}}}" for w in format_specs]
        header_format = "  ".join(format_parts)
        print(colorize(header_format.format(*header_parts), Colors.BOLD))
        print(get_separator(separator_width))

        for player in trend_data:
            row_parts = []
            # 状态符号
            if player['status'] == '+':
                status_display = colorize("[+]", Colors.GREEN)
            elif player['status'] == '-':
                status_display = colorize("[-]", Colors.RED)
            else:
                status_display = colorize("[=]", Colors.BLUE)

            player_name = player['name']
            max_name_len = format_specs[1]
            if len(player_name) > max_name_len:
                player_name = player_name[:max_name_len-3] + "..."
            row_parts.extend([status_display, player_name])

            for field in display_fields:
                if field == "rank":
                    row_parts.extend([
                        str(player['start_rank']) if player['start_rank'] is not None else "N/A",
                        str(player['end_rank']) if player['end_rank'] is not None else "掉出",
                        format_change(player['rank_change'], reverse=True)
                    ])
                elif field == "lv":
                    row_parts.extend([
                        str(player['start_lv']) if player['start_lv'] is not None else "N/A",
                        str(player['end_lv']) if player['end_lv'] is not None else "N/A",
                        format_change(player['lv_change'])
                    ])
                elif field == "exp":
                    row_parts.extend([
                        format_number(player['start_exp']) if player['start_exp'] is not None else "N/A",
                        format_number(player['end_exp']) if player['end_exp'] is not None else "N/A",
                        format_change(player['exp_change'])
                    ])
                elif field == "acc":
                    row_parts.extend([
                        f"{player['start_acc']:.2f}%" if player['start_acc'] is not None else "N/A",
                        f"{player['end_acc']:.2f}%" if player['end_acc'] is not None else "N/A",
                        format_change(player['acc_change'], is_percent=True)
                    ])
                elif field == "combo":
                    row_parts.extend([
                        format_number(player['start_combo']) if player['start_combo'] is not None else "N/A",
                        format_number(player['end_combo']) if player['end_combo'] is not None else "N/A",
                        format_change(player['combo_change'])
                    ])
                elif field == "pc":
                    row_parts.extend([
                        format_number(player['start_pc']) if player['start_pc'] is not None else "N/A",
                        format_number(player['end_pc']) if player['end_pc'] is not None else "N/A",
                        format_change(player['pc_change'])
                    ])

            print(header_format.format(*row_parts))

        print(get_separator(separator_width))

        total_players = len(trend_data)
        stayed = len([p for p in trend_data if p['status'] == '='])
        dropped = len([p for p in trend_data if p['status'] == '-'])
        new = len([p for p in trend_data if p['status'] == '+'])

        print(colorize(f"统计: 总计 {total_players} 名玩家 | 一直在榜: {stayed} | 掉出榜: {dropped} | 新上榜: {new}", Colors.YELLOW))

        # 导出选项：支持格式/编号/Y(询问格式)/N(skip)
        if getattr(self, "_non_interactive", False):
            export_choice = "n"
        else:
            export_choice = _safe_input(
                colorize("\n导出: 输入格式(csv/xlsx)/编号(1/2)/Y(询问格式)/N(skip) [N]: ", Colors.CYAN),
                default="n",
            ).strip().lower()
        export_format = self._resolve_trend_export_format(export_choice)
        if export_format:
            self.export_trend_data(
                trend_data,
                display_fields,
                mode,
                start_date,
                end_point,
                export_format=export_format,
            )

    def _resolve_trend_export_format(self, raw_choice):
        """解析导出输入，返回 csv/xlsx 或 None（跳过）"""
        choice = (raw_choice or "").strip().lower()
        format_map = {
            "1": "csv",
            "2": "xlsx",
            "csv": "csv",
            "xlsx": "xlsx",
        }
        if choice in ("", "n", "no"):
            return None
        if choice in format_map:
            return format_map[choice]
        if choice in ("y", "yes"):
            followup = _safe_input(
                colorize("请选择导出格式：csv/xlsx 或 1/2 [csv]: ", Colors.CYAN),
                default="csv",
            ).strip().lower()
            if not followup:
                return "csv"
            return format_map.get(followup)

        print(colorize("无效输入，已跳过导出。可输入 csv/xlsx/1/2/Y/N", Colors.YELLOW))
        return None

    def export_trend_data(self, trend_data, display_fields, mode, start_date, end_point, export_format="csv"):
        """导出趋势数据为 CSV/XLSX 文件"""
        # 构建数据框
        data_dict = {}
        
        # 基本字段
        data_dict['状态'] = [player['status'] for player in trend_data]
        data_dict['玩家名'] = [player['name'] for player in trend_data]
        
        # 根据选择的字段添加数据
        if "rank" in display_fields:
            data_dict['起始排名'] = [player['start_rank'] for player in trend_data]
            data_dict['结束排名'] = [player['end_rank'] for player in trend_data]
            data_dict['排名变化'] = [player['rank_change'] for player in trend_data]
        
        if "lv" in display_fields:
            data_dict['起始等级'] = [player['start_lv'] for player in trend_data]
            data_dict['结束等级'] = [player['end_lv'] for player in trend_data]
            data_dict['等级变化'] = [player['lv_change'] for player in trend_data]
        
        if "exp" in display_fields:
            data_dict['起始经验'] = [player['start_exp'] for player in trend_data]
            data_dict['结束经验'] = [player['end_exp'] for player in trend_data]
            data_dict['经验变化'] = [player['exp_change'] for player in trend_data]
        
        if "acc" in display_fields:
            data_dict['起始准确率'] = [player['start_acc'] for player in trend_data]
            data_dict['结束准确率'] = [player['end_acc'] for player in trend_data]
            data_dict['准确率变化'] = [player['acc_change'] for player in trend_data]
        
        if "combo" in display_fields:
            data_dict['起始连击'] = [player['start_combo'] for player in trend_data]
            data_dict['结束连击'] = [player['end_combo'] for player in trend_data]
            data_dict['连击变化'] = [player['combo_change'] for player in trend_data]
        
        if "pc" in display_fields:
            data_dict['起始游玩次数'] = [player['start_pc'] for player in trend_data]
            data_dict['结束游玩次数'] = [player['end_pc'] for player in trend_data]
            data_dict['游玩次数变化'] = [player['pc_change'] for player in trend_data]
        
        df = pd.DataFrame(data_dict)
        
        # 生成文件名
        mode_name = self.mode_names.get(mode, "未知")
        ext = export_format if export_format in ("csv", "xlsx") else "csv"
        base_filename = f"trend_mode{mode}_{start_date.strftime('%Y%m%d')}_{end_point.strftime('%Y%m%d')}.{ext}"
        filename = self.get_unique_filename(base_filename, ext)
        filepath = os.path.join(self.output_dir, filename)
        
        # 保存文件
        if ext == "csv":
            df.to_csv(filepath, index=False, encoding="utf-8-sig")
        else:
            from utils.stats_xlsx_formatter import apply_change_conditional_formatting, autosize_openpyxl_sheet

            with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="trend", index=False)
                ws = writer.sheets.get("trend")
                if ws is not None:
                    ws.freeze_panes = "A2"
                    apply_change_conditional_formatting(ws, df)
                    autosize_openpyxl_sheet(ws)
        print(colorize(f"\n已导出趋势数据({ext.upper()}): {filepath}", Colors.GREEN))
    

    setattr(cls, "do_trend", db_safe_operation(do_trend))
    setattr(cls, "_resolve_trend_export_format", _resolve_trend_export_format)
    setattr(cls, "export_trend_data", export_trend_data)

