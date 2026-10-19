'use strict';

// Geometry and animation only. Audible IDs and musical positions come from DAC snapshots.
class PianoRollRenderer {
  constructor(colors, cpu) {
    this.colors=colors;this.particleLimit=cpu?128:256;this.emissionPeriod=cpu?50:34;this.fxScale=cpu?.75:1;this.enabled=true;
    const preference=window.matchMedia('(prefers-reduced-motion: reduce)');
    this.reducedMotion=preference.matches;
    const changed=event=>{this.reducedMotion=event.matches;this.textures=null;this.clearEffects();};
    if(preference.addEventListener)preference.addEventListener('change',changed);
    else if(preference.addListener)preference.addListener(changed);
    this.notes=[];this.byId=new Map();this.nextOnset=new Map();this.revision=null;
    this.previous=null;this.seen=new Set();this.particles=[];this.pulses=[];
    this.impactCount=0;this.history=[];this.lastCells=[];this.viewport='';
    this.background=null;this.textures=null;this.palette=new Set();
    this.emitters=new Map();this.lastEmitters=[];this.lastTrails=[];this.lastEffects=[];this.surface=null;this.particleSerial=0;this.observedAt=0;
  }

  setNotes(notes, revision) {
    this.notes=notes;this.revision=revision;this.byId=new Map(notes.map(n=>[n.id,n]));
    this.palette=new Set(notes.map(n=>this.colors[n.hand]||this.colors.unassigned));
    this.nextOnset.clear();
    const pitches=new Map();
    for(const n of notes){if(!pitches.has(n.pitch))pitches.set(n.pitch,[]);pitches.get(n.pitch).push(n);}
    for(const list of pitches.values()) {
      list.sort((a,b)=>a.onset_s-b.onset_s||a.key_off_s-b.key_off_s);
      for(let i=0;i<list.length;i++) {
        const n=list[i];let low=i+1,high=list.length;
        // Overlapping instances remain independent. Find the next re-articulation
        // at or after this release, rather than cutting a held overlapping voice.
        while(low<high){const mid=(low+high)>>1;if(list[mid].onset_s<n.key_off_s-1e-7)low=mid+1;else high=mid;}
        if(low<list.length)this.nextOnset.set(n.id,list[low].onset_s);
      }
    }
    this.previous=null;this.seen.clear();this.clearEffects();
    this.impactCount=0;this.history=[];this.lastCells=[];
  }

  clearEffects(){this.particles=[];this.pulses=[];this.emitters.clear();this.lastEmitters=[];this.lastTrails=[];this.lastEffects=[];}
  setEnabled(on){this.enabled=!!on;if(!this.enabled)this.clearEffects();}
  reset(){this.previous=null;this.seen.clear();this.clearEffects();}

  observe(snapshot, visible, now) {
    const previous=this.previous;
    if(previous&&snapshot.seq===previous.seq)return;
    this.previous=snapshot;this.observedAt=now;
    if(!visible||!this.enabled||snapshot.phase!=='playing'||snapshot.volume<=0||snapshot.playback_revision!==this.revision) {
      this.clearEffects();this.seen.clear();return;
    }
    let from=previous?previous.position_s:snapshot.position_s;
    const sameClock=previous&&previous.clock_epoch===snapshot.clock_epoch&&previous.playback_revision===snapshot.playback_revision&&previous.phase==='playing';
    if(!sameClock) {
      this.clearEffects();this.seen.clear();
      // A natural start from ready/zero may flash the first actual sounding note.
      // Resume and seek into an already-held note must never invent an attack.
      const anchor=snapshot.loop.enabled?snapshot.loop.a_s:0;
      if(previous&&previous.phase==='ready'&&previous.position_s===0&&snapshot.position_s>=anchor&&snapshot.position_s-anchor<=.15*snapshot.rate)from=anchor-1e-7;
      else return;
    } else if(snapshot.position_s<from) {
      this.clearEffects();this.seen.clear();
      if(!snapshot.loop.enabled)return;
      from=snapshot.loop.a_s-1e-7;
    } else if(snapshot.position_s-from>.25*snapshot.rate) {
      // Do not release a burst of stale impacts after a stalled UI.
      this.clearEffects();this.seen.clear();return;
    }
    for(const id of snapshot.active_instance_ids) {
      const n=this.byId.get(id);
      if(!n||this.seen.has(id)||n.onset_s<=from||n.onset_s>snapshot.position_s+1e-7)continue;
      this.seen.add(id);this.emit(n,now);
    }
  }

