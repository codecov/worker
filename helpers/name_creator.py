import uuid


class NameCreator:
    def __init__(self):
        self.curr_uuid = ""
        self.curr_idx = 0

    def create(self) -> str:
        if self.curr_idx == 0:
            self.curr_uuid = uuid.uuid4().hex
        low = self.curr_idx * 8
        high = low + 8
        result = self.curr_uuid[low:high]
        self.curr_idx += 1
        self.curr_idx %= 4
        return result


global_name_creator = NameCreator()
