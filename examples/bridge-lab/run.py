"""Native AppCore entry point; all engine calls run on the main thread."""
import argparse
import asyncio
from importlib.metadata import version
from importlib.resources import files
import json
from pathlib import Path
import platform
import sys
import tempfile
import traceback
from bridge_lab.bridge import register_api
from bridge_lab.fixtures import python_sources

async def verify(view, screenshot=None):
    await view.wait_settled(timeout=15)
    await view.wait_until(lambda: view.evaluate('window.BRIDGE_LAB_READY === true'), timeout=15)
    results = []
    async def case(index, expected=None, code=None, failure=False):
        view.evaluate(f'BridgeLab.select({index})')
        if code is not None:
            view.evaluate('document.getElementById("editor").value = '+json.dumps(code))
        result = await view.evaluate_async('BridgeLab.run()')
        results.append(result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
        assert result['success'] is not failure, result
        if expected is not None:
            assert result['output'] == expected, result
        return result
    await case(0,['42'])
    await case(0,['52'],'print(lab.add(30,22));')
    await case(1,['request started','result: 42'])
    await case(2,['before: 0','after: 2'])
    assert view.evaluate('lab.counter.value') == 2
    await case(3,['length: 1','last: 7','snapshot: [7]'])
    error = await case(4)
    assert len(error['output']) == 1 and 'zero' in error['output'][0].lower(),error
    await case(5,['name: Bridge Lab','is plain JS: true','{"name":"Bridge Lab","version":"1.0","tags":["python","js"]}'])
    await case(0,code='lab.divide(1,0);',failure=True)
    await case(1,code='await lab.delayed_double(21,2001);',failure=True)
    await case(0,['42'],'print(lab.add(20,22));')
    view.evaluate('BridgeLab.select(1); BridgeLab.reset(); window.pendingRun=BridgeLab.run(); void 0')
    assert view.evaluate('BridgeLab.busy && document.getElementById("run").disabled')
    assert view.evaluate('BridgeLab.select(2) === false && BridgeLab.reset() === false')
    assert await view.evaluate_async('BridgeLab.run()') is None
    pending = await view.evaluate_async('pendingRun')
    assert pending['output'] == ['request started','result: 42']
    assert view.evaluate('!BridgeLab.busy && !document.getElementById("run").disabled')
    view.evaluate('BridgeLab.select(0); BridgeLab.reset(); document.getElementById("clear").click()')
    assert view.evaluate('BridgeLab.logs.length') == 0
    await case(0,code='for(let i=0;i<310;i++) console.warn("x".repeat(4100));')
    assert view.evaluate('BridgeLab.logs.length') == 300
    assert view.evaluate('BridgeLab.logs.every(x=>x.message.length<=4000)')
    if screenshot:
        view.evaluate('document.getElementById("clear").click(); BridgeLab.select(2); BridgeLab.reset()')
        await view.evaluate_async('BridgeLab.run()')
        await asyncio.sleep(0.2)
        image = view.copy_pixels().to_rgba()
        import struct
        import zlib
        def chunk(kind, data):
            return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
        stride = image.width * 4
        raw = b''.join(b'\0'+image.data[y*stride:(y+1)*stride] for y in range(image.height))
        screenshot.parent.mkdir(parents=True,exist_ok=True)
        screenshot.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',image.width,image.height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))
    return results

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cpu',action='store_true')
    parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--smoke-report',type=Path)
    parser.add_argument('--screenshot',type=Path,help='With --smoke, save real CPU AppCore view PNG')
    args=parser.parse_args()
    report={'platform':platform.platform(),'python':platform.python_version(),'success':False}
    try:
        if version('ultralight-py')!='0.5.0':
            raise RuntimeError('Requires ultralight-py==0.5.0')
        from ultralight_py import API,Application,Resource
        assets=files('bridge_lab').joinpath('assets')
        mime={'html':'text/html','css':'text/css','js':'text/javascript'}
        resources={p.name:Resource(p.read_bytes(),mime[p.name.rsplit('.',1)[-1]]) for p in assets.iterdir() if p.is_file()}
        resources['sources.js']=Resource(('window.PYTHON_SOURCES='+json.dumps(python_sources())+';').encode(),'text/javascript')
        with tempfile.TemporaryDirectory(prefix='bridge-lab-') as state:
            with API('lab') as api, Application(resource_loader=resources.get,cache_path=state,app_name='UltralightBridgeLab',force_cpu_renderer=args.cpu or bool(args.screenshot)) as app:
                register_api(api)
                window=app.create_window(1280,800,title='Ultralight Bridge Lab')
                api.attach(window.view)
                window.view.load_url('file:///index.html')
                if args.smoke:
                    async def smoke():
                        pump=asyncio.create_task(app.run_async())
                        try:
                            report['results']=await asyncio.wait_for(verify(window.view,args.screenshot),45)
                            report['success']=True
                        finally:
                            app.close()
                            await pump
                    asyncio.run(smoke())
                else:
                    app.run()
        return 0
    except Exception as exc:
        report['error']=str(exc)
        traceback.print_exc()
        return 1
    finally:
        if args.smoke_report:
            args.smoke_report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if args.smoke:
            print('Bridge Lab native smoke: '+('PASS' if report['success'] else 'FAIL'),flush=True)

if __name__=='__main__':
    sys.exit(main())
