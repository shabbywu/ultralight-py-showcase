"""Exact score semantics. No MIDI import, quantization or inferred notation."""
from dataclasses import dataclass, field
from fractions import Fraction as Q
import hashlib
import re
import xml.etree.ElementTree as ET
from .score_source import fail

UNITS = {'whole': Q(4), 'half': Q(2), 'quarter': Q(1), 'eighth': Q(1, 2),
         '16th': Q(1, 4), '32nd': Q(1, 8), '64th': Q(1, 16)}
METERS = {(2, 4), (3, 4), (4, 4), (3, 8), (6, 8), (9, 8), (12, 8)}
DYNAMICS = dict(zip(('ppp', 'pp', 'p', 'mp', 'mf', 'f', 'ff', 'fff'), (24, 36, 48, 60, 76, 92, 108, 120)))
UNSUPPORTED = {'grace', 'unpitched', 'transpose', 'trill-mark', 'turn', 'inverted-turn',
               'mordent', 'inverted-mordent', 'tremolo', 'arpeggiate', 'swing', 'segno', 'coda',
               'senza-misura', 'multiple-rest', 'measure-repeat', 'slash', 'scordatura'}
UNSUPPORTED.update({'delayed-turn','delayed-inverted-turn','vertical-turn','inverted-vertical-turn',
                    'schleifer','shake','haydn','other-ornament','glissando','slide','bend',
                    'hammer-on','pull-off','breath-mark','caesura','play','listen','listening'})


@dataclass(frozen=True)
class ScoreElement:
    id: str
    measure_uid: str
    part_id: str
    staff_id: str
    voice_id: str
    onset: Q
    duration: Q
    pitch: int | None
    written_pitch: tuple | None
    tie_start: bool = False
    tie_stop: bool = False
    tie_number: str = '1'
    staccato: bool = False
    cue: bool = False
    visible: bool = True
    velocity_override: int | None = None


@dataclass
class Measure:
    id: str
    number: str
    length: Q
    meter: tuple
    elements: list = field(default_factory=list)
    directions: list = field(default_factory=list)
    forward: bool = False
    repeat_times: int = 0
    endings: tuple = ()


@dataclass
class ScoreDocument:
    source: object
    title: str
    parts: list
    measures: list
    diagnostics: list
    needs_confirmation: dict
    revision: str

    @property
    def elements(self):
        return [e for m in self.measures for e in m.elements]


