from email.message import EmailMessage


class Email:
    def __init__(
        self, to_addr=None, from_addr=None, subject=None, text=None, html=None
    ):
        self.message = EmailMessage()
        self.message["To"] = to_addr
        self.message["From"] = from_addr
        self.message["Subject"] = subject
        self.message.set_content(text)
        if html:
            self.message.add_alternative(html, "html")
