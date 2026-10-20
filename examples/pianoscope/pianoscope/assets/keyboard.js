'use strict';
const PianoNames=['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'];
const Solfege=['Do','Di','Re','Ri','Mi','Fa','Fi','Sol','Si♭','La','Li','Si'];
const isWhite=p=>[0,2,4,5,7,9,11].includes(p%12);
const noteName=p=>PianoNames[p%12]+(Math.floor(p/12)-1);
class KeyboardLayout {
 constructor(used,mode,width){
  this.used=new Set(used);let lo=21,hi=108;
  if(mode!=='full'&&used.length){
   lo=Math.min(...used);hi=Math.max(...used);
   while(hi-lo<12){if(lo>21)lo--;if(hi<108)hi++;}
   if(!isWhite(lo))lo--;if(!isWhite(hi))hi++;
  }
  this.low=lo;this.high=hi;this.byMidi={};this.rects=[];
  const pitches=Array.from({length:hi-lo+1},(_,i)=>i+lo),whites=pitches.filter(isWhite),w=width/whites.length;
  whites.forEach((m,i)=>this.byMidi[m]={midi:m,x:i*w,width:w,center:(i+.5)*w,is_black:false,is_used:this.used.has(m)});
  pitches.filter(p=>!isWhite(p)).forEach(m=>{const x=this.byMidi[m-1].x+w-w*.3;this.byMidi[m]={midi:m,x,width:w*.6,center:x+w*.3,is_black:true,is_used:this.used.has(m)}});
  this.rects=pitches.map(p=>this.byMidi[p]);
 }
 noteRect(note,strike,t,pps){const k=this.byMidi[note.pitch];if(!k)return null;const bottom=strike-(note.start_s-t)*pps,top=strike-(note.key_off_s-t)*pps;return {x:k.center-k.width*.41,y:Math.min(top,bottom-3),width:k.width*.82,height:Math.max(3,bottom-top),center:k.center,bottom};}
}
window.KeyboardLayout=KeyboardLayout;
