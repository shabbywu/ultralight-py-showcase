"""Standard MIDI File writer and the adapter for the existing sound engine."""
from fractions import Fraction as Q
from collections import defaultdict
from io import BytesIO
import math
import struct
from .midi import Note, Score
from .score_source import fail


def variable(value):
    if not 0 <= value <= 0x0fffffff:
        fail('MIDI delta tick 超出 SMF 范围', code='MIDI_PRECISION')
    output = [value & 127]
    while value >> 7:
        value >>= 7
        output.insert(0, (value & 127) | 128)
    return bytes(output)


def encode_track(events, end_tick):
    out, previous = bytearray(), 0
    for tick, priority, ordinal, data, _ in sorted(events, key=lambda e: e[:3]):
        out += variable(tick - previous) + data
        previous = tick
    out += variable(max(0, end_tick - previous)) + b'\xff\x2f\x00'
    return b'MTrk' + struct.pack('>I', len(out)) + out


def compile_midi(plan):
    positions = [plan.duration_qn]
    positions += [n[k] for n in plan.instances for k in ('onset_qn', 'key_off_qn')]
    positions += [t['qn'] for t in plan.tempos] + [c['qn'] for c in plan.controls]
    ppqn = 24
    for position in positions:
        ppqn = math.lcm(ppqn, Q(position).denominator)
        if ppqn > 32767:
            fail('有理数时间不能在 PPQN≤32,767 下精确编码', code='MIDI_PRECISION')
    slots, routes = {}, {}
    available = [i for i in range(16) if i != 9]
    for n in sorted(plan.instances, key=lambda n: (n['onset_qn'], n['id'])):
        ends = slots.setdefault((n['part_id'], n['pitch']), [])
        lane = next((i for i, end in enumerate(ends) if end <= n['onset_qn']), len(ends))
        if lane == len(ends):
            ends.append(n['sustain_end_qn'])
        else:
            ends[lane] = n['sustain_end_qn']
        key = (n['part_id'], lane)
        if key not in routes:
            if len(routes) == len(available):
                fail('同音重叠超过已验证 SMF 通道路由容量（15）', code='MIDI_ROUTING')
            routes[key] = available[len(routes)]
        n['midi_channel'] = routes[key]
    events, event_map = [], []
    def add(tick, priority, payload, record):
        ordinal = len(events)
        events.append((int(tick), priority, ordinal, payload, record))
        if record:
            event_map.append(dict(record, tick=int(tick)))
    errors = []
    for i, t in enumerate(plan.tempos):
        exact = Q(60_000_000) / t['bpm']
        encoded = round(exact)
        if not 1 <= encoded <= 0xffffff:
            fail('tempo 超出 SMF 表示范围', code='MIDI_PRECISION')
        end = plan.tempos[i + 1]['qn'] if i + 1 < len(plan.tempos) else plan.duration_qn
        errors.append(dict(qn=[t['qn'].numerator, t['qn'].denominator], microseconds=encoded,
                           microseconds_error=float(encoded - exact),
                           segment_seconds_error=float((end - t['qn']) * (encoded - exact) / 1_000_000)))
        add(t['qn'] * ppqn, 1, b'\xff\x51\x03' + encoded.to_bytes(3, 'big'), None)
    end_tick = int(plan.duration_qn * ppqn)
    tempo_track = encode_track(events, end_tick)
    events = []
    for channel in routes.values():
        add(0, -2, bytes((0xc0 | channel, 0)), None)
    for c in plan.controls:
        for (pid, lane), channel in routes.items():
            if c['part_id'] == pid:
                add(c['qn'] * ppqn, 1, bytes((0xb0 | channel, c['control'], c['value'])),
                    dict(kind='cc', channel=channel, control=c['control'], value=c['value']))
    for n in plan.instances:
        ch = n['midi_channel']
        for key, status, priority in (('onset_qn', 0x90, 2), ('key_off_qn', 0x80, 0)):
            kind = 'note_on' if status == 0x90 else 'note_off'
            add(n[key] * ppqn, priority, bytes((status | ch, n['pitch'], n['velocity'] if status == 0x90 else 0)),
                dict(kind=kind, instance_id=n['id'], channel=ch, pitch=n['pitch'], element_ids=n['element_ids']))
    note_track = encode_track(events, end_tick)
    plan.midi_bytes = b'MThd' + struct.pack('>IHHH', 6, 1, 2, ppqn) + tempo_track + note_track
    plan.midi_event_map = event_map
    plan.midi_precision = dict(ppqn=ppqn, tempos=errors, seconds_error_bound=sum(abs(e['segment_seconds_error']) for e in errors))
    return plan.midi_bytes


def sound_score(plan):
    """Typed data adaptation only. Never parse MIDI back into notation."""
    ppqn = plan.midi_precision['ppqn']
    tracks = [dict(id=p['id'], name=p['name'], source_channel=i, source_track=i,
                   note_count=sum(n['part_id'] == p['id'] for n in plan.instances), hand='unassigned')
              for i, p in enumerate(plan.document.parts)]
    channels = {t['id']: t['source_channel'] for t in tracks}
    notes = [Note(n['id'], n['part_id'], n['pitch'], n['velocity'], n['onset_s'], n['key_off_s'],
                  n['sustain_end_s'], n['hand'], n['hand_source'], int(n['onset_qn'] * ppqn),
                  int(n['key_off_qn'] * ppqn), '|'.join(n['element_ids'])) for n in plan.instances]
    controls = [dict(time_s=float(plan.seconds(c['qn'])), tick=int(c['qn'] * ppqn),
                     source_channel=channels[c['part_id']], control=c['control'], value=c['value'])
                for c in plan.controls]
    tempos = [dict(tick=int(t['qn'] * ppqn), time_s=float(plan.seconds(t['qn'])),
                   tempo=round(Q(60_000_000) / t['bpm']), bpm=float(t['bpm'])) for t in plan.tempos]
    meters = [dict(tick=int(o['start_qn'] * ppqn), numerator=plan.document.measures[o['written_index']].meter[0],
                   denominator=plan.document.measures[o['written_index']].meter[1]) for o in plan.occurrences]
    return Score(plan.document.title, plan.duration_s, tracks, notes, tempos, meters, controls,
                 warnings=[d['message'] for d in plan.document.diagnostics],
                 score_id=plan.revision, source_fingerprint=plan.document.source.sha256,
                 ppqn=ppqn, duration_tick=int(plan.duration_qn * ppqn))
