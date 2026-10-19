"""Finite score-path expansion, exact tempo integration and sounding instances."""
from dataclasses import dataclass, field
from fractions import Fraction as Q
from collections import defaultdict
import bisect
import hashlib
import json
from .score_source import fail


@dataclass
class PlaybackPlan:
    document: object
    occurrences: list
    instances: list
    tempos: list
    controls: list
    display_spans: list
    duration_qn: Q
    revision: str
    settings: dict
    midi_bytes: bytes = b''
    midi_event_map: list = field(default_factory=list)
    midi_precision: dict = field(default_factory=dict)
    diagnostics: list = field(default_factory=list)
    _tempo_qn: list = field(default_factory=list,repr=False)
    _tempo_seconds: list = field(default_factory=list,repr=False)

    def seconds(self, position):
        position = Q(position)
        if not self._tempo_qn:
            total=Q(0)
            for i,t in enumerate(self.tempos):
                if i:
                    before=self.tempos[i-1]
                    total+=(t['qn']-before['qn'])*60/before['bpm']
                self._tempo_qn.append(t['qn'])
                self._tempo_seconds.append(total)
        i=max(0,bisect.bisect_right(self._tempo_qn,position)-1)
        return self._tempo_seconds[i]+(position-self.tempos[i]['qn'])*60/self.tempos[i]['bpm']

    @property
    def duration_s(self):
        return float(self.seconds(self.duration_qn))

    def occurrence_at(self, seconds):
        index = bisect.bisect_right([o['start_s'] for o in self.occurrences], seconds) - 1
        return self.occurrences[max(0, index)]

    def qn_at_seconds(self, seconds):
        self.seconds(0)
        i=max(0,bisect.bisect_right(self._tempo_seconds,seconds)-1)
        t=self.tempos[i]
        return float(t['qn'])+max(0.,seconds-float(self._tempo_seconds[i]))*float(t['bpm'])/60

    def seek_target(self, element_id, seconds=0, occurrence_id=None):
        candidates = [s for s in self.display_spans if s['element_id'] == element_id]
        if not candidates:
            # Rests and measure anchors have no note-on, but still have occurrences.
            element = next((e for e in self.document.elements if e.id == element_id), None)
            uid = element.measure_uid if element else element_id
            candidates = [dict(occurrence_id=o['id'], element_id=element_id,
                               start_s=float(self.seconds(o['start_qn'] + (element.onset if element else 0))))
                          for o in self.occurrences if o['measure_uid'] == uid]
        if not candidates:
            fail('谱面元素不属于当前乐谱', code='SCORE_STALE')
        if occurrence_id:
            target = next((s for s in candidates if s['occurrence_id'] == occurrence_id), None)
            if target is None:
                fail('元素不在指定遍次内', code='SCORE_STALE')
        else:
            current = self.occurrence_at(seconds)['id']
            target = next((s for s in candidates if s['occurrence_id'] == current), None)
            target = target or next((s for s in candidates if s['start_s'] >= seconds), candidates[0])
        choices={}
        for span in candidates:
            choices.setdefault(span['occurrence_id'],dict(occurrence_id=span['occurrence_id'],position_s=span['start_s']))
        return dict(target, choices=list(choices.values()))


def expand_path(measures):
    """Non-nested repeat regions, with alternatives retained in written order."""
    regions, start, prior_end = [], None, -1
    for i, measure in enumerate(measures):
        if measure.forward:
            if start is not None:
                fail('首版不支持嵌套反复')
            start = i
        if measure.repeat_times:
            begin = start if start is not None else prior_end + 1
            if begin > i:
                fail('反复起点不明确')
            end = i
            while end + 1 < len(measures) and measures[end + 1].endings:
                end += 1
            regions.append((begin, i, end, measure.repeat_times))
            prior_end, start = end, None
    if start is not None:
        fail('前反复没有匹配后反复')
    for a, b in zip(regions, regions[1:]):
        if b[0] <= a[2]:
            fail('反复区域重叠／嵌套')
    by_start = {r[0]: r for r in regions}
    path, i = [], 0
    while i < len(measures):
        region = by_start.get(i)
        if region:
            begin, backward, end, times = region
            if times!=2 and any(measures[j].endings for j in range(begin,end+1)):
                fail('一／二结尾只能用于两遍反复；其他遍次路径不明确')
            for visit in range(1, times + 1):
                selected = [j for j in range(begin, end + 1)
                            if not measures[j].endings or visit in measures[j].endings]
                if not selected:
                    fail('反复遍次无可执行小节')
                path.extend(selected)
                if len(path) > 1024:
                    fail('展开超过 1,024 个小节出现', code='SCORE_LIMIT')
            i = end + 1
        else:
            if measures[i].endings:
                fail('结尾不属于明确反复区域')
            path.append(i)
            i += 1
    if len(path) > 1024:
        fail('展开超过 1,024 个小节出现', code='SCORE_LIMIT')
    return path


