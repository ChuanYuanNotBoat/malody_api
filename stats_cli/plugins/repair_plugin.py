def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors
    def do_repair(self, arg):
        """
        手动修复数据库问题
        
        用法: repair [force]
        参数:
        force - 可选，强制重新修复，即使没有发现问题
        
        示例:
        repair      # 检查并修复问题
        repair force # 强制重新修复
        """
        force_repair = arg.strip().lower() == "force"
        
        cursor = self.conn.cursor()
        
        print(colorize("\n数据库修复工具", Colors.CYAN))
        print(get_separator())
        
        if force_repair:
            print(colorize("强制修复模式", Colors.YELLOW))
        
        try:
            # 检查数据库完整性
            cursor.execute("PRAGMA integrity_check")
            integrity_result = cursor.fetchone()[0]
            
            issues_found = []
            
            if integrity_result != "ok":
                issues_found.append(f"数据库完整性: {integrity_result}")
                print(colorize(f"发现数据库完整性问题: {integrity_result}", Colors.YELLOW))
            
            # 检查状态统计问题
            cursor.execute("SELECT COUNT(*) FROM charts WHERE status = 1")
            beta_count = cursor.fetchone()[0]
            
            # 检查是否有状态为1的记录但统计为0
            if beta_count == 0:
                cursor.execute("SELECT cid FROM charts WHERE status = 1 LIMIT 5")
                beta_records = cursor.fetchall()
                if beta_records:
                    issues_found.append("状态为1的记录存在但统计为0")
                    print(colorize(f"发现 {len(beta_records)} 个状态为1的记录，但统计显示为0", Colors.YELLOW))
                    for cid, in beta_records:
                        print(f"  CID {cid} 状态为1")
            
            # 如果没有发现问题但强制修复，或者发现问题
            if issues_found or force_repair:
                if force_repair and not issues_found:
                    print(colorize("强制重新修复数据库...", Colors.YELLOW))
                else:
                    print(colorize(f"发现 {len(issues_found)} 个问题，正在修复...", Colors.YELLOW))
                
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
                
                fixed_count = 0
                for cid, correct_status in known_issues:
                    cursor.execute("SELECT status FROM charts WHERE cid = ?", (cid,))
                    result = cursor.fetchone()
                    if result:
                        current_status = result[0]
                        if current_status != correct_status:
                            cursor.execute("UPDATE charts SET status = ? WHERE cid = ?", (correct_status, cid))
                            fixed_count += 1
                            print(f"  修复 CID {cid}: 状态 {current_status} -> {correct_status}")
                
                self.conn.commit()
                
                # 验证修复结果
                cursor.execute("PRAGMA integrity_check")
                new_integrity = cursor.fetchone()[0]
                
                print(colorize("\n修复完成!", Colors.GREEN))
                print(f"修复了 {fixed_count} 条记录")
                print(f"修复后完整性检查: {new_integrity}")
                
                # 显示修复后的状态分布
                cursor.execute("SELECT status, COUNT(*) FROM charts GROUP BY status ORDER BY status")
                status_dist = cursor.fetchall()
                status_names = {0: "Alpha", 1: "Beta", 2: "Stable"}
                
                print(colorize("\n修复后状态分布:", Colors.CYAN))
                for status, count in status_dist:
                    status_name = status_names.get(status, f"未知({status})")
                    print(f"  {status_name}: {count}")
                    
            else:
                print(colorize("没有发现需要修复的问题。", Colors.GREEN))
                print(colorize("如需强制重新修复，请使用 'repair force' 命令。", Colors.YELLOW))
                
        except Exception as e:
            print(colorize(f"修复过程中发生错误: {e}", Colors.RED))



    setattr(cls, "do_repair", db_safe_operation(do_repair))

