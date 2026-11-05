# 第三方资源

## Lucide 图标（app.js 里的 ICONS）

图标的造型（SVG 路径）来自 Lucide（https://lucide.dev），按原样内联在页面里。

ISC License

Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as part of Feather (MIT). All other copyright (c) for Lucide are held by Lucide Contributors 2022.

Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted, provided that the above copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

Feather 部分（MIT License）：Copyright (c) 2013-2022 Cole Bemis

## 动作配图（wger）

动作库的配图来自开源健身项目 wger（https://wger.de），每张图的作者、许可（CC BY-SA 3.0 或 CC BY-SA 4.0）和来源记在 `ironm_agent/exercise_images.yaml`，动作详情里逐张署名。图片文件由 `scripts/fetch_exercise_images.py` 下载到服务器的数据目录，不放进仓库。

## 动作配图（Everkinetic）

一部分动作的配图来自 Everkinetic 开源动作库（https://github.com/everkinetic/data，作者 Everkinetic，CC BY-SA 4.0），清单在 `ironm_agent/exercise_images_everkinetic.yaml`，图片文件由 `scripts/fetch_everkinetic_images.py` 下载到服务器的数据目录，不放进仓库。

## 动作动图（由上面两处的图合成）

有起止两张图的动作，由 `scripts/make_exercise_gifs.py` 把两张对齐、铺白底、缩小后合成来回切换的动图（改编作品），沿用原图的许可（CC BY-SA），页面署原图作者并注明"由两张图合成"。其余配图按原样显示。

- CC BY-SA 3.0：https://creativecommons.org/licenses/by-sa/3.0/
- CC BY-SA 4.0：https://creativecommons.org/licenses/by-sa/4.0/

## 饮食配图（Wikimedia Commons）

食物库里的原料和菜品、推荐食谱、减脂餐的配图来自 Wikimedia Commons（https://commons.wikimedia.org），只收允许再用的许可（CC0、CC BY、CC BY-SA、公有领域）。每张图的作者、许可和来源记在 `ironm_agent/food_images.yaml`，食谱页和饮食记录里署名。图片按原样显示（缩略图），未做修改。图片文件由 `scripts/fetch_food_images.py` 下载到服务器的数据目录，不放进仓库。

## 训练和饮食照片（Unsplash、Pexels）

训练（按部位）、推荐食谱、减脂餐、常见食物的照片来自 Unsplash（Unsplash License，https://unsplash.com/license）和 Pexels（Pexels License，https://www.pexels.com/license/），都是免费许可，不收 Unsplash+ 付费图。每张照片的作者、来源页写在 `ironm_agent/food_images.yaml`，页面上署名。照片文件由 `scripts/fetch_stock_images.py` 下载到本机数据目录，不随仓库分发。

## 像素字体（缝合像素字体 Fusion Pixel Font）

`fusion-pixel-12px-zh_hans.woff2`：缝合像素字体 12px 比例宽度简体中文版 v2026.10.25，作者 TakWolf，来源 https://github.com/TakWolf/fusion-pixel-font ，SIL Open Font License 1.1；字体合并了方舟像素字体、俐方体11号、Galmuri 的字形。许可原文（含合并字体的许可）在 `fusion-pixel-LICENSE.txt`。

## 食物营养数据（USDA FoodData Central）

食物库（`ironm_agent/foods.yaml`）里原料每 100 克的营养，主要按美国农业部 USDA FoodData Central（https://fdc.nal.usda.gov，公有领域）等公开资料整理并取整，个别中式食物参考常见公开数据；内容待审定。

## 动作数据参考（free-exercise-db）

第二批动作的名称和主次肌肉参考了 free-exercise-db（https://github.com/yuhonas/free-exercise-db，The Unlicense，公有领域）。中文的做法、要点等内容是自己写的，没有使用它的文字和图片（图片来源不明）。

## 平面肌肉图（musclemap-v1.json）

数据页主图（正面、背面的平面肌肉图）的图形来自 MuscleMap（https://github.com/melihcolpan/MuscleMap），作者 Melih Colpan，MIT 许可。它的路径数据写在 Swift 源码里，这里原样转成了 JSON（男女正面、背面四张图，分区名和路径都没改）。openGym 用的也是这套图；openGym 自己的代码是 AGPL，这里没有用它的代码。

MIT License

Copyright (c) 2026 Melih Colpan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
