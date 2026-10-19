"""PortAudio output, DAC timestamp mapping, bounded post-gain sample history.

The callback only copies prepared PCM and updates preallocated sample slots.
It never calls the UI, synthesizer, FFT, filesystem, or blocking locks.
"""
import math
import asyncio
import numpy as np
import sounddevice as sd

class Audio:
    block=512
    def __init__(self):
        self.sample_rate=48000;self.stream=None;self.error=None;self.ready=False
        self.pcm=None;self.rate=1.;self.duration=0.;self.cursor=0;self.position=0.
        self.playing=False;self.volume=.65;self.gain=0.;self.epoch=0;self.underruns=0
        self.loop={'enabled':False,'a_s':0.,'b_s':0.}
        self.ring=np.zeros((64,self.block,2),np.float32);self.stamps=np.zeros((64,4),np.float64);self.serial=0
        self.offsets=np.zeros((64,2),np.int64);self.lengths=np.zeros((64,2),np.int64);self.samples_at=np.zeros((64,2),np.int64)
        self.entrance=True;self.fade_cursor=0;self.fade_requested=False;self.fade_dac=None
        self.fade_envelope=np.zeros(self.block,np.float32)
        length=round(.005*self.sample_rate);self.fade_envelope[:length]=np.linspace(1,0,length)
        self.fade_in=np.linspace(0,1,length,dtype=np.float32)
        self.ramp=np.arange(self.block,dtype=np.float32)/self.block
        self.gains=np.empty(self.block,dtype=np.float32)
        self.last_heard_serial=0;self.finish_dac=None;self.device=None
    def open(self):
        self.close_stream();self.playing=False;self.error=None
        for sr in (48000,44100):
            try:
                sd.check_output_settings(channels=2,dtype='float32',samplerate=sr)
                self.sample_rate=sr
                self.fade_envelope.fill(0);length=round(.005*sr);self.fade_envelope[:length]=np.linspace(1,0,length)
                self.fade_in=np.linspace(0,1,length,dtype=np.float32)
                self.stream=sd.OutputStream(samplerate=sr,channels=2,dtype='float32',blocksize=self.block,
                    latency='low',callback=self._callback)
                self.device=dict(sd.query_devices(kind='output'));self.ready=True
                return True
            except Exception as exc:self.error=str(exc)
        self.ready=False;return False
    def install(self,pcm,rate,duration,position):
        self.halt();self.pcm=pcm;self.rate=rate;self.duration=duration
        self.set_position(position)
    def _reset_history(self):
        self.epoch+=1;self.stamps.fill(0);self.finish_dac=None;self.gain=0
        self.entrance=True;self.fade_cursor=0;self.fade_requested=False;self.fade_dac=None
    def set_position(self,value):
        self.position=float(value)
        self.cursor=round(self.position/self.rate*self.sample_rate)
        self._reset_history()
    def halt(self):
        position=self.clock()[0] if self.playing else self.position
        self.playing=False
        if self.stream and self.stream.active:self.stream.abort()
        self.position=position;self._reset_history()
        return position
    async def fade_halt(self):
        if self.playing and self.stream and self.stream.active:
            self.fade_requested=True
            # Yield on the application thread while a 5ms fade reaches the DAC.
            deadline=asyncio.get_running_loop().time()+.1
            while self.fade_dac is None and asyncio.get_running_loop().time()<deadline:
                await asyncio.sleep(.002)
            if self.fade_dac is not None:
                await asyncio.sleep(max(0,min(.08,self.fade_dac-float(self.stream.time))))
        return self.halt()
    def start(self):
        if not self.ready or not self.stream:raise RuntimeError('未找到声音输出设备')
        self._reset_history();self.playing=True
        try:self.stream.start()
        except Exception:
            self.playing=False;self.ready=False;raise
    def _callback(self,out,frames,time,status):
        if status.output_underflow:self.underruns+=1
        out.fill(0)
        if not self.playing or self.pcm is None:return
        epoch=self.epoch;pcm=self.pcm;cursor=self.cursor;offset=0
        a=round(self.loop['a_s']/self.rate*self.sample_rate)
        b=round(self.loop['b_s']/self.rate*self.sample_rate)
        looping=self.loop['enabled'];limit=b if looping else len(pcm)
        slot=(self.serial+1)%64;self.stamps[slot,0]=0;segment_count=0
        fade=max(1,round(.005*self.sample_rate))
        while offset<frames:
            if cursor>=limit:
                if looping:cursor=a
                else:break
            n=min(frames-offset,limit-cursor)
            out[offset:offset+n]=pcm[cursor:cursor+n]
            self.offsets[slot,segment_count]=offset;self.lengths[slot,segment_count]=n;self.samples_at[slot,segment_count]=cursor
            # Envelope indices derive from source samples, so fades continue
            # across callbacks even when a loop boundary splits a tiny block.
            if looping and cursor<a+fade:
                start=max(0,cursor-a);length=min(n,fade-start)
                if length>0:np.multiply(out[offset:offset+length],self.fade_in[start:start+length,None],out=out[offset:offset+length])
            if self.entrance:
                length=min(n,fade-self.fade_cursor)
                if length>0:np.multiply(out[offset:offset+length],self.fade_in[self.fade_cursor:self.fade_cursor+length,None],out=out[offset:offset+length])
                self.fade_cursor+=length
                if self.fade_cursor>=fade:self.entrance=False
            fade_limit=b if looping else len(pcm)
            if cursor+n>fade_limit-fade:
                begin=max(0,fade_limit-fade-cursor);index=max(0,cursor+begin-(fade_limit-fade));length=n-begin
                np.multiply(out[offset+begin:offset+n],self.fade_in[::-1][index:index+length,None],out=out[offset+begin:offset+n])
            segment_count+=1;cursor+=n;offset+=n
        target=self.volume
        np.multiply(self.ramp,target-self.gain,out=self.gains);self.gains+=self.gain
        np.multiply(out,self.gains[:,None],out=out);self.gain=target
        if self.fade_requested:
            if self.fade_dac is None:
                np.multiply(out,self.fade_envelope[:,None],out=out)
                self.fade_dac=float(time.outputBufferDacTime)+.005
            else:out.fill(0)
        if epoch!=self.epoch:return
        self.cursor=cursor;self.serial+=1
        self.ring[slot]=out
        self.stamps[slot,1]=epoch;self.stamps[slot,2]=float(time.outputBufferDacTime);self.stamps[slot,3]=segment_count
        self.stamps[slot,0]=self.serial
        if not looping and cursor>=len(pcm) and self.finish_dac is None:
            self.finish_dac=float(time.outputBufferDacTime)+offset/self.sample_rate
    def _records(self):
        result=[]
        for slot in range(64):
            serial,epoch,dac,count=self.stamps[slot]
            if serial>0 and epoch==self.epoch:
                segments=[(int(self.offsets[slot,i]),int(self.lengths[slot,i]),int(self.samples_at[slot,i])) for i in range(int(count))]
                if self.stamps[slot,0]==serial:result.append((int(serial),int(epoch),float(dac),segments))
        return sorted(result,key=lambda s:s[0])
    def clock(self):
        if not self.playing or not self.stream:return self.position,False,False
        try:now=float(self.stream.time)
        except Exception:
            self.ready=False;self.playing=False;self.error='声音输出设备已断开'
            return self.position,False,False
        records=self._records()
        pos=self.position;tail=False
        for serial,epoch,dac,segments in records:
            if dac>now:break
            for off,n,start in segments:
                if now<dac+off/self.sample_rate:break
                played=min(n,max(0,(now-dac)*self.sample_rate-off))
                sample=start+played
                pos=min(self.duration,sample/self.sample_rate*self.rate)
                tail=sample/self.sample_rate*self.rate>=self.duration
        ended=self.finish_dac is not None and now>=self.finish_dac
        if ended:pos=self.duration;tail=False
        self.position=pos
        return pos,tail,ended
    def heard_window(self):
        if not self.playing or self.volume==0 or not self.stream:return np.zeros((4096,2),np.float32)
        now=float(self.stream.time)
        result=np.zeros((4096,2),np.float32);pieces=[]
        for stamp in self._records():
            serial,epoch,dac,segments=stamp
            heard=min(self.block,max(0,int((now-dac)*self.sample_rate)))
            if heard:
                data=self.ring[serial%64,:heard].copy()
                if self.stamps[serial%64,0]==serial:pieces.append(data)
        if pieces:
            joined=np.concatenate(pieces)[-4096:];result[-len(joined):]=joined
        return result
    def close_stream(self):
        if self.stream:
            self.stream.abort();self.stream.close();self.stream=None
        self.ready=False
    def close(self):self.playing=False;self.close_stream();self.pcm=None
