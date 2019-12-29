from decimal import Decimal

from services.notification.notifiers.gitter import GitterNotifier


class TestGitterkNotifier(object):

    def test_build_payload_without_special_config(self, dbsession, mock_configuration, sample_comparison):
        mock_configuration.params['setup']['codecov_url'] = 'test.example.br'
        comparison = sample_comparison
        notifier = GitterNotifier(
            repository=sample_comparison.head.commit.repository,
            title='title',
            notifier_yaml_settings={},
            notifier_site_settings=True,
            current_yaml={}
        )
        result = notifier.build_payload(comparison)
        commit = comparison.head.commit
        repository = commit.repository
        text = f"Coverage for <test.example.br/gh/{repository.slug}/commit/{commit.commitid}|{repository.slug}> *increased* +10.00% on `new_branch` is `60.00000%` via `<test.example.br/gh/{repository.slug}/commit/{commit.commitid}|{commit.commitid[:7]}>`"
        expected_result = {
            'message': text,
            "branch": 'new_branch',
            "pr": comparison.pull.pullid,
            "commit": commit.commitid,
            "commit_short": commit.commitid[:7],
            "text": 'increased',
            "commit_url": f'https://github.com/{repository.slug}/commit/{commit.commitid}',
            "codecov_url": f'test.example.br/gh/{repository.slug}/commit/{commit.commitid}',
            "coverage": '60.00000',
            "coverage_change": Decimal('10.00'),
        }
        assert result['message'] == expected_result['message']
        assert result == expected_result

    def test_build_paylost_without_base_report(self):
        # TODO (Thiago): Write
        pass
