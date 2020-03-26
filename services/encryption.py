import os

from covreports.config import get_config

from covreports.encryption import StandardEncryptor


first_part = get_config("setup", "encryption_secret", default="")
second_part = os.getenv("ENCRYPTION_SECRET", "")
third_part = "fYaA^Bj&h89,hs49iXyq]xARuCg"


encryptor = StandardEncryptor(first_part, second_part, third_part)
