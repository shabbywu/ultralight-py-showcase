"""Original, directly authored MusicXML phrases (MIT); no MIDI conversion."""
from pathlib import Path
import xml.etree.ElementTree as E

ROOT = Path(__file__).resolve().parents[1] / 'tests/fixtures/v2'


def note(ident, pitch=None, duration=12, kind='quarter', staff=1, voice='1', tie=(), chord=False, extra=''):
    content = '<rest/>' if pitch is None else f'<pitch><step>{pitch[0]}</step><alter>{pitch[1]}</alter><octave>{pitch[2]}</octave></pitch>'
    return (f'<note id="{ident}">' + ('<chord/>' if chord else '') + content +
            f'<duration>{duration}</duration>' + ''.join(f'<tie type="{t}"/>' for t in tie) +
            f'<voice>{voice}</voice><type>{kind}</type><staff>{staff}</staff>' +
            ('<notations>' + ''.join(f'<tied type="{t}"/>' for t in tie) + '</notations>' if tie else '') + extra + '</note>')


ATTR = '''<attributes><divisions>12</divisions><key><fifths>0</fifths><mode>major</mode></key>
<time><beats>4</beats><beat-type>4</beat-type></time><staves>2</staves>
<clef number="1"><sign>G</sign><line>2</line></clef><clef number="2"><sign>F</sign><line>4</line></clef></attributes>'''


def document(title, measures):
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0"><work><work-title>{title}</work-title></work>
<identification><creator type="composer">PianoScope 原创 · MIT</creator><rights>MIT; directly authored MusicXML, 2026</rights></identification>
<defaults><scaling><millimeters>7</millimeters><tenths>40</tenths></scaling></defaults>
<part-list><score-part id="P1"><part-name>钢琴</part-name><part-abbreviation>Pno.</part-abbreviation></score-part></part-list>
<part id="P1">{''.join(measures)}</part></score-partwise>'''


def temporal():
    backup = '<backup><duration>48</duration></backup>'
    measures = []
    measures.append('<measure id="pickup" number="0" implicit="yes">' + ATTR +
                    '<direction><sound tempo="120"/></direction>' + note('pickup-g', ('G', 0, 4)) +
                    '<backup><duration>12</duration></backup>' + note('pickup-rest', staff=2, voice='2') + '</measure>')
    a = '<barline location="left"><repeat direction="forward"/></barline>'
    a += '<direction><sound tempo="120"/></direction><direction><offset>24</offset><sound tempo="60"/></direction>'
    a += '<direction><direction-type><pedal type="start" line="yes"/></direction-type></direction>'
    a += note('a-long', ('C', 0, 5), 48, 'whole', tie=('start',))
    a += note('a-chord-short', ('E', 0, 5), 24, 'half', chord=True)
    a += backup + note('a-overlap', ('C', 0, 5), 24, 'half', voice='3') + note('a-rest', duration=24, kind='half', voice='3')
    a += backup + note('a-bass', ('C', 0, 3), 48, 'whole', staff=2, voice='2')
    measures.append('<measure id="A" number="1">' + a + '</measure>')
    b = '<barline location="left"><ending number="1" type="start"/></barline>'
    b += note('b-tie', ('C', 0, 5), 48, 'whole', tie=('stop',))
    b += backup + note('b-bass-1', ('G', 0, 2), 24, 'half', staff=2, voice='2') + note('b-bass-2', ('G', 0, 2), 24, 'half', staff=2, voice='2')
    b += '<barline location="right"><ending number="1" type="stop"/><repeat direction="backward" times="2"/></barline>'
    measures.append('<measure id="B" number="2">' + b + '</measure>')
    c = '<barline location="left"><ending number="2" type="start"/></barline>'
    c += '<direction><offset>12</offset><sound tempo="90"/></direction>'
    c += '<direction><offset>24</offset><sound damper-pedal="no"/></direction>'
    # Same voice changes staff for the second ending tie continuation.
    c += note('c-tie-cross', ('C', 0, 5), 24, 'half', staff=2, tie=('stop',))
    c += note('c-next', ('D', 0, 5), 24, 'half')
    c += backup + note('c-bass', ('F', 0, 3), 48, 'whole', staff=2, voice='2')
    c += '<barline location="right"><ending number="2" type="discontinue"/></barline>'
    measures.append('<measure id="C" number="2">' + c + '</measure>')
    d = '<direction><direction-type><octave-shift type="down" size="8"/></direction-type><staff>1</staff></direction>'
    for i, pitch in enumerate(('C', 'D', 'E')):
        extra = '<time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes><normal-type>eighth</normal-type></time-modification>'
        # time-modification belongs before staff in schema; use an explicit note.
        notation = '<notations><tuplet type="start"/></notations>' if i == 0 else '<notations><tuplet type="stop"/></notations>' if i == 2 else ''
        d += f'<note id="d-triplet-{i}"><pitch><step>{pitch}</step><octave>6</octave></pitch><duration>4</duration><voice>1</voice><type>eighth</type>{extra}<staff>1</staff>{notation}</note>'
    d += note('d-dotted', ('G', 0, 6), 18, 'quarter').replace('<type>quarter</type>', '<type>quarter</type><dot/>')
    d += note('d-eighth', ('E', 0, 6), 6, 'eighth') + note('d-quarter', ('C', 0, 6))
    d += '<direction><direction-type><octave-shift type="stop" size="8"/></direction-type><staff>1</staff></direction>'
    d += backup + note('d-bass', ('C', 0, 3), 48, 'whole', staff=2, voice='2')
    measures.append('<measure id="D" number="3">' + d + '</measure>')
    return document('回环与晨光 · 时间契约', measures)


def printed():
    measures = []
    melody = [('C', 0, 5), ('E', 0, 5), ('G', 0, 5), ('D', 0, 5), ('F', 0, 5), ('A', 0, 5)]
    for bar in range(24):
        content = ATTR + '<direction><sound tempo="120"/></direction>' if bar == 0 else ''
        if bar in (4, 8, 16, 20):
            content += '<print new-system="yes"/>'
        if bar == 12:
            content += '<print new-page="yes"/>'
        for beat in range(4):
            pitch = melody[(bar + beat) % len(melody)]
            content += note(f'p-{bar}-{beat}', pitch)
            if beat in (0, 2):
                content += note(f'p-chord-{bar}-{beat}', ('G', 0, 4), chord=True)
        content += '<backup><duration>48</duration></backup>'
        for beat in range(2):
            content += note(f'p-bass-{bar}-{beat}', ('C' if bar % 2 == 0 else 'G', 0, 3), 24, 'half', staff=2, voice='2')
        measures.append(f'<measure id="print-{bar}" number="{bar + 1}">{content}</measure>')
    return document('初光 · 乐谱阅读练习', measures)


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, text in (('temporal', temporal()), ('printed', printed())):
        # Syntax only; semantic expectations are authored independently in tests.
        E.fromstring(text)
        (ROOT / (name + '.musicxml')).write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()