def parse_score(source, settings=None, cancelled=lambda: False):
    settings = settings or {}
    root = ET.fromstring(source.working_xml)
    diagnostics = list(source.diagnostics)
    def error(node, message):
        fail(message, source.locations.get(node.get('_ps_id'), {}).get('source_locator', ''))
    for n in root.iter():
        if 'time-only' in n.attrib or n.tag=='note' and any(k in n.attrib for k in ('attack','release','pizzicato','end-dynamics')):
            error(n,'条件起音／额外演奏偏移不在首版执行范围')
        if n.tag=='tie' and n.get('type') not in ('start','stop'):
            error(n,'tie 的声音关系必须为 start／stop')
        if n.tag=='octave-shift' and n.get('size','8')!='8':
            error(n,'首版支持 8va／8vb')
        if n.tag in ('divisions','duration','offset','alter','octave','fifths','actual-notes','normal-notes') and not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)',(n.text or '').strip()):
            error(n,'音乐数值必须是 MusicXML 十进制数：'+n.tag)
        if n.tag=='words' and re.search(r'\bD\s*\.\s*[CS]\s*\.|\bal\s+(?:fine|coda)\b',n.text or '',re.I):
            error(n,'首版不执行 D.C.／D.S.／Fine／Coda 导航')
        if n.tag in UNSUPPORTED:
            if n.tag == 'transpose' and all(Q(c.text or '0') == 0 for c in n):
                continue
            error(n, '首版不能执行此记号：' + n.tag)
        if n.tag == 'sound' and any(k in n.attrib for k in ('dacapo', 'dalsegno', 'fine', 'tocoda', 'coda', 'segno', 'time-only', 'sostenuto-pedal', 'soft-pedal')):
            error(n, '首版不执行导航／条件播放或特殊踏板')
        if n.tag in ('fermata', 'wedge', 'accent', 'tenuto') or n.tag == 'words' and any(w in (n.text or '').lower() for w in ('rit', 'accel')):
            diagnostics.append(dict(code='DISPLAY_ONLY', message='仅显示，未额外改变声音：' + n.tag,
                                    source_locator=source.locations[n.get('id')]['source_locator']))
    part_nodes = root.findall('part')
    part_defs = {n.get('id'): n.findtext('part-name', '钢琴') for n in root.findall('part-list/score-part')}
    # Source part IDs are not remapped: references use the original part-list ID.
    if not 1 <= len(part_nodes) <= 2:
        error(root, '首版仅支持一个双谱表 part 或两个单谱表 part')
    needs = {}
    if len(part_nodes) == 2 and not settings.get('piano_group_confirmed'):
        needs['piano_group_confirmed'] = '请确认这两个分部组成同一钢琴组'
    combined, parts = [], []
    pitched = 0
    for pi, part in enumerate(part_nodes):
        pid = part.get('id')
        divisions = None
        meter = None
        staves = 1
        active_endings = ()
        nodes = part.findall('measure')
        if not nodes or len(nodes) > 256:
            error(part, '乐谱小节数必须在 1–256 内')
        for mi, measure in enumerate(nodes):
            if cancelled():
                raise InterruptedError('已取消')
            if pi and len(nodes) != len(combined):
                error(part, '两个分部小节数不一致')
            uid = combined[mi].id if pi else measure.get('id')
            cursor = end = Q(0)
            chord_onset = None
            elements, directions = [], []
            forward, repeat_times = False, 0
            endings = active_endings
            for item in measure:
                tag = item.tag
                if tag == 'attributes':
                    if item.find('divisions') is not None:
                        divisions = Q(item.findtext('divisions'))
                        if divisions <= 0:
                            error(item, 'divisions 必须大于零')
                    staves = int(item.findtext('staves', str(staves)))
                    if staves != (2 if len(part_nodes) == 1 else 1):
                        error(item, '钢琴组必须为两谱表；不截取多谱表总谱')
                    for clef in item.findall('clef'):
                        if clef.findtext('sign') not in ('G', 'F', 'C'):
                            error(clef, '仅支持 G／F／C 谱号')
                    for key in item.findall('key'):
                        fifths = key.findtext('fifths')
                        if fifths is None or not -7 <= int(fifths) <= 7 or key.findtext('mode', 'major') not in ('major', 'minor', 'none'):
                            error(key, '调号超出首版范围')
                    if item.find('time') is not None:
                        time = item.find('time')
                        if cursor or len(time.findall('beats')) != 1 or len(time.findall('beat-type')) != 1:
                            error(time, '不支持节内／相加拍号')
                        try:
                            meter = (int(time.findtext('beats')), int(time.findtext('beat-type')))
                        except (ValueError, TypeError):
                            error(time, '拍号不可执行')
                        if meter not in METERS:
                            error(time, '拍号超出首版范围')
                elif tag in ('backup', 'forward'):
                    if divisions is None:
                        error(item, 'duration 前缺少 divisions')
                    amount = Q(item.findtext('duration', '0')) / divisions
                    if amount <= 0:
                        error(item, 'backup／forward 必须大于零')
                    cursor += amount if tag == 'forward' else -amount
                    if cursor < 0:
                        error(item, 'backup 越过小节开始')
                    end = max(end, cursor)
                    chord_onset = None
                elif tag == 'note':
                    if divisions is None or meter is None:
                        error(item, '缺少明确 divisions／拍号')
                    duration = Q(item.findtext('duration', '0')) / divisions
                    if duration <= 0:
                        error(item, '音符／休止必须有正 duration')
                    is_chord = item.find('chord') is not None
                    if is_chord and chord_onset is None:
                        error(item, 'chord 缺少前导音符')
                    onset = chord_onset if is_chord else cursor
                    if not is_chord:
                        chord_onset = cursor
                        cursor += duration
                    end = max(end, onset + duration)
                    staff = int(item.findtext('staff', '1'))
                    if not 1 <= staff <= staves:
                        error(item, 'staff 不存在')
                    voice = item.findtext('voice', '1')
                    pitch_node = item.find('pitch')
                    pitch, spelling = None, None
                    if pitch_node is not None:
                        step, octave = pitch_node.findtext('step'), int(pitch_node.findtext('octave', '-10'))
                        alter = Q(pitch_node.findtext('alter', '0'))
                        if step not in ('C','D','E','F','G','A','B') or alter.denominator != 1:
                            error(item, '不支持微分音或非法音高')
                        pitch = 12 * (octave + 1) + dict(C=0, D=2, E=4, F=5, G=7, A=9, B=11)[step] + int(alter)
                        if not 21 <= pitch <= 108:
                            error(item, '音高超出 A0–C8')
                        spelling = (step, int(alter), octave)
                        pitched += 1
                    elif item.find('rest') is None:
                        error(item, '音符缺少 pitch／rest')
                    tm = item.find('time-modification')
                    if tm is not None and (int(tm.findtext('actual-notes', '0')), int(tm.findtext('normal-notes', '0'))) not in ((3, 2), (5, 4), (6, 4), (7, 4)):
                        error(item, '连音比率未经验证')
                    if len(item.findall("notations/tuplet[@type='start']")) > 1:
                        error(item, '不支持嵌套连音')
                    ties = {t.get('type') for t in item.findall('tie')}
                    tied = item.findall('notations/tied')
                    numbers = {t.get('number', '1') for t in tied}
                    if len(numbers) > 1:
                        error(item, '一个音符不能有歧义延音编号')
                    velocity_override=None
                    if item.get('dynamics') is not None:
                        try:
                            dynamics=Q(item.get('dynamics'))
                        except ValueError:
                            error(item,'音符 dynamics 必须是明确数值')
                        if dynamics<0:
                            error(item,'音符 dynamics 不能为负')
                        velocity_override=max(1,min(127,round(dynamics*Q(90,100))))
                    elements.append(ScoreElement(item.get('id'), uid, pid, f'{pid}:{staff}', voice,
                        onset, duration, pitch, spelling, 'start' in ties, 'stop' in ties,
                        next(iter(numbers), '1'), item.find('notations/articulations/staccato') is not None,
                        item.find('cue') is not None, item.get('print-object') != 'no',velocity_override))
                    if item.find('cue') is not None or item.get('print-object')=='no':
                        diagnostics.append(dict(code='CUE_DISPLAY_ONLY' if item.find('cue') is not None else 'INVISIBLE_PLAYBACK',
                            message='cue 音符仅展示，不生成起音' if item.find('cue') is not None else '不可见音符保留播放，按源设置不显示',
                            element_id=item.get('id'),source_locator=source.locations[item.get('id')]['source_locator']))
                elif tag in ('direction', 'sound'):
                    if divisions is None:
                        error(item, 'direction 前缺少 divisions')
                    sound = item if tag == 'sound' else item.find('sound')
                    offset_node=item.find('offset')
                    # A direction offset defaults to display-only. A sound child
                    # offset is always musical and overrides its parent direction.
                    offset = item.findtext('offset','0') if tag=='sound' or offset_node is not None and offset_node.get('sound')=='yes' else '0'
                    if sound is not None and sound.find('offset') is not None:
                        offset = sound.findtext('offset')
                    pos = cursor + Q(offset) / divisions
                    if pos < 0:
                        error(item, 'direction offset 越过小节开始')
                    scope = f'{pid}:{item.findtext("staff", "1")}'
                    if sound is not None:
                        for key in ('tempo', 'dynamics', 'damper-pedal'):
                            if sound.get(key) is not None:
                                value = sound.get(key)
                                value = Q(100 if value == 'yes' else 0 if value == 'no' else value)
                                if key == 'tempo' and value == 0:
                                    if settings.get('default_tempo'):
                                        value=Q(str(settings['default_tempo']))
                                    else:
                                        needs['default_tempo'] = '未提供可执行速度，请确认四分音符／分钟'
                                        continue
                                if value < 0 or key == 'damper-pedal' and value > 100:
                                    error(item, '声音参数超出范围')
                                directions.append(dict(onset=pos, kind=key, value=value, priority=2,
                                                       scope=scope, element_id=item.get('id')))
                    for dt in item.findall('direction-type'):
                        for met in dt.findall('metronome'):
                            unit = UNITS.get(met.findtext('beat-unit'))
                            per = met.findtext('per-minute')
                            if not unit or not per:
                                error(met, 'metronome 不能换算为明确速度')
                            dots = len(met.findall('beat-unit-dot'))
                            value = Q(per) * unit * (2 - Q(1, 2**dots))
                            if value <= 0:
                                error(met, '速度必须大于零')
                            directions.append(dict(onset=pos, kind='tempo', value=value, priority=1,
                                                   scope=scope, element_id=item.get('id')))
                        for dynamics in dt.findall('dynamics'):
                            names = [v.tag for v in dynamics]
                            if names:
                                if len(names) != 1 or names[0] not in DYNAMICS:
                                    error(dynamics, '力度符号不能按首版策略执行')
                                directions.append(dict(onset=pos, kind='velocity', value=Q(DYNAMICS[names[0]]),
                                                       priority=1, scope=scope, element_id=item.get('id')))
                        for pedal in dt.findall('pedal'):
                            kind = pedal.get('type')
                            if kind not in ('start', 'stop', 'change', 'continue', 'discontinue', 'resume'):
                                error(pedal, '踏板记号不支持')
                            if kind not in ('continue',):
                                values = (0, 100) if kind == 'change' else (0,) if kind in ('stop', 'discontinue') else (100,)
                                for value in values:
                                    directions.append(dict(onset=pos, kind='damper-pedal', value=Q(value),
                                                           priority=1, scope=scope, element_id=item.get('id')))
                elif tag == 'barline':
                    repeat = item.find('repeat')
                    if repeat is not None:
                        if repeat.get('direction') == 'forward':
                            if forward:
                                error(repeat,'同一小节重复的前反复不明确')
                            forward = True
                        elif repeat.get('direction') == 'backward':
                            if repeat_times:
                                error(repeat,'同一小节重复的后反复不明确')
                            repeat_times = int(repeat.get('times', '2'))
                            if not 2 <= repeat_times <= 16:
                                error(repeat, '反复次数必须在 2–16 内')
                        else:
                            error(repeat, '反复方向错误')
                    ending = item.find('ending')
                    if ending is not None:
                        try:
                            numbers = tuple(int(n.strip()) for n in ending.get('number', '').split(','))
                        except ValueError:
                            error(ending, '结尾遍次必须可枚举')
                        if any(n not in (1, 2) for n in numbers):
                            error(ending, '首版支持一／二结尾')
                        if ending.get('type') == 'start':
                            endings = active_endings = numbers
                        elif ending.get('type') in ('stop', 'discontinue'):
                            endings = endings or active_endings or numbers
                            active_endings = ()
                elif tag not in ('print',):
                    diagnostics.append(dict(code='DISPLAY_UNVERIFIED', message='未单独验证显示字段：' + tag,
                                            source_locator=source.locations[item.get('id')]['source_locator']))
            if meter is None:
                error(measure, '缺少拍号，不猜测 4/4')
            expected = Q(meter[0] * 4, meter[1])
            implicit = measure.get('implicit') == 'yes'
            if end <= 0 or end > expected or end < expected and not (implicit or mi == len(nodes) - 1):
                error(measure, '小节时值与拍号矛盾；弱起需 implicit，尾小节允许不完整')
            if any(d['onset'] > end for d in directions):
                error(measure, 'direction 越过小节边界')
            if pi:
                target = combined[mi]
                if target.length != end or target.meter != meter:
                    error(measure, '分部小节时间不对齐')
                if (forward or repeat_times or endings) and (forward, repeat_times, endings) != (target.forward, target.repeat_times, target.endings):
                    error(measure, '分部反复路径矛盾')
                target.elements.extend(elements)
                target.directions.extend(directions)
            else:
                combined.append(Measure(uid, measure.get('number', str(mi + 1)), end, meter,
                                        elements, directions, forward, repeat_times, endings))
        parts.append(dict(id=pid, name=part_defs.get(pid, '钢琴'), staves=staves))
    if pitched == 0 or pitched > 5000:
        error(root, '有音高的源 note 数必须在 1–5,000 内')
    first_tempos = [d for d in combined[0].directions if d['kind'] == 'tempo' and d['onset'] == 0]
    if not first_tempos and not settings.get('default_tempo'):
        needs['default_tempo'] = '未提供起始播放速度；建议四分音符=120，须确认'
    if settings.get('default_tempo') and not 10 <= Q(str(settings['default_tempo'])) <= 1000:
        error(root, '确认速度必须在 10–1000 BPM 内')
    return ScoreDocument(source, root.findtext('work/work-title') or root.findtext('movement-title') or source.original_name,
                         parts, combined, diagnostics, needs, hashlib.sha256((source.sha256 + ':profile1').encode()).hexdigest()[:24])
