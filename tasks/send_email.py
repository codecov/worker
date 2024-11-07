import logging

from shared.celery_config import send_email_task_name
from shared.config import get_config

import services.smtp
from app import celery_app
from helpers.email import Email
from helpers.metrics import metrics
from services.template import TemplateService
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class SendEmailTask(BaseCodecovTask, name=send_email_task_name):
    def run_impl(
        self, db_session, to_addr, subject, template_name, from_addr=None, **kwargs
    ):
        with metrics.timer("worker.tasks.send_email"):
            if from_addr is None:
                from_addr = get_config(
                    "services", "smtp", "from_address", default="noreply@codecov.io"
                )

            log_extra_dict = {
                "to_addr": to_addr,
                "from_addr": from_addr,
                "template_name": template_name,
                "template_kwargs": kwargs,
            }

            log.info(
                "Received send email task",
                extra=log_extra_dict,
            )

            smtp_service = services.smtp.SMTPService()

            if not smtp_service.active():
                log.warning(
                    "Cannot send email because SMTP is not configured for this installation of codecov"
                )
                return {
                    "email_successful": False,
                    "err_msg": "Cannot send email because SMTP is not configured for this installation of codecov",
                }
            template_service = TemplateService()

            with metrics.timer("worker.tasks.send_email.render_templates"):
                text_template = template_service.get_template(f"{template_name}.txt")
                text = text_template.render(**kwargs)

                html_template = template_service.get_template(f"{template_name}.html")
                html = html_template.render(**kwargs)

            email_wrapper = Email(to_addr, from_addr, subject, text, html)

            err_msg = None
            metrics.incr("worker.tasks.send_email.attempt")
            with metrics.timer("worker.tasks.send_email.send"):
                try:
                    smtp_service.send(email_wrapper)
                except services.smtp.SMTPServiceError as exc:
                    err_msg = str(exc)

            if err_msg is not None:
                log.warning(f"Failed to send email: {err_msg}", extra=log_extra_dict)
                metrics.incr("worker.tasks.send_email.fail")
                return {"email_successful": False, "err_msg": err_msg}

            log.info("Sent email", extra=log_extra_dict)
            metrics.incr("worker.tasks.send_email.succeed")
            return {"email_successful": True, "err_msg": None}


RegisteredSendEmailTask = celery_app.register_task(SendEmailTask())
send_email = celery_app.tasks[RegisteredSendEmailTask.name]
