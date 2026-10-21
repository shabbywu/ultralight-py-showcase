# Showcase media / 展示素材

All four demos are recorded from actual native AppCore windows. The original three use ultralight-py 0.5.0; Ashen Reliquary uses 0.6.1 with its authoritative Python backend. Each provides an animated WebP, its first frame as a PNG poster, and a separate full-size PNG screenshot. Timing follows captured frame timestamps. Images are resized and compressed without generated frames, composited output or audio. The website does not host standalone browser games.

四个样例均由真实原生应用运行后录制。设计稿只用于网页布局参考，不作为应用演示素材。原始三个样例的录制材料保存在 `.tmp/site-redesign/`，Ashen Reliquary 原始帧与时间戳保存在 `.tmp/ashen-reliquary/recording/`，不发布。

| Sample | Animated demo | Still screenshot | Source / license |
| --- | --- | --- | --- |
| Emberkeep | `emberkeep-demo.webp` — actual exploration and combat from a seeded normal run | `emberkeep.png` | [Source](https://github.com/shabbywu/emberkeep), [MIT](emberkeep-LICENSE.txt) |
| PianoScope | `pianoscope-demo.webp` — original MusicXML “初光 / First Light”, real SoundFont/DAC playback | `pianoscope.png` — lazily engraved grand-staff view | [Source](https://github.com/shabbywu/ultralight-py-showcase/tree/main/examples/pianoscope), [MIT](pianoscope-LICENSE.txt), [component notice](pianoscope-NOTICE.md) |
| Bridge Lab | `bridge-lab-demo.webp` — real edited function output, object proxy and asynchronous Promise | `bridge-lab.png` | [Source](https://github.com/shabbywu/ultralight-py-showcase/tree/main/examples/bridge-lab), [source & usage notice](bridge-lab-NOTICE.md) |

| Ashen Reliquary | `ashen-reliquary-demo.webp` — native equipment, rotation, gem socketing, stack splitting and backend relic generation | `ashen-reliquary.png` | [Source](https://github.com/shabbywu/ultralight-py-showcase/tree/main/examples/ashen-reliquary), [source & artwork notice](ashen-reliquary-NOTICE.md) |

`*-poster.png` is a real first frame of the corresponding animation. Recorded application interfaces may retain their original language; the website navigation, descriptions, controls, alt text and notices are localized independently.

应用内文字保留录制时的原貌；站点的导航、介绍、控件与替代文字分别提供完整中文和英文。音源、字体、原生库及其他组件仍遵循各自许可，网页中不分发这些原文件。本站新增代码与 Bridge Lab 暂未指定统一许可，不能将来源说明视为额外许可授权。
