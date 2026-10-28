# 第三方资源

## Lucide 图标（app.js 里的 ICONS）

图标的造型（SVG 路径）来自 Lucide（https://lucide.dev），按原样内联在页面里。

ISC License

Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as part of Feather (MIT). All other copyright (c) for Lucide are held by Lucide Contributors 2022.

Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted, provided that the above copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

Feather 部分（MIT License）：Copyright (c) 2013-2022 Cole Bemis

## 动作配图（wger）

动作库的配图来自开源健身项目 wger（https://wger.de），每张图的作者、许可（CC BY-SA 3.0 或 CC BY-SA 4.0）和来源记在 `ironm_agent/exercise_images.yaml`，动作详情里逐张署名。图片按原样显示，未做修改。图片文件由 `scripts/fetch_exercise_images.py` 下载到服务器的数据目录，不放进仓库。

- CC BY-SA 3.0：https://creativecommons.org/licenses/by-sa/3.0/
- CC BY-SA 4.0：https://creativecommons.org/licenses/by-sa/4.0/

## 动作数据参考（free-exercise-db）

第二批动作的名称和主次肌肉参考了 free-exercise-db（https://github.com/yuhonas/free-exercise-db，The Unlicense，公有领域）。中文的做法、要点等内容是自己写的，没有使用它的文字和图片（图片来源不明）。

## 3D 肌肉模型（muscles-v1.glb）

数据页的 3D 人体图用的模型 `muscles-v1.glb` 来自 Gymmetry 的健身改造版（https://github.com/kalibismail/gymmetry-muscle-model ，2026-10-22 版本，文件未做修改），它改编自：

- **Z-Anatomy — The libre 3D atlas of anatomy**，作者 Gauthier Kervyn（https://github.com/Z-Anatomy/Models-of-human-anatomy），CC BY-SA 4.0；
- **BodyParts3D**，The Database Center for Life Science（Kousaku Okubo）（https://dbarchive.biosciencedbc.jp/en/bodyparts3d/desc.html），CC BY-SA 2.1 Japan。

改编版的说明：只保留有名字的肌肉网格，左右合并成 44 个分区，降低面数、加了烘焙的顶点色，去掉了贴图和原材质；头部、手足骨骼和肌腱作为不可选的背景。这个模型按 **CC BY-SA 4.0** 分发（https://creativecommons.org/licenses/by-sa/4.0/），转发时要保留以上署名、许可链接和这段修改说明。两个许可都允许商用。

## three.js（three-r160-*.js）

显示 3D 模型用的 three.js r160（https://threejs.org）：`three-r160.module.min.js` 是原版文件；`three-r160-gltf-loader.js`、`three-r160-orbit-controls.js`、`three-r160-geometry-utils.js` 分别来自它的 `examples/jsm/loaders/GLTFLoader.js`、`examples/jsm/controls/OrbitControls.js`、`examples/jsm/utils/BufferGeometryUtils.js`，只把 import 的路径改成同目录的文件，其余没有改动。

The MIT License

Copyright © 2010-2023 three.js authors

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