  emit(note, now) {
    this.impactCount++;
    this.history.push({id:note.id,pitch:note.pitch,onset_s:note.onset_s});
    if(this.history.length>64)this.history.shift();
    this.pulses.push({pitch:note.pitch,hand:note.hand,born:now});
    if(this.pulses.length>32)this.pulses.shift();
    if(!this.reducedMotion)this.spray(note,now,4);
  }

  spray(note, now, count) {
    let hash=0;for(let i=0;i<note.id.length;i++)hash=(hash*31+note.id.charCodeAt(i))>>>0;
    for(let i=0;i<count;i++) {
      const id=++this.particleSerial,seed=(hash+Math.imul(id,2654435761))>>>0;
      const fraction=.03+(seed%997)/996*.94;
      if(this.particles.length>=this.particleLimit)this.particles.shift();
      this.particles.push({id,pitch:note.pitch,hand:note.hand,born:now,fraction,
        vx:(fraction-.5)*(100+seed%71),vy:-130-seed%91,
        gravity:230+seed%61,life:.44+(seed%21)/100});
    }
  }

  geometry(layout, time, line, height, pps) {
    const cells=[];
    for(const n of this.notes) {
      const key=layout.byMidi[n.pitch];if(!key)continue;
      const naturalTop=line-(n.key_off_s-time)*pps,bottom=line-(n.onset_s-time)*pps;
      if(bottom<0||naturalTop>height)continue;
      const length=Math.max(1.5,(n.key_off_s-n.onset_s)*pps),next=this.nextOnset.get(n.id);
      const naturalGap=next===undefined?Infinity:Math.max(0,(next-n.key_off_s)*pps);
      const gap=Math.min(Math.max(0,4-naturalGap),length*.25);
      cells.push({id:n.id,pitch:n.pitch,hand:n.hand,x:key.x+2,width:Math.max(2,key.width-4),
        naturalTop,top:bottom-length+gap,bottom,height:length-gap,gap,released:n.key_off_s<time});
    }
    return cells;
  }

  prepareTextures(scale) {
    if(!this.textures||this.textures.scale!==scale)this.textures={scale,colors:new Map()};
    // Only the full-key contact glow is a bitmap. Flying particles are live
    // trajectories, continuously emitted while DAC snapshots report held keys.
    for(const color of this.palette) {
      if(this.textures.colors.has(color))continue;
      const canvas=document.createElement('canvas');canvas.width=scale;canvas.height=24*scale;
      const p=canvas.getContext('2d');p.setTransform(scale,0,0,scale,0,0);
      const glow=p.createLinearGradient(0,0,0,24);glow.addColorStop(0,'transparent');glow.addColorStop(.7,color);glow.addColorStop(1,'transparent');
      p.fillStyle=glow;p.globalAlpha=.7;p.fillRect(0,0,1,24);
      p.fillStyle=color;p.globalAlpha=.95;p.fillRect(0,14,1,6);p.fillStyle='#fff0cd';p.globalAlpha=1;p.fillRect(0,16,1,2);
      this.textures.colors.set(color,canvas);
    }
  }

