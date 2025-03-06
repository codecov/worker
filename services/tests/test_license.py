from datetime import datetime

from database.tests.factories import OwnerFactory, RepositoryFactory
from services.license import (
    InvalidLicenseReason,
    calculate_reason_for_not_being_valid,
    has_valid_license,
    is_properly_licensed,
    requires_license,
)


class TestLicenseService(object):
    def test_is_properly_licensed_doesnt_require_license(self, dbsession, mocker):
        mocker.patch("services.license.requires_license", return_value=False)
        mocker.patch("services.license.has_valid_license", return_value=False)
        assert is_properly_licensed(dbsession)

    def test_is_properly_licensed_requires_license_doesnt_have_it(
        self, dbsession, mocker
    ):
        mocker.patch("services.license.requires_license", return_value=True)
        mocker.patch("services.license.has_valid_license", return_value=False)
        assert not is_properly_licensed(dbsession)

    def test_is_properly_licensed_requires_license_has_it(self, dbsession, mocker):
        mocker.patch("services.license.requires_license", return_value=True)
        mocker.patch("services.license.has_valid_license", return_value=True)
        assert is_properly_licensed(dbsession)

    def test_requires_license(self, mocker):
        mocker.patch("services.license.is_enterprise", return_value=True)
        assert requires_license()
        mocker.patch("services.license.is_enterprise", return_value=False)
        assert not requires_license()

    def test_has_valid_license(self, dbsession, mocker):
        mocked_reason = mocker.patch(
            "services.license.reason_for_not_being_valid", return_value=None
        )
        assert has_valid_license(dbsession)
        mocked_reason.assert_called_with(dbsession)
        mocker.patch(
            "services.license.reason_for_not_being_valid", return_value="something"
        )
        assert not has_valid_license(dbsession)
        mocked_reason.assert_called_with(dbsession)

    def test_calculate_reason_for_not_being_valid_no_license(
        self, dbsession, mock_configuration
    ):
        assert (
            calculate_reason_for_not_being_valid(dbsession)
            == InvalidLicenseReason.invalid
        )

    def test_calculate_reason_for_not_being_valid_bad_url(
        self, dbsession, mock_configuration
    ):
        encrypted_license = "0dRbhbzp8TVFQp7P4e2ES9lSfyQlTo8J7LQ/N51yeAE/KcRBCnU+QsVvVMDuLL4xNGXGGk9p4ZTmIl0II3cMr0tIoPHe9Re2UjommalyFYuP8JjjnNR/Ql2DnjOzEnTzsE2Poq9xlNHcIU4F9gC2WOYPnazR6U+t4CelcvIAbEpbOMOiw34nVyd3OEmWusquMNrwkNkk/lwjwCJmj6bTXQ=="
        mock_configuration.params["setup"]["enterprise_license"] = encrypted_license
        mock_configuration.params["setup"]["codecov_url"] = "https://bad.site.org"
        assert (
            calculate_reason_for_not_being_valid(dbsession)
            == InvalidLicenseReason.url_mismatch
        )

    def test_calculate_reason_for_not_being_valid_simple_license(
        self, dbsession, mock_configuration, mocker
    ):
        mocker.patch("services.license._get_now", return_value=datetime(2020, 4, 2))
        encrypted_license = "0dRbhbzp8TVFQp7P4e2ES9lSfyQlTo8J7LQ/N51yeAE/KcRBCnU+QsVvVMDuLL4xNGXGGk9p4ZTmIl0II3cMr0tIoPHe9Re2UjommalyFYuP8JjjnNR/Ql2DnjOzEnTzsE2Poq9xlNHcIU4F9gC2WOYPnazR6U+t4CelcvIAbEpbOMOiw34nVyd3OEmWusquMNrwkNkk/lwjwCJmj6bTXQ=="
        mock_configuration.params["setup"]["enterprise_license"] = encrypted_license
        mock_configuration.params["setup"]["codecov_url"] = "https://codeov.mysite.com"
        assert calculate_reason_for_not_being_valid(dbsession) is None

    def test_calculate_reason_for_not_being_valid_too_many_owners(
        self, dbsession, mock_configuration
    ):
        for i in range(11):
            owner = OwnerFactory.create(
                service="github", username=f"test_calculate_reason_{i}"
            )
            dbsession.add(owner)
        dbsession.flush()
        encrypted_license = "0dRbhbzp8TVFQp7P4e2ES9lSfyQlTo8J7LQ/N51yeAE/KcRBCnU+QsVvVMDuLL4xNGXGGk9p4ZTmIl0II3cMr0tIoPHe9Re2UjommalyFYuP8JjjnNR/Ql2DnjOzEnTzsE2Poq9xlNHcIU4F9gC2WOYPnazR6U+t4CelcvIAbEpbOMOiw34nVyd3OEmWusquMNrwkNkk/lwjwCJmj6bTXQ=="
        mock_configuration.params["setup"]["enterprise_license"] = encrypted_license
        mock_configuration.params["setup"]["codecov_url"] = "https://codeov.mysite.com"
        assert (
            calculate_reason_for_not_being_valid(dbsession)
            == InvalidLicenseReason.users_exceeded
        )

    def test_calculate_reason_for_not_being_valid_too_many_plan_activated_users(
        self, dbsession, mock_configuration
    ):
        org_owner = OwnerFactory.create(
            service="github", oauth_token=None, plan_activated_users=list(range(1, 12))
        )
        dbsession.add(org_owner)
        dbsession.flush()
        encrypted_license = "wxWEJyYgIcFpi6nBSyKQZQeaQ9Eqpo3SXyUomAqQOzOFjdYB3A8fFM1rm+kOt2ehy9w95AzrQqrqfxi9HJIb2zLOMOB9tSy52OykVCzFtKPBNsXU/y5pQKOfV7iI3w9CHFh3tDwSwgjg8UsMXwQPOhrpvl2GdHpwEhFdaM2O3vY7iElFgZfk5D9E7qEnp+WysQwHKxDeKLI7jWCnBCBJLDjBJRSz0H7AfU55RQDqtTrnR+rsLDHOzJ80/VxwVYhb"
        mock_configuration.params["setup"]["enterprise_license"] = encrypted_license
        mock_configuration.params["setup"]["codecov_url"] = "https://codecov.mysite.com"
        assert (
            calculate_reason_for_not_being_valid(dbsession)
            == InvalidLicenseReason.users_exceeded
        )

    def test_calculate_reason_for_not_being_valid_repos_exceeded(
        self, dbsession, mock_configuration
    ):
        # number of max repos is 20
        owner = OwnerFactory.create(service="github")
        dbsession.add(owner)
        dbsession.flush()
        for i in range(21):
            repo = RepositoryFactory.create(updatestamp=datetime.now(), owner=owner)
            dbsession.add(repo)
        dbsession.flush()
        encrypted_license = "0dRbhbzp8TVFQp7P4e2ES9lSfyQlTo8J7LQ/N51yeAE/KcRBCnU+QsVvVMDuLL4xNGXGGk9p4ZTmIl0II3cMr0tIoPHe9Re2UjommalyFYuP8JjjnNR/Ql2DnjOzEnTzsE2Poq9xlNHcIU4F9gC2WOYPnazR6U+t4CelcvIAbEpbOMOiw34nVyd3OEmWusquMNrwkNkk/lwjwCJmj6bTXQ=="
        mock_configuration.params["setup"]["enterprise_license"] = encrypted_license
        mock_configuration.params["setup"]["codecov_url"] = "https://codeov.mysite.com"
        assert (
            calculate_reason_for_not_being_valid(dbsession)
            == InvalidLicenseReason.repos_exceeded
        )

    def test_calculate_reason_for_not_being_valid_repos_warning(
        self, dbsession, mock_configuration, mocker
    ):
        mocker.patch("services.license._get_now", return_value=datetime(2020, 4, 2))
        # number of max repos is 20
        owner = OwnerFactory.create(service="github")
        dbsession.add(owner)
        dbsession.flush()
        for i in range(18):
            repo = RepositoryFactory.create(updatestamp=datetime.now(), owner=owner)
            dbsession.add(repo)
        dbsession.flush()
        encrypted_license = "0dRbhbzp8TVFQp7P4e2ES9lSfyQlTo8J7LQ/N51yeAE/KcRBCnU+QsVvVMDuLL4xNGXGGk9p4ZTmIl0II3cMr0tIoPHe9Re2UjommalyFYuP8JjjnNR/Ql2DnjOzEnTzsE2Poq9xlNHcIU4F9gC2WOYPnazR6U+t4CelcvIAbEpbOMOiw34nVyd3OEmWusquMNrwkNkk/lwjwCJmj6bTXQ=="
        mock_configuration.params["setup"]["enterprise_license"] = encrypted_license
        mock_configuration.params["setup"]["codecov_url"] = "https://codeov.mysite.com"
        assert calculate_reason_for_not_being_valid(dbsession) is None

    def test_calculate_reason_for_not_being_valid_expired(
        self, dbsession, mock_configuration, mocker
    ):
        mocker.patch("services.license._get_now", return_value=datetime(2021, 10, 11))
        owner = OwnerFactory.create(service="github")
        dbsession.add(owner)
        dbsession.flush()
        for i in range(18):
            repo = RepositoryFactory.create(updatestamp=datetime.now(), owner=owner)
            dbsession.add(repo)
        dbsession.flush()
        encrypted_license = "0dRbhbzp8TVFQp7P4e2ES9lSfyQlTo8J7LQ/N51yeAE/KcRBCnU+QsVvVMDuLL4xNGXGGk9p4ZTmIl0II3cMr0tIoPHe9Re2UjommalyFYuP8JjjnNR/Ql2DnjOzEnTzsE2Poq9xlNHcIU4F9gC2WOYPnazR6U+t4CelcvIAbEpbOMOiw34nVyd3OEmWusquMNrwkNkk/lwjwCJmj6bTXQ=="
        mock_configuration.params["setup"]["enterprise_license"] = encrypted_license
        mock_configuration.params["setup"]["codecov_url"] = "https://codeov.mysite.com"
        assert (
            calculate_reason_for_not_being_valid(dbsession)
            == InvalidLicenseReason.expired
        )
