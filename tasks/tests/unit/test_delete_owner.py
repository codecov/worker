import json
from pathlib import Path
from asyncio import Future

import pytest

from tasks.delete_owner import DeleteOwnerTask
from database.tests.factories import OwnerFactory
from database.models import Owner

here = Path(__file__)

class TestDeleteOwnerTaskUnit(object):

    @pytest.mark.asyncio
    async def test_unknown_owner(self, mocker, mock_configuration, dbsession):
        unknown_ownerid = 10404
        with pytest.raises(AssertionError, match='Owner not found'):
            await DeleteOwnerTask().run_async(
                dbsession,
                unknown_ownerid
            )
