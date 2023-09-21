import logging
from smtplib import SMTPDataError, SMTPRecipientsRefused, SMTPSenderRefused

from shared.celery_config import send_email_task_name

from app import celery_app
from database.models import Owner
from helpers.email import Email
from helpers.metrics import metrics
from services.smtp import get_smtp_service
from services.template import get_template_service
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class SendEmailTask(BaseCodecovTask):
    name = send_email_task_name

    async def run_async(
        self, db_session, ownerid, template_name, from_addr, subject, **kwargs
    ):
        with metrics.timer("worker.tasks.send_email"):
            log_extra_dict = {
                "from_addr": from_addr,
                "template_name": template_name,
                "template_kwargs": kwargs,
                "ownerid": ownerid,
            }

            log.info(
                "Received send email task",
                extra=log_extra_dict,
            )

            owners = db_session.query(Owner).filter_by(ownerid=ownerid)
            owner = owners.first()
            if not owner:
                log.error(
                    "Unable to find owner",
                    extra=log_extra_dict,
                )
                return None
            to_addr = owner.email

            smtp_service = get_smtp_service()
            if smtp_service is None:
                log.warning(
                    "Cannot send email because SMTP is not configured for this installation of codecov."
                )
                return None
            template_service = get_template_service()

            with metrics.timer("worker.tasks.send_email.render_templates"):
                text = template_service.get_template(f"{template_name}.txt", **kwargs)
                html = template_service.get_template(f"{template_name}.html", **kwargs)

            email_wrapper = Email(to_addr, from_addr, subject, text, html)

            err_msg = None
            try:
                metrics.incr(f"worker.tasks.send_email.attempt")
                with metrics.timer("worker.tasks.send_email.send"):
                    errs = smtp_service.send(email_wrapper)
                if len(errs) != 0:
                    err_msg = " ".join(
                        list(
                            map(
                                lambda err_tuple: f"{err_tuple[0]} {err_tuple[1]}", errs
                            )
                        )
                    )
            except SMTPRecipientsRefused:
                err_msg = "All recipients were refused"
            except SMTPSenderRefused:
                err_msg = "Sender was refused"
            except SMTPDataError:
                err_msg = "The SMTP server did not accept the data"

            if err_msg is not None:
                log.warning(f"Failed to send email: {err_msg}", extra=log_extra_dict)
                metrics.incr(f"worker.tasks.send_email.fail")
                return {"email_successful": False, "err_msg": err_msg}

            log.info("Sent email", extra=log_extra_dict)
            metrics.incr(f"worker.tasks.send_email.succeed")
            return {"email_successful": True, "err_msg": None}


RegisteredSendEmailTask = celery_app.register_task(SendEmailTask())
send_email = celery_app.tasks[RegisteredSendEmailTask.name]
