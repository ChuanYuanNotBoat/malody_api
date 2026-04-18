from datetime import datetime


def install(cls, *, colorize, colors, db_safe_operation):
    def do_alias(self, arg):
        """
        设置玩家别名
        """
        args = arg.split()
        if len(args) < 2:
            print(colorize("错误: 请输入原名和新名", colors.RED))
            return

        original_name = args[0]
        new_name = " ".join(args[1:])
        cursor = self.conn.cursor()

        try:
            cursor.execute("SELECT player_id FROM player_aliases WHERE alias = ?", (original_name,))
            result = cursor.fetchone()
            if not result:
                print(colorize(f"\n未找到玩家: {original_name}", colors.YELLOW))
                return

            player_id = result[0]
            cursor.execute("SELECT player_id FROM player_aliases WHERE alias = ?", (new_name,))
            result = cursor.fetchone()
            if result:
                print(colorize(f"\n名称 '{new_name}' 已被其他玩家使用", colors.RED))
                return

            current_time = datetime.now()
            cursor.execute(
                """
                INSERT INTO player_aliases (player_id, alias, first_seen, last_seen)
                VALUES (?, ?, ?, ?)
                """,
                (player_id, new_name, current_time, current_time),
            )
            cursor.execute(
                "UPDATE player_identity SET current_name = ? WHERE player_id = ?",
                (new_name, player_id),
            )
            self.conn.commit()
            print(colorize(f"\n成功将 '{original_name}' 的别名设置为 '{new_name}'", colors.GREEN))
        except Exception as e:
            self.conn.rollback()
            print(colorize(f"\n数据库错误: {e}", colors.RED))

    setattr(cls, "do_alias", db_safe_operation(do_alias))

