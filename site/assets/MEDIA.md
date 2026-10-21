# Showcase media / 展示素材

The original three demos are actual native AppCore windows running ultralight-py 0.5.0. Ashen Reliquary adds a native still capture using 0.6.1 and an interactive browser demo. No image-generation outputs are included in the website. The original three samples provide an animated WebP, a PNG poster for motion controls, and a separate full-size PNG screenshot. Ashen provides a still image and browser play instead of an animation. WebP timing follows the captured frame timestamps; images are resized and compressed, with no audio or composited outputs.

三个样例均由真实原生应用运行后录制。设计稿只用于网页布局参考，不作为应用演示素材。原始帧、执行日志及机器报告保存在根 `.tmp/site-redesign/`，不发布。

| Sample | Animated demo | Still screenshot | Source / license |
| --- | --- | --- | --- |
| Emberkeep | `emberkeep-demo.webp` — actual exploration and combat from a seeded normal run | `emberkeep.png` | [Source](https://github.com/shabbywu/emberkeep), [MIT](emberkeep-LICENSE.txt) |
| PianoScope | `pianoscope-demo.webp` — original MusicXML “初光 / First Light”, real SoundFont/DAC playback | `pianoscope.png` — lazily engraved grand-staff view | [Source](https://github.com/shabbywu/ultralight-py-showcase/tree/main/examples/pianoscope), [MIT](pianoscope-LICENSE.txt), [component notice](pianoscope-NOTICE.md) |
| Bridge Lab | `bridge-lab-demo.webp` — real edited function output, object proxy and asynchronous Promise | `bridge-lab.png` | [Source](https://github.com/shabbywu/ultralight-py-showcase/tree/main/examples/bridge-lab), [source & usage notice](bridge-lab-NOTICE.md) |

`*-poster.png` is a real first frame of the corresponding animation. Recorded application interfaces may retain their original language; the website navigation, descriptions, controls, alt text and notices are localized independently.

应用内文字保留录制时的原貌；站点的导航、介绍、控件与替代文字分别提供完整中文和英文。音源、字体、原生库及其他组件仍遵循各自许可，网页中不分发这些原文件。本站新增代码与 Bridge Lab 暂未指定统一许可，不能将来源说明视为额外许可授权。

Ashen Reliquary: `ashen-reliquary.png` is a native CPU View capture made for publication, with quickbar bindings initialized for display. The independent browser build ships at `demos/ashen-reliquary/`. See [source and artwork notices](ashen-reliquary-NOTICE.md). No regression was rerun for publication.
