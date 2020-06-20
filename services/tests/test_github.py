from services.github import get_github_integration_token

# DONT WORRY, this is generated for the purposes of validation, and is not the real
# one on which the code ran
fake_private_key = """-----BEGIN RSA PRIVATE KEY-----
MIICXAIBAAKBgQDCFqq2ygFh9UQU/6PoDJ6L9e4ovLPCHtlBt7vzDwyfwr3XGxln
0VbfycVLc6unJDVEGZ/PsFEuS9j1QmBTTEgvCLR6RGpfzmVuMO8wGVEO52pH73h9
rviojaheX/u3ZqaA0di9RKy8e3L+T0ka3QYgDx5wiOIUu1wGXCs6PhrtEwICBAEC
gYBu9jsi0eVROozSz5dmcZxUAzv7USiUcYrxX007SUpm0zzUY+kPpWLeWWEPaddF
VONCp//0XU8hNhoh0gedw7ZgUTG6jYVOdGlaV95LhgY6yXaQGoKSQNNTY+ZZVT61
zvHOlPynt3GZcaRJOlgf+3hBF5MCRoWKf+lDA5KiWkqOYQJBAMQp0HNVeTqz+E0O
6E0neqQDQb95thFmmCI7Kgg4PvkS5mz7iAbZa5pab3VuyfmvnVvYLWejOwuYSp0U
9N8QvUsCQQD9StWHaVNM4Lf5zJnB1+lJPTXQsmsuzWvF3HmBkMHYWdy84N/TdCZX
Cxve1LR37lM/Vijer0K77wAx2RAN/ppZAkB8+GwSh5+mxZKydyPaPN29p6nC6aLx
3DV2dpzmhD0ZDwmuk8GN+qc0YRNOzzJ/2UbHH9L/lvGqui8I6WLOi8nDAkEA9CYq
ewfdZ9LcytGz7QwPEeWVhvpm0HQV9moetFWVolYecqBP4QzNyokVnpeUOqhIQAwe
Z0FJEQ9VWsG+Df0noQJBALFjUUZEtv4x31gMlV24oiSWHxIRX4fEND/6LpjleDZ5
C/tY+lZIEO1Gg/FxSMB+hwwhwfSuE3WohZfEcSy+R48=
-----END RSA PRIVATE KEY-----"""


class TestGithubSpecificLogic(object):
    def test_get_github_integration_token_enterprise(self, mocker, mock_configuration):
        service = "github_enterprise"
        mock_configuration._params[service] = {"url": "http://legit-github"}
        integration_id = 1
        mocked_post = mocker.patch("services.github.requests.post")
        mocked_post.return_value.json.return_value = {"token": "arriba"}
        mocker.patch("services.github.get_pem", return_value=fake_private_key)
        assert get_github_integration_token(service, integration_id) == "arriba"
        mocked_post.assert_called_with(
            "http://legit-github/api/v3/app/installations/1/access_tokens",
            headers={
                "Accept": "application/vnd.github.machine-man-preview+json",
                "Authorization": mocker.ANY,
                "User-Agent": "Codecov",
            },
        )

    def test_get_github_integration_token_production(self, mocker, mock_configuration):
        service = "github"
        mock_configuration._params["github_enterprise"] = {"url": "http://legit-github"}
        integration_id = 1
        mocked_post = mocker.patch("services.github.requests.post")
        mocked_post.return_value.json.return_value = {"token": "arriba"}
        mocker.patch("services.github.get_pem", return_value=fake_private_key)
        assert get_github_integration_token(service, integration_id) == "arriba"
        mocked_post.assert_called_with(
            "https://api.github.com/app/installations/1/access_tokens",
            headers={
                "Accept": "application/vnd.github.machine-man-preview+json",
                "Authorization": mocker.ANY,
                "User-Agent": "Codecov",
            },
        )