def performed_notes(measure, source, diagnostics):
    """Source-declared ornaments only; exact bounded events, no quantization."""
    def error(e, text):
        fail(text, source.locations[e.id]['source_locator'])
    arps = defaultdict(list)
    for e in measure.elements:
        if e.arpeggio:
            arps[(e.part_id, e.onset, e.arpeggio[0])].append(e)
    offsets = {}
    for group in arps.values():
        directions = {e.arpeggio[1] for e in group if e.arpeggio[1]}
        if len(directions) > 1:
            error(group[0], '同组琶音方向矛盾')
        group = sorted(group, key=lambda e: (e.pitch, e.id), reverse='down' in directions)
        # MusicXML declares order, not spread time. This documented playback
        # policy uses 1/16 quarter-note steps, capped to half the shortest note.
        step = min(Q(1, 16), min(e.duration for e in group) / (2 * len(group)))
        for i, e in enumerate(group):
            offsets[e.id] = i * step
        diagnostics.append(dict(code='ARPEGGIO_POLICY', message='琶音按源方向依次起音；间隔为 1/16 四分音符，短音时收窄，结束位置不延长', element_id=group[0].id,
                                source_locator=source.locations[group[0].id]['source_locator']))
    voices = defaultdict(list)
    for e in measure.elements:
        voices[(e.part_id, e.voice_id)].append(e)
    strokes, consumed = {}, set()
    for elements in voices.values():
        clusters = defaultdict(list)
        for e in elements:
            clusters[e.onset].append(e)
        groups = [clusters[q] for q in sorted(clusters)]
        def signature(group):
            marks = {e.tremolo for e in group if e.tremolo}
            if len(marks) > 1:
                error(group[0], '同一和弦震音记号矛盾')
            return next(iter(marks), None)
        for i, group in enumerate(groups):
            e = group[0]
            spec = signature(group)
            if not spec or e.id in consumed:
                continue
            kind, marks, step = spec
            endpoints = [group]
            if kind == 'start' and i + 1 < len(groups):
                other = groups[i + 1]
                if signature(other) != ('stop', marks, step) or other[0].onset != e.onset + e.duration:
                    error(e, '成对震音需同小节同声部相邻且划数一致')
                endpoints.append(other)
            elif kind != 'single':
                error(e, '震音 start／stop 缺少同小节配对')
            members = [n for endpoint in endpoints for n in endpoint]
            if any(n.pitch is None or n.duration != e.duration or n.tie_start or n.tie_stop or n.arpeggio or n.cue or n.staccato for n in members):
                error(e, '震音需等时值的明确音高；与 tie／琶音／cue／staccato 的组合尚未验证')
            length = e.duration * len(endpoints)
            if length % step:
                error(e, '震音时长不是明确击奏间隔的整数倍')
            count = int(length / step)
            if count * max(map(len, endpoints)) > 20_000:
                error(e, '震音展开超过 20,000')
            consumed.update(n.id for n in members if n.id != e.id)
            strokes[e.id] = [(n, e.onset + j * step, e.onset + (j + 1) * step)
                             for j in range(count) for n in endpoints[j % len(endpoints)]]
    result = []
    for e in measure.elements:
        if e.id in consumed:
            continue
        if e.id in strokes:
            result.extend(strokes[e.id])
        else:
            result.append((e, e.onset + offsets.get(e.id, 0), e.onset + e.duration))
        if len(result) > 20_000:
            error(e, '展开音符超过 20,000')
    return sorted(result, key=lambda item: item[1])


