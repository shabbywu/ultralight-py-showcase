"""Explicit capability surface; no arbitrary Python or filesystem exposure."""
def register(api,controller):
    for name in ('choose_midi','choose_midi_folder','open_midi_folder','get_midi_library','open_path','begin_load','get_job','cancel_job','get_score','get_notes','get_overview',
                 'play','pause','stop','seek','configure','preview_hands','apply_hands','undo_hands','set_loop',
                 'set_volume','get_transport','get_analysis','retry_audio',
                 'begin_notation','get_notation_job','cancel_notation_job','apply_notation','get_notation','get_notation_page','get_notation_preview','get_notation_warnings','get_key_suggestion',
                 'choose_score_export','begin_score_export'):
        api.register(getattr(controller,name))
    api.register_object('session',controller.session,members=['phase','score_id','revision','generation','ready','hand_status'])
