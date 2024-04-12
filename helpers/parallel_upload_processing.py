import copy

from shared.utils.sessions import SessionType

from database.models.reports import Upload


# copied from shared/reports/resources.py Report.next_session_number()
def next_session_number(session_dict):
    start_number = len(session_dict)
    while start_number in session_dict or str(start_number) in session_dict:
        start_number += 1
    return start_number


# copied and cut down from worker/services/report/raw_upload_processor.py
# this version stripped out all the ATS label stuff
def _adjust_sessions(
    original_sessions: dict,
    to_merge_flags,
    current_yaml,
):
    session_ids_to_fully_delete = []
    flags_under_carryforward_rules = [
        f for f in to_merge_flags if current_yaml.flag_has_carryfoward(f)
    ]
    if flags_under_carryforward_rules:
        for sess_id, curr_sess in original_sessions.items():
            if curr_sess.session_type == SessionType.carriedforward:
                if curr_sess.flags:
                    if any(
                        f in flags_under_carryforward_rules for f in curr_sess.flags
                    ):
                        session_ids_to_fully_delete.append(sess_id)
    if session_ids_to_fully_delete:
        # delete sessions from dict
        for id in session_ids_to_fully_delete:
            original_sessions.pop(id, None)
    return


def get_parallel_session_ids(
    sessions, argument_list, db_session, report_service, commit_yaml
):
    num_sessions = len(argument_list)

    mock_sessions = copy.deepcopy(sessions)  # the sessions already in the report
    get_parallel_session_ids = []

    # iterate over all uploads, get the next session id, and adjust sessions (remove CFF logic)
    for i in range(num_sessions):
        next_session_id = next_session_number(mock_sessions)

        upload_pk = argument_list[i]["upload_pk"]
        upload = db_session.query(Upload).filter_by(id_=upload_pk).first()
        to_merge_session = report_service.build_session(upload)
        flags = upload.flag_names

        mock_sessions[next_session_id] = to_merge_session
        _adjust_sessions(mock_sessions, flags, commit_yaml)

        get_parallel_session_ids.append(next_session_id)

    return get_parallel_session_ids