def compile_plan(document, settings=None, cancelled=lambda: False):
    settings = dict(settings or {})
    if document.needs_confirmation:
        fail('播放参数需要确认：' + '；'.join(document.needs_confirmation.values()), code='SCORE_CONFIRMATION')
    signature = json.dumps(settings, sort_keys=True, ensure_ascii=False)
    revision = hashlib.sha256((document.revision + ':playback-v2:' + signature).encode()).hexdigest()[:24]
    plan = PlaybackPlan(document, [], [], [], [], [], Q(0), revision, settings)
    plan.diagnostics=list(document.diagnostics)
    # State at each written measure boundary. A jump restores that boundary state;
    # it must not inherit a velocity/pedal/tempo from an unrelated prior visit.
    tempo = Q(str(settings.get('default_tempo', 120)))
    velocities = {p['id']: 80 for p in document.parts}
    pedals = {p['id']: 0 for p in document.parts}
    entry_states = []
    def resolved(directions):
        grouped = defaultdict(list)
        for d in directions:
            kind = 'velocity' if d['kind'] == 'dynamics' else d['kind']
            scope = 'global' if kind == 'tempo' else d['scope'].split(':')[0]
            value = max(1, min(127, round(d['value'] * Q(90, 100)))) if d['kind'] == 'dynamics' else d['value']
            grouped[(d['onset'], kind, scope)].append(dict(d, value=value))
        result = []
        for (onset, kind, scope), group in grouped.items():
            priority = max(d['priority'] for d in group)
            group = [d for d in group if d['priority'] == priority]
            values = {d['value'] for d in group}
            if len(values) > 1 and kind == 'tempo' and len({d['scope'] for d in group}) == 1:
                location = document.source.locations.get(group[-1]['element_id'], {}).get('source_locator', '')
                plan.diagnostics.append(dict(code='TEMPO_SOURCE_ORDER', message='同谱表同位置有多个速度命令，按源顺序采用最后一个：'+str(group[-1]['value'])+' BPM', source_locator=location))
                group, values = group[-1:], {group[-1]['value']}
            # A pedal change deliberately has two events in source order.
            if len(values) > 1 and not (kind == 'damper-pedal' and len({d['element_id'] for d in group}) == 1):
                fail('同位置同优先级播放参数冲突',document.source.locations.get(group[0]['element_id'],{}).get('source_locator',''))
            for d in group if kind == 'damper-pedal' else group[:1]:
                result.append(dict(onset=onset, kind=kind, scope=scope, value=d['value']))
        return sorted(result, key=lambda d: d['onset'])
    resolved_measures = []
    for measure in document.measures:
        entry_states.append((tempo, dict(velocities), dict(pedals)))
        directions = resolved(measure.directions)
        resolved_measures.append(directions)
        for d in directions:
            if d['kind'] == 'tempo':
                tempo = d['value']
            elif d['kind'] == 'velocity':
                velocities[d['scope']] = int(d['value'])
            elif d['kind'] == 'damper-pedal':
                pedals[d['scope']] = round(d['value'] * Q(127, 100))
    visits, pending = defaultdict(int), {}
    previous_written = None
    previous_end = Q(0)
    for ordinal, mi in enumerate(expand_path(document.measures)):
        if cancelled():
            raise InterruptedError('已取消')
        measure = document.measures[mi]
        visits[mi] += 1
        occ_id = f'o{ordinal + 1}'
        base = plan.duration_qn
        occ = dict(id=occ_id, measure_uid=measure.id, written_index=mi, number=measure.number,
                   visit_index=visits[mi], start_qn=base, end_qn=base + measure.length)
        plan.occurrences.append(occ)
        jump = previous_written is None or mi != previous_written + 1
        if jump:
            tempo, velocities, pedals = entry_states[mi]
            velocities, pedals = dict(velocities), dict(pedals)
            plan.tempos.append(dict(qn=base, bpm=tempo))
            for pid, value in pedals.items():
                plan.controls.append(dict(qn=base, part_id=pid, control=64, value=value))
        local = resolved_measures[mi]
        for d in local:
            if d['kind'] == 'tempo':
                plan.tempos.append(dict(qn=base + d['onset'], bpm=d['value']))
            elif d['kind'] == 'damper-pedal':
                plan.controls.append(dict(qn=base + d['onset'], part_id=d['scope'], control=64,
                                          value=round(d['value'] * Q(127, 100))))
        # Tie matching follows exact adjacency in the actual expanded path. Staff
        # is intentionally absent from the key, so a voice can cross staves.
        for e, performed_on, performed_off in performed_notes(measure, document.source, plan.diagnostics):
            if e.pitch is None or e.cue:
                continue
            on, off = base + performed_on, base + performed_off
            key = (e.part_id, e.voice_id, e.pitch, e.tie_number)
            candidates = pending.get(key, [])
            match = [n for n in candidates if n['key_off_qn'] == on] if e.tie_stop else []
            if len(match) > 1:
                fail('同声部同音高延音链存在歧义', code='SCORE_TIE')
            if match:
                note = match[0]
                candidates.remove(note)
                note['key_off_qn'] = off
                note['element_ids'].append(e.id)
                note['occurrence_ids'].append(occ_id)
            else:
                if e.tie_stop:
                    plan.diagnostics.append(dict(code='TIE_PATH_REARTICULATION', message='实际路径没有相邻 tie 起点，此段重新起音', element_id=e.id))
                velocity = velocities[e.part_id]
                for d in local:
                    if d['kind'] == 'velocity' and d['scope'] == e.part_id and d['onset'] <= performed_on:
                        velocity = int(d['value'])
                if e.velocity_override is not None:
                    velocity=e.velocity_override
                if e.staccato and not (e.tie_start or e.tie_stop):
                    off = on + e.duration / 2
                note = dict(id=f'i{len(plan.instances) + 1}', element_ids=[e.id], occurrence_ids=[occ_id],
                            onset_qn=on, key_off_qn=off, pitch=e.pitch, velocity=velocity,
                            staff_id=e.staff_id, voice_id=e.voice_id, part_id=e.part_id,
                            hand='unassigned', hand_source='unknown')
                plan.instances.append(note)
                if len(plan.instances) > 20_000:
                    fail('展开音符超过 20,000', code='SCORE_LIMIT')
            if e.tie_start:
                pending.setdefault(key, []).append(note)
            plan.display_spans.append(dict(instance_id=note['id'], element_id=e.id,
                                           occurrence_id=occ_id, start_qn=on,
                                           end_qn=min(base + performed_off, note['key_off_qn'])))
        # Preserve final control state on contiguous written measures.
        for d in local:
            if d['kind'] == 'tempo':
                tempo = d['value']
            elif d['kind'] == 'velocity':
                velocities[d['scope']] = int(d['value'])
            elif d['kind'] == 'damper-pedal':
                pedals[d['scope']] = round(d['value'] * Q(127, 100))
        plan.duration_qn += measure.length
        previous_written, previous_end = mi, plan.duration_qn
    # At coincident boundary, last source event wins only after equal-priority
    # conflicts have already been rejected in resolved().
    tempos = {t['qn']: t for t in plan.tempos}
    plan.tempos = [tempos[q] for q in sorted(tempos)]
    if plan.duration_s > 600:
        fail('展开后基准曲长超过 600 秒', code='SCORE_LIMIT')
    for pid in pedals:
        plan.controls.append(dict(qn=plan.duration_qn, part_id=pid, control=64, value=0))
    plan.controls.sort(key=lambda c: c['qn'])
    for n in plan.instances:
        n['onset_s'] = float(plan.seconds(n['onset_qn']))
        n['key_off_s'] = float(plan.seconds(n['key_off_qn']))
        relevant = [c for c in plan.controls if c['part_id'] == n['part_id']]
        # SMF note-off precedes controllers at the same tick. A pedal press on
        # that boundary cannot retroactively sustain the released key.
        before = [c for c in relevant if c['qn'] < n['key_off_qn']]
        down = before[-1]['value'] >= 64 if before else False
        release = next((c['qn'] for c in relevant if c['qn'] >= n['key_off_qn'] and c['value'] < 64), plan.duration_qn)
        n['sustain_end_qn'] = release if down else n['key_off_qn']
        n['sustain_end_s'] = float(plan.seconds(n['sustain_end_qn']))
    for s in plan.display_spans:
        s['start_s'], s['end_s'] = float(plan.seconds(s['start_qn'])), float(plan.seconds(s['end_qn']))
    for o in plan.occurrences:
        o['start_s'], o['end_s'] = float(plan.seconds(o['start_qn'])), float(plan.seconds(o['end_qn']))
    return plan
