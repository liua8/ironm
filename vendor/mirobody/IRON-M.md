# 这份 mirobody 是 iron-m 的一部分

iron-m（AI 健身管家）以 mirobody 为健康数据底座，并在它的架构上修改（iron-m `spec/spec.md` [2026-10-23] §24、§25）。
从 2026-10-24 起，这个目录不再是指向上游的子模块，而是 iron-m 仓库里的普通目录，改动直接提交在 iron-m 里。

- 上游：https://github.com/thetahealth/mirobody
- 基于的上游版本：1.5.8（提交 7775b50a55e17c98e1c02dfb93fb544dbccd1504）
- 许可：Apache-2.0（见本目录 `LICENSE`、`LICENSE-3RD-PARTY`），版权声明保持不变；LOINC 等第三方资料按 `LICENSE-3RD-PARTY` 使用
- 改动登记：每一处改动登记在 iron-m `spec/spec.md` §24 的改动清单里（改了什么、为什么、通用还是健身专用）；
  改过的文件在文件开头注明"iron-m 修改"，以满足 Apache-2.0 第 4 条（b）的要求
- 同步上游：拿上游新版本和 1.5.8 比出差异，再合进这里；通用的改动可以整理后提交回上游

截至合入时，这个目录里的文件和上游 1.5.8 完全一致。
