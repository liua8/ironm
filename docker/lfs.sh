#!/bin/sh
# 构建镜像时用（spec §185 需求 5）：vendor/mirobody 里两个大数据文件走 git-lfs。
# 没装 git-lfs 或下载的是压缩包时，拿到的只是几行占位文字（里面记着文件的 sha256），
# 这时从上游 mirobody 同一版本（1.5.8，提交 7775b50）下载，校验和对上才用。
set -eu
UPSTREAM="https://media.githubusercontent.com/media/thetahealth/mirobody/7775b50a55e17c98e1c02dfb93fb544dbccd1504"
for f in mirobody/res/loinc/fhir_loinc_bundle.tar.gz mirobody/res/genomics/cpic-v1.60.0.json.gz; do
  path="vendor/mirobody/$f"
  if ! head -c 100 "$path" | grep -q "git-lfs"; then
    continue
  fi
  oid="$(sed -n 's/^oid sha256:\([0-9a-f]*\)$/\1/p' "$path")"
  echo "取 git-lfs 数据文件：$f"
  if ! curl -fsSL --retry 3 --max-time 600 -o "$path.download" "$UPSTREAM/$f"; then
    rm -f "$path.download"
    cat >&2 <<EOF
下不到 $f（git-lfs 数据文件，大约 1–13 MB）。三个办法任选一个，然后再跑 docker compose up -d --build：
  1. 用 git clone 拿的代码：装 git-lfs，在仓库目录里跑 git lfs install && git lfs pull
  2. 下载压缩包拿的代码：用浏览器打开下面这个地址下载，放到仓库里的 $path（替换掉原来那个小文件）
     $UPSTREAM/$f
  3. 换一个能上 GitHub 的网络重试
EOF
    exit 1
  fi
  got="$(sha256sum "$path.download" | cut -d' ' -f1)"
  if [ "$got" != "$oid" ]; then
    rm -f "$path.download"
    echo "下回来的 $f 校验和不对（要 $oid，得到 $got），不用它。" >&2
    exit 1
  fi
  mv "$path.download" "$path"
done