  paintParticles(ctx, layout, width, line, now) {
    const scale=this.fxScale,h=128,base=112,ph=Math.ceil(h*scale);
    const groups=new Map(),heads=new Map();this.lastTrails=[];let leftMost=Infinity,rightMost=-Infinity;
    this.particles=this.particles.filter(p=>(now-p.born)/1000<p.life);
    for(const p of this.particles) {
      const key=layout.byMidi[p.pitch];if(!key)continue;
      const age=Math.max(0,(now-p.born)/1000),strength=(1-age/p.life)**2,bucket=Math.min(3,Math.floor(strength*4));
      const color=this.colors[p.hand]||this.colors.unassigned,id=color+':'+bucket;
      if(!groups.has(id))groups.set(id,{color,bucket,paths:[]});if(!heads.has(bucket))heads.set(bucket,[]);
      const path=[];
      for(let i=0;i<=5;i++){const t=Math.max(0,age-.13+i*.13/5);path.push([key.x+key.width*p.fraction+p.vx*t,base+p.vy*t+.5*p.gravity*t*t]);}
      for(const point of path){leftMost=Math.min(leftMost,point[0]);rightMost=Math.max(rightMost,point[0]);}
      const tip=path[5],point=Math.max(1.7,Math.min(3.5,key.width*.08));
      groups.get(id).paths.push(path);heads.get(bucket).push({x:tip[0],y:tip[1],point});
      this.lastTrails.push({id:p.id,pitch:p.pitch,x:tip[0],y:tip[1]+line-base,tail_x:path[0][0],tail_y:path[0][1]+line-base,opacity:strength});
    }
    if(!groups.size||rightMost<0||leftMost>width)return;
    // Upload only the live spray region; grow the buffer in coarse steps so
    // moving trails do not repeatedly allocate a whole-window particle surface.
    const left=Math.max(0,Math.floor((leftMost-4)/32)*32);
    const wanted=Math.max(32,Math.min(width,rightMost+4)-left),pw=Math.ceil(Math.ceil(wanted/32)*32*scale);
    if(!this.surface||this.surface.width<pw||this.surface.height!==ph){this.surface=document.createElement('canvas');this.surface.width=pw;this.surface.height=ph;}
    const capacity=this.surface.width/scale,fx=this.surface.getContext('2d');
    fx.setTransform(scale,0,0,scale,-left*scale,0);fx.clearRect(left,0,capacity,h);
    for(const group of groups.values()) {
      for(const pass of [0,1]) {
        fx.strokeStyle=pass?'#fff0cd':group.color;
        fx.globalAlpha=(group.bucket+1)/4*(pass?.9:.3);fx.lineWidth=pass?1.2:2.6;fx.beginPath();
        for(const path of group.paths){const start=pass?3:0;fx.moveTo(...path[start]);for(let i=start+1;i<path.length;i++)fx.lineTo(...path[i]);}
        fx.stroke();
      }
    }
    fx.fillStyle='#fff0cd';
    for(const [bucket,points] of heads){fx.globalAlpha=(bucket+1)/4;fx.beginPath();for(const p of points)fx.rect(p.x-p.point/2,p.y-p.point/2,p.point,p.point);fx.fill();}
    fx.globalAlpha=1;ctx.globalAlpha=1;ctx.drawImage(this.surface,left,line-base,capacity,h);
  }

