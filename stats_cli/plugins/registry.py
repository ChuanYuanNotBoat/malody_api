from stats_cli.plugins import crawl_status_plugin, export_plugin, optimize_plugin, update_plugin, utility_plugin


def install_plugins(cls, *, colorize, colors, db_safe_operation, get_separator, base_dir):
    update_plugin.install(cls, colorize=colorize, colors=colors, base_dir=base_dir)
    export_plugin.install(cls, colorize=colorize, colors=colors, db_safe_operation=db_safe_operation)
    optimize_plugin.install(cls, colorize=colorize, colors=colors, base_dir=base_dir)
    crawl_status_plugin.install(cls, colorize=colorize, colors=colors, get_separator=get_separator)
    utility_plugin.install(
        cls,
        colorize=colorize,
        colors=colors,
        get_separator=get_separator,
        db_safe_operation=db_safe_operation,
    )
