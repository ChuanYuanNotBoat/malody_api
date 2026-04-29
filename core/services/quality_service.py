import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..database import get_db_connection


def _now_iso() -> str:
    return datetime.now().isoformat()


class QualityService:
    def __init__(self, db_path: str = "malody_rankings.db"):
        self.db_path = db_path
        self.logs_dir = os.path.join(os.getcwd(), "logs")
        self.history_file = os.path.join(self.logs_dir, "quality_reports.json")
        os.makedirs(self.logs_dir, exist_ok=True)
        self.rules = [
            {
                "id": "completeness_player_rankings",
                "name": "Player rankings completeness",
                "category": "completeness",
                "description": "Detect null/empty player names in rankings.",
            },
            {
                "id": "consistency_chart_song_fk",
                "name": "Charts linked to songs",
                "category": "consistency",
                "description": "Detect chart records whose SID is missing in songs table.",
            },
            {
                "id": "timeliness_latest_player_crawl",
                "name": "Latest player crawl freshness",
                "category": "timeliness",
                "description": "Detect stale player ranking crawl timestamps.",
            },
            {
                "id": "anomaly_invalid_chart_level",
                "name": "Invalid chart level values",
                "category": "anomaly",
                "description": "Detect invalid chart levels (<=0).",
            },
            {
                "id": "cross_table_mode_coverage",
                "name": "Cross-table mode coverage",
                "category": "cross_table",
                "description": "Detect mode values in charts that do not appear in rankings.",
            },
        ]

    def _load_history(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.history_file):
            return []
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_history(self, history: List[Dict[str, Any]]) -> None:
        tmp = self.history_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.history_file)

    def list_rules(self) -> List[Dict[str, Any]]:
        return self.rules

    def _issue(self, rule_id: str, severity: str, message: str, metric: Any, recommendation: str) -> Dict[str, Any]:
        return {
            "rule_id": rule_id,
            "severity": severity,
            "message": message,
            "metric": metric,
            "recommendation": recommendation,
        }

    def _run_all(self, stale_hours: int = 72) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM player_rankings WHERE name IS NULL OR TRIM(name) = ''")
            bad_names = int(cursor.fetchone()[0] or 0)
            if bad_names > 0:
                issues.append(
                    self._issue(
                        "completeness_player_rankings",
                        "high" if bad_names > 100 else "medium",
                        "player_rankings has empty player names",
                        {"bad_rows": bad_names},
                        "Repair or re-crawl affected records.",
                    )
                )

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM charts c
                LEFT JOIN songs s ON s.sid = c.sid
                WHERE s.sid IS NULL
                """
            )
            missing_song_fk = int(cursor.fetchone()[0] or 0)
            if missing_song_fk > 0:
                issues.append(
                    self._issue(
                        "consistency_chart_song_fk",
                        "high" if missing_song_fk > 1000 else "medium",
                        "charts contains rows with missing songs foreign records",
                        {"missing_rows": missing_song_fk},
                        "Backfill songs table or remove invalid chart rows.",
                    )
                )

            cursor.execute("SELECT MAX(crawl_time) FROM player_rankings")
            latest_crawl = cursor.fetchone()[0]
            if latest_crawl:
                try:
                    if isinstance(latest_crawl, str):
                        latest_dt = datetime.fromisoformat(latest_crawl.replace("Z", "+00:00").replace(" ", "T"))
                    else:
                        latest_dt = latest_crawl
                    delta = datetime.now() - latest_dt.replace(tzinfo=None)
                    if delta > timedelta(hours=stale_hours):
                        issues.append(
                            self._issue(
                                "timeliness_latest_player_crawl",
                                "medium",
                                "player rankings data looks stale",
                                {"hours_since_latest": round(delta.total_seconds() / 3600, 1)},
                                "Run leaderboard crawler to refresh data.",
                            )
                        )
                except Exception:
                    issues.append(
                        self._issue(
                            "timeliness_latest_player_crawl",
                            "low",
                            "failed to parse latest crawl timestamp",
                            {"raw_value": str(latest_crawl)},
                            "Normalize timestamp format during ingestion.",
                        )
                    )

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM charts
                WHERE level IS NOT NULL
                  AND TRIM(level) != ''
                  AND CAST(level AS REAL) <= 0
                """
            )
            invalid_levels = int(cursor.fetchone()[0] or 0)
            if invalid_levels > 0:
                issues.append(
                    self._issue(
                        "anomaly_invalid_chart_level",
                        "low" if invalid_levels < 50 else "medium",
                        "charts contains invalid non-positive level values",
                        {"invalid_rows": invalid_levels},
                        "Repair invalid levels or exclude them from analytics.",
                    )
                )

            cursor.execute(
                """
                SELECT COUNT(DISTINCT c.mode)
                FROM charts c
                LEFT JOIN player_rankings p ON p.mode = c.mode
                WHERE p.mode IS NULL
                """
            )
            missing_modes = int(cursor.fetchone()[0] or 0)
            if missing_modes > 0:
                issues.append(
                    self._issue(
                        "cross_table_mode_coverage",
                        "low",
                        "charts has mode values not present in player rankings",
                        {"mode_count": missing_modes},
                        "Verify crawler coverage for those modes.",
                    )
                )
        finally:
            conn.close()
        return issues

    def run_check(self, stale_hours: int = 72, selected_rules: Optional[List[str]] = None) -> Dict[str, Any]:
        issues = self._run_all(stale_hours=stale_hours)
        if selected_rules:
            wanted = set(selected_rules)
            issues = [item for item in issues if item["rule_id"] in wanted]

        penalties = {"high": 30, "medium": 15, "low": 5}
        score = 100
        for issue in issues:
            score -= penalties.get(issue.get("severity", "low"), 5)
        score = max(0, score)

        severity = "low"
        if score < 60:
            severity = "high"
        elif score < 80:
            severity = "medium"

        history = self._load_history()
        previous_score = history[-1]["score"] if history else None
        trend = "stable"
        if isinstance(previous_score, (int, float)):
            if score > previous_score:
                trend = "improving"
            elif score < previous_score:
                trend = "degrading"

        report = {
            "checked_at": _now_iso(),
            "score": score,
            "severity": severity,
            "issues": issues,
            "repair_suggestions": sorted({issue["recommendation"] for issue in issues}),
            "trend": trend,
            "rule_count": len(self.rules),
            "issue_count": len(issues),
            "selected_rules": selected_rules or [],
        }
        history.append(report)
        history = history[-200:]
        self._save_history(history)
        return report

    def latest_report(self) -> Dict[str, Any]:
        history = self._load_history()
        if not history:
            return self.run_check()
        return history[-1]


quality_service = QualityService()