  paint(ctx, layout, width, height, time, snapshot, lift, now) {
    const line=height*(1-lift/100),pps=85,viewport=width+':'+height+':'+line;
    if(this.viewport!==viewport){this.viewport=viewport;this.clearEffects();}
    // Grid pixels are static until size/DPR/key range changes. Reuse their bitmap.
    const size=ctx.canvas.width+':'+ctx.canvas.height;
    if(!this.background||this.background.layout!==layout||this.background.size!==size) {
      const canvas=document.createElement('canvas');canvas.width=ctx.canvas.width;canvas.height=ctx.canvas.height;
      const grid=canvas.getContext('2d');grid.setTransform(canvas.width/width,0,0,canvas.height/height,0,0);
      grid.fillStyle='#0c1b1d';grid.fillRect(0,0,width,height);grid.strokeStyle='#233f38';grid.beginPath();
      for(const key of layout.rects)if(!key.is_black){grid.moveTo(key.x,0);grid.lineTo(key.x,height);}
      grid.stroke();this.background={canvas,layout,size};
    }
    ctx.drawImage(this.background.canvas,0,0,width,height);
    this.lastEffects=[];this.lastEmitters=[];this.lastTrails=[];
    if(this.enabled)this.prepareTextures(Math.max(1,Math.round(ctx.canvas.width/width)));
    const compatible=snapshot&&snapshot.playback_revision===this.revision;
    const active=new Set(compatible?snapshot.active_instance_ids:[]),tails=new Set(compatible?snapshot.sustained_instance_ids:[]);
    this.lastCells=this.geometry(layout,time,line,height,pps);
    for(const cell of this.lastCells) {
      ctx.fillStyle=this.colors[cell.hand]||this.colors.unassigned;
      ctx.globalAlpha=active.has(cell.id)?1:cell.released?.2:.65;
      ctx.fillRect(cell.x,cell.top,cell.width,cell.height);
      // A small head accent also exposes independent onsets in overlapping voices.
      ctx.globalAlpha=active.has(cell.id)?1:.8;
      ctx.fillRect(cell.x,cell.bottom-Math.min(2,cell.height*.2),cell.width,Math.min(2,cell.height*.2));
      if(tails.has(cell.id)){ctx.globalAlpha=.55;ctx.strokeStyle=ctx.fillStyle;ctx.strokeRect(cell.x,line-8,cell.width,8);}
    }
    if(this.enabled&&compatible) {
      const sounding=new Map();
      if(now-this.observedAt<=250)for(const id of active){const n=this.byId.get(id);if(n)sounding.set(n.pitch,n);}
      for(const pitch of this.emitters.keys())if(!sounding.has(pitch))this.emitters.delete(pitch);
      for(const [pitch,n] of sounding) {
        const key=layout.byMidi[pitch];if(!key)continue;
        let emitter=this.emitters.get(pitch);
        if(!emitter){emitter={last:now-this.emissionPeriod};this.emitters.set(pitch,emitter);}
        if(now-emitter.last>this.emissionPeriod*3)emitter.last=now-this.emissionPeriod;
        if(!this.reducedMotion)for(let batches=0;now-emitter.last>=this.emissionPeriod&&batches<2;batches++){emitter.last+=this.emissionPeriod;this.spray(n,emitter.last,2);}
        const glow=this.textures.colors.get(this.colors[n.hand]||this.colors.unassigned);
        ctx.globalAlpha=.8;ctx.drawImage(glow,0,0,glow.width,glow.height,key.x,line-17,key.width,24);
        this.lastEmitters.push({pitch,x:key.x,width:key.width});
        this.lastEffects.push({kind:'held',pitch,x:key.x,width:key.width});
      }
      this.pulses=this.pulses.filter(p=>now-p.born<220);
      for(const p of this.pulses){const key=layout.byMidi[p.pitch];if(!key)continue;
        const color=this.colors[p.hand]||this.colors.unassigned,strength=1-(now-p.born)/220;
        const texture=this.textures.colors.get(color);
        ctx.globalAlpha=strength;ctx.drawImage(texture,0,0,texture.width,texture.height,key.x,line-17,key.width,24);
        this.lastEffects.push({kind:'attack',pitch:p.pitch,x:key.x,width:key.width});
      }
      if(!this.reducedMotion)this.paintParticles(ctx,layout,width,line,now);

    }
    ctx.globalAlpha=1;ctx.lineWidth=1;
    this.lastLine=line;return line;
  }

  inspect() {
    return {enabled:this.enabled,reduced_motion:this.reducedMotion,impacts:this.impactCount,
      particles:this.particles.length,particle_limit:this.particleLimit,pulses:this.pulses.length,
      line:this.lastLine,cells:this.lastCells.slice(0,512),visible_cells:this.lastCells.length,
      effects:this.lastEffects.slice(0,160),emitters:this.lastEmitters.slice(0,88),trails:this.lastTrails.slice(0,64),particle_scale:this.fxScale,history:this.history.slice()};
  }
}
window.PianoRollRenderer=PianoRollRenderer;
