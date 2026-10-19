"""Explicit MusicXML-only binding surface. Filesystem paths remain in Python."""


def register(api, controller):
    for name in ('choose_score','choose_score_folder','get_score_library',
                 'begin_score_load','get_job','cancel_job','confirm_score_load','get_candidate',
                 'get_score_page','publish_score_load','get_document','get_capabilities','get_diagnostics',
                 'get_notes','get_overview','get_source_elements','get_practice_settings',
                 'play','pause','stop','seek','seek_score','configure','set_volume','set_loop',
                 'get_transport','get_analysis','preview_hands','apply_hands','undo_hands','retry_audio',
                 'choose_export','begin_export'):
        api.register(getattr(controller,name))
