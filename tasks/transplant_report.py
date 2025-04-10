from app import celery_app
from services.report.transplant import transplant_commit_report
from tasks.base import BaseCodecovTask


class TransplantReportTask(BaseCodecovTask, name="app.tasks.reports.transplant_report"):
    def run_impl(self, db_session, repo_id: int, from_sha: str, to_sha: str):
        transplant_commit_report(repo_id, from_sha, to_sha)


RegisteredTransplantReportTask = celery_app.register_task(TransplantReportTask())
transplant_report_task = celery_app.tasks[RegisteredTransplantReportTask.name]
