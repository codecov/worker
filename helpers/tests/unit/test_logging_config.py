from helpers.logging_config import CustomLocalJsonFormatter, get_logging_config_dict, config_dict


class TestLoggingConfig(object):

    def test_local_formatter(self):
        log_record = {'levelname': 'weird_level', 'message': 'This is a message'}
        cljf = CustomLocalJsonFormatter()
        res = cljf.jsonify_log_record(log_record)
        assert 'weird_level: This is a message --- {}' == res

    def test_local_formatter_with_exc_info(self):
        log_record = {
            'levelname': 'weird_level',
            'message': 'This is a message',
            'exc_info': 'Line\nWith\nbreaks'
        }
        cljf = CustomLocalJsonFormatter()
        res = cljf.jsonify_log_record(log_record)
        assert 'weird_level: This is a message --- {}\nLine\nWith\nbreaks' == res

    def test_get_logging_config_dict(self):
        assert get_logging_config_dict() == config_dict
