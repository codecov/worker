from uuid import uuid4

from services.processing.state import (
    ProcessingState,
    should_perform_merge,
    should_trigger_postprocessing,
)


def test_single_upload():
    state = ProcessingState(1234, uuid4().hex)
    state.mark_uploads_as_processing([1])

    state.mark_upload_as_processed(1)

    # this is the only in-progress upload, nothing more to expect
    assert should_perform_merge(state.get_upload_numbers())

    assert state.get_uploads_for_merging() == {1}
    state.mark_uploads_as_merged([1])

    assert should_trigger_postprocessing(state.get_upload_numbers())


def test_concurrent_uploads():
    state = ProcessingState(1234, uuid4().hex)
    state.mark_uploads_as_processing([1])

    state.mark_upload_as_processed(1)
    # meanwhile, another upload comes in:
    state.mark_uploads_as_processing([2])

    # not merging/postprocessing yet, as that will be debounced with the second upload
    assert not should_perform_merge(state.get_upload_numbers())

    state.mark_upload_as_processed(2)

    assert should_perform_merge(state.get_upload_numbers())

    assert state.get_uploads_for_merging() == {1, 2}
    state.mark_uploads_as_merged([1, 2])

    assert should_trigger_postprocessing(state.get_upload_numbers())


def test_batch_merging_many_uploads():
    state = ProcessingState(1234, uuid4().hex)

    state.mark_uploads_as_processing([1, 2, 3, 4, 5, 6, 7, 8, 9])

    for id in range(1, 9):
        state.mark_upload_as_processed(id)

    # we have only processed 8 out of 9. we want to do a batched merge
    assert should_perform_merge(state.get_upload_numbers())
    merging = state.get_uploads_for_merging()
    assert len(merging) == 5  # = MERGE_BATCH_SIZE
    state.mark_uploads_as_merged(merging)

    # but no notifications yet
    assert not should_trigger_postprocessing(state.get_upload_numbers())

    state.mark_upload_as_processed(9)

    # with the last upload being processed, we do another merge, and then trigger notifications
    assert should_perform_merge(state.get_upload_numbers())
    merging = state.get_uploads_for_merging()
    assert len(merging) == 4
    state.mark_uploads_as_merged(merging)

    assert should_trigger_postprocessing(state.get_upload_numbers())
