from email.message import EmailMessage


class Email:
    def __init__(
        self, to_addr=None, from_addr=None, subject=None, text=None, html=None
    ):
        self.message = EmailMessage()
        self.to_addr = to_addr
        self.from_addr = from_addr
        self.text = text
        self.html = html
        self.subject = subject

    @property
    def to_addr(self):
        return self.message["To"]

    @to_addr.setter
    def to_addr(self, val):
        self.message["To"] = val

    @property
    def from_addr(self):
        return self.message["From"]

    @from_addr.setter
    def from_addr(self, val):
        self.message["From"] = val

    @property
    def subject(self):
        return self.message["Subject"]

    @subject.setter
    def subject(self, val):
        self.message["Subject"] = val

    @property
    def text(self):
        return self.message.get_payload()[0]

    @text.setter
    def text(self, val):
        self.message.set_content(val)

    @property
    def html(self):
        return self.message.get_payload()[1]

    @html.setter
    def html(self, val):
        self.message.add_alternative(val, "text/html")
